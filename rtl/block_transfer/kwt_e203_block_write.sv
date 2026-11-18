// Reference E203 NICE overlay. Uses the existing LSU for both SRAM and PPI.
// custom3/funct3=7/funct7=0x28: (source, word count) -> first error, or zero.
`include "e203_defines.v"

module e203_subsys_nice_core (
    input wire nice_clk, nice_rst_n,
    output wire nice_active, nice_mem_holdup,
    input wire nice_req_valid,
    output wire nice_req_ready,
    input wire [31:0] nice_req_inst, nice_req_rs1, nice_req_rs2,
    output wire nice_rsp_valid,
    input wire nice_rsp_ready,
    output reg [31:0] nice_rsp_rdat,
    output wire nice_rsp_err,
    output wire nice_icb_cmd_valid,
    input wire nice_icb_cmd_ready,
    output wire [31:0] nice_icb_cmd_addr,
    output wire nice_icb_cmd_read,
    output wire [31:0] nice_icb_cmd_wdata,
    output wire [1:0] nice_icb_cmd_size,
    input wire nice_icb_rsp_valid,
    output wire nice_icb_rsp_ready,
    input wire [31:0] nice_icb_rsp_rdata,
    input wire nice_icb_rsp_err
);
    localparam [31:0] STAGING_BASE = 32'ha0026000;
    localparam [31:0] STAGING_END = 32'ha0036000;
    localparam [31:0] PARAM_DATA = 32'h10000010;
    localparam [2:0] IDLE=0, READ_REQ=1, READ_RSP=2, WRITE_REQ=3, WRITE_RSP=4, REPLY=5;
    reg [2:0] state;
    reg [15:0] source_offset;
    reg [6:0] remaining;
    reg [31:0] payload;
    wire [32:0] source_end = {1'b0,nice_req_rs1} + {24'b0,nice_req_rs2[6:0],2'b0};
    wire legal = nice_req_inst[31:25] == 7'h28 && nice_req_inst[14:12] == 3'h7 &&
                 nice_req_inst[6:0] == 7'h7b && nice_req_rs1[1:0] == 0 &&
                 nice_req_rs1 >= STAGING_BASE && source_end <= {1'b0,STAGING_END} &&
                 nice_req_rs2 >= 1 && nice_req_rs2 <= 64;

    assign nice_req_ready = state == IDLE;
    assign nice_active = nice_req_valid || !nice_req_ready;
    assign nice_mem_holdup = !nice_req_ready;
    assign nice_rsp_valid = state == REPLY;
    // Report a software status through rd. The blocking instruction retires
    // normally so the driver can run ABORT or quarantine the active lease.
    assign nice_rsp_err = 1'b0;
    assign nice_icb_cmd_valid = state == READ_REQ || state == WRITE_REQ;
    assign nice_icb_cmd_read = state == READ_REQ;
    assign nice_icb_cmd_addr = nice_icb_cmd_read ? STAGING_BASE + {16'b0,source_offset} : PARAM_DATA;
    assign nice_icb_cmd_wdata = payload;
    assign nice_icb_cmd_size = 2'b10;
    assign nice_icb_rsp_ready = state == READ_RSP || state == WRITE_RSP;

    always @(posedge nice_clk or negedge nice_rst_n) begin
        if (!nice_rst_n) begin
            state <= IDLE;
            source_offset <= 0;
            remaining <= 0;
            payload <= 0;
            nice_rsp_rdat <= 0;
        end else begin
            case (state)
                IDLE: if (nice_req_valid) begin
                    if (legal) begin
                        source_offset <= 16'(nice_req_rs1 - STAGING_BASE);
                        remaining <= nice_req_rs2[6:0];
                        state <= READ_REQ;
                    end else begin
                        nice_rsp_rdat <= -32'd3;
                        state <= REPLY;
                    end
                end
                READ_REQ: if (nice_icb_cmd_ready) state <= READ_RSP;
                READ_RSP: if (nice_icb_rsp_valid) begin
                    if (nice_icb_rsp_err) begin
                        nice_rsp_rdat <= -32'd1;
                        state <= REPLY;
                    end else begin
                        payload <= nice_icb_rsp_rdata;
                        state <= WRITE_REQ;
                    end
                end
                WRITE_REQ: if (nice_icb_cmd_ready) state <= WRITE_RSP;
                WRITE_RSP: if (nice_icb_rsp_valid) begin
                    if (nice_icb_rsp_err || nice_icb_rsp_rdata != 0 || remaining == 1) begin
                        nice_rsp_rdat <= nice_icb_rsp_err ? -32'd1 : nice_icb_rsp_rdata;
                        state <= REPLY;
                    end else begin
                        source_offset <= source_offset + 16'd4;
                        remaining <= remaining - 1'b1;
                        state <= READ_REQ;
                    end
                end
                REPLY: if (nice_rsp_ready) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule

// The existing bridge puts per-transaction error in bus_rc on entry to REPLY.
// Return it as write-response data on DATA writes, which ordinary stores ignore.
// Reads and non-DATA writes retain the existing contract.
module kwt_block_write_response (
    input wire clk, rst_n, cmd_fire, cmd_read,
    input wire [31:0] cmd_addr, bus_rc, original_data,
    output wire [31:0] response_data
);
    reg data_write;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) data_write <= 0;
        else if (cmd_fire) data_write <= !cmd_read && cmd_addr == 32'h10000010;
    end
    assign response_data = data_write ? bus_rc : original_data;
endmodule
