// Bounded NICE source reader with a dedicated accelerator data handshake.
// The shared SRAM still sits behind the existing E203 LSU and BIU.
module e203_subsys_nice_core #(
    parameter integer TIMEOUT = 64
) (
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
    input wire nice_icb_rsp_err,
    output wire stream_valid,
    input wire stream_ready, stream_error, stream_cancel,
    output wire [31:0] stream_data
);
    localparam [31:0] STAGING_BASE = 32'ha0026000;
    localparam [31:0] STAGING_END = 32'ha0036000;
    localparam [2:0] IDLE=0, READ_REQ=1, READ_RSP=2, HOLD=3, REPLY=4;
    localparam [2:0] OK=0, SOURCE_ERROR=1, WAIT_TIMEOUT=2, CANCELLED=3, SINK_ERROR=4;
    localparam TIMER_WIDTH = $clog2(TIMEOUT);
    localparam [TIMER_WIDTH-1:0] TIMER_LAST = TIMER_WIDTH'(TIMEOUT-1);
    reg [2:0] state, first_error;
    reg [15:0] source_offset;
    reg [6:0] remaining, completed;
    reg [31:0] payload;
    reg [TIMER_WIDTH-1:0] timer;

    wire [32:0] source_end = {1'b0,nice_req_rs1} + {24'b0,nice_req_rs2[6:0],2'b0};
    wire legal = nice_req_inst[31:25] == 7'h28 && nice_req_inst[14:12] == 3'h7 &&
                 nice_req_inst[6:0] == 7'h7b && nice_req_rs1[1:0] == 0 &&
                 nice_req_rs1 >= STAGING_BASE && source_end <= {1'b0,STAGING_END} &&
                 nice_req_rs2 >= 1 && nice_req_rs2 <= 64;
    wire [2:0] stop = first_error != OK ? first_error :
                      stream_cancel ? CANCELLED : stream_error ? SINK_ERROR : OK;
    wire response_word = state == READ_RSP && nice_icb_rsp_valid && !nice_icb_rsp_err;

    assign nice_req_ready = state == IDLE;
    assign nice_active = nice_req_valid || !nice_req_ready;
    assign nice_mem_holdup = !nice_req_ready;
    assign nice_rsp_valid = state == REPLY;
    assign nice_rsp_err = 1'b0;
    assign nice_icb_cmd_valid = state == READ_REQ;
    assign nice_icb_cmd_read = 1'b1;
    assign nice_icb_cmd_addr = STAGING_BASE + {16'b0,source_offset};
    assign nice_icb_cmd_wdata = 0;
    assign nice_icb_cmd_size = 2'b10;
    assign nice_icb_rsp_ready = state == READ_RSP;
    assign stream_valid = stop == OK && (response_word || state == HOLD);
    assign stream_data = state == HOLD ? payload : nice_icb_rsp_rdata;

    task automatic fail(input [2:0] cause);
        begin
            // rd[14:8] counts words committed before the first fault.
            nice_rsp_rdat <= {1'b1,16'b0,completed,5'b0,cause};
            state <= REPLY;
        end
    endtask

    task automatic advance;
        begin
            timer <= 0;
            if (remaining == 1) begin
                nice_rsp_rdat <= 0;
                state <= REPLY;
            end else begin
                source_offset <= source_offset + 16'd4;
                completed <= completed + 1'b1;
                remaining <= remaining - 1'b1;
                state <= READ_REQ;
            end
        end
    endtask

    always @(posedge nice_clk or negedge nice_rst_n) begin
        if (!nice_rst_n) begin
            state <= IDLE;
            source_offset <= 0;
            completed <= 0;
            remaining <= 0;
            payload <= 0;
            timer <= 0;
            first_error <= OK;
            nice_rsp_rdat <= 0;
        end else begin
            case (state)
                IDLE: if (nice_req_valid) begin
                    if (legal) begin
                        source_offset <= 16'(nice_req_rs1 - STAGING_BASE);
                        remaining <= nice_req_rs2[6:0];
                        completed <= 0;
                        timer <= 0;
                        first_error <= OK;
                        state <= READ_REQ;
                    end else begin
                        nice_rsp_rdat <= -32'd3;
                        state <= REPLY;
                    end
                end
                READ_REQ, READ_RSP: begin
                    // A visible ICB request cannot be withdrawn. Retain the
                    // first error and drain the issued read before replying.
                    // With no physical response only fabric reset can exit.
                    if (first_error == OK) begin
                        if (stop != OK) first_error <= stop;
                        else if (timer == TIMER_LAST) first_error <= WAIT_TIMEOUT;
                        else timer <= timer + 1'b1;
                    end
                    if (state == READ_REQ && nice_icb_cmd_ready) begin
                        state <= READ_RSP;
                        timer <= 0;
                    end
                    if (state == READ_RSP && nice_icb_rsp_valid) begin
                        timer <= 0;
                        if (stop != OK) fail(stop);
                        else if (nice_icb_rsp_err) fail(SOURCE_ERROR);
                        else if (stream_ready) advance();
                        else begin
                            payload <= nice_icb_rsp_rdata;
                            state <= HOLD;
                        end
                        // A handshake at the limit beats the response timeout.
                        first_error <= OK;
                    end
                end
                HOLD: begin
                    if (stop != OK) fail(stop);
                    else if (stream_ready) advance();
                    else if (timer == TIMER_LAST) fail(WAIT_TIMEOUT);
                    else timer <= timer + 1'b1;
                end
                REPLY: if (nice_rsp_ready) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
