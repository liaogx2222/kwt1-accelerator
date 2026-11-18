// Reference E203 integration. The only shared SRAM port is the existing LSU.
// custom3 / funct3=7 / funct7=0x29 holds one canonical lease until completion.
module e203_subsys_nice_core (
    input wire nice_clk, nice_rst_n,
    output wire nice_active, nice_mem_holdup,
    input wire nice_req_valid,
    output wire nice_req_ready,
    input wire [31:0] nice_req_inst, nice_req_rs1, nice_req_rs2,
    output wire nice_rsp_valid,
    input wire nice_rsp_ready,
    output wire [31:0] nice_rsp_rdat,
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

    input wire lease_valid, cancel, bank_available,
    input wire [31:0] lease_base,
    input wire [14:0] lease_words,
    input wire [15:0] lease_epoch,
    output wire lease_hold, reset_required,
    input wire range_valid, range_weight, finish_frame,
    input wire [14:0] range_start, range_words,
    output wire range_ready,
    output wire aux_valid,
    input wire aux_ready,
    output wire [14:0] aux_index,
    output wire [31:0] aux_data,
    output wire aux_last,
    output wire tile_valid,
    output wire [2:0] tile_id,
    output wire tile_deep,
    input wire tile_done, tile_read,
    input wire [9:0] tile_addr,
    output wire tile_ready, tile_response,
    output wire [127:0] tile_data,
    input wire [11:0] compute_en, compute_we,
    input wire [143:0] compute_addr,
    input wire [191:0] compute_wdata,
    output wire [191:0] compute_rdata
);
    wire cmd_ready, result_valid, response_ready;
    wire [3:0] error_code;
    wire [14:0] error_index, read_index, sink_index;
    wire [15:0] read_epoch;
    wire bank_request, bank_grant, bank_done, bank_aborted, bank_close;
    wire sink_valid, sink_ready, sink_abort, sink_weight, sink_range_last;
    wire [31:0] sink_data;
    reg outstanding, running, invalid_instruction, packet_common;
    reg [14:0] tag_index;
    reg [15:0] tag_epoch;
    wire instruction_ok = nice_req_inst[31:25]==7'h29 && nice_req_inst[14:12]==7 &&
                          nice_req_inst[6:0]==7'h7b && nice_req_rs2[31:21]==0;
    wire launch = nice_req_valid && nice_req_ready;
    wire accept_result = nice_rsp_valid && nice_rsp_ready;
    assign nice_req_ready = cmd_ready && !running;
    assign nice_rsp_valid = running && (invalid_instruction || (result_valid && !outstanding));
    assign nice_rsp_rdat = invalid_instruction ? 32'h00000001 :
                           {reset_required,12'b0,error_index,error_code};
    assign nice_rsp_err = 1'b0;
    assign nice_active = running || nice_req_valid;
    assign nice_mem_holdup = running;
    assign nice_icb_cmd_read = 1'b1;
    assign nice_icb_cmd_wdata = 0;
    assign nice_icb_cmd_size = 2'b10;
    assign nice_icb_rsp_ready = outstanding && response_ready;
    assign aux_valid = sink_valid && !sink_weight;
    assign aux_index = sink_index;
    assign aux_data = sink_data;
    assign aux_last = sink_range_last;

    // Tags are captured on the physical command handshake. A timed-out
    // outstanding request holds the CPU until drained or fabric reset.
    always @(posedge nice_clk or negedge nice_rst_n) begin
        if (!nice_rst_n) begin
            running<=0; invalid_instruction<=0; outstanding<=0; packet_common<=0;
            tag_index<=0; tag_epoch<=0;
        end else begin
            if (launch) begin
                running<=1; invalid_instruction<=!instruction_ok; packet_common<=nice_req_rs2[20];
            end
            if (accept_result) running<=0;
            if (nice_icb_cmd_valid && nice_icb_cmd_ready) begin
                outstanding<=1; tag_index<=read_index; tag_epoch<=read_epoch;
            end
            if (nice_icb_rsp_valid && nice_icb_rsp_ready) outstanding<=0;
        end
    end

    kwt_indexed_block_reader #(.TIMEOUT(128)) reader (
        .clk(nice_clk),.rst_n(nice_rst_n),.cmd_valid(launch&&instruction_ok),.cmd_ready(cmd_ready),
        .cmd_base(nice_req_rs1),.cmd_words(nice_req_rs2[20]?15'd4144:15'd15432),
        .cmd_common(nice_req_rs2[20]),.cmd_layer(nice_req_rs2[19:16]),.cmd_epoch(nice_req_rs2[15:0]),
        .lease_valid(lease_valid),.lease_base(lease_base),.lease_words(lease_words),.lease_epoch(lease_epoch),
        .lease_hold(lease_hold),.cancel(cancel),.read_valid(nice_icb_cmd_valid),
        .read_ready(nice_icb_cmd_ready),.read_addr(nice_icb_cmd_addr),.read_epoch(read_epoch),.read_index(read_index),
        .rsp_valid(nice_icb_rsp_valid&&outstanding),.rsp_ready(response_ready),.rsp_epoch(tag_epoch),.rsp_index(tag_index),
        .rsp_error(nice_icb_rsp_err),.rsp_data(nice_icb_rsp_rdata),
        .bank_request(bank_request),.bank_grant(bank_grant),.bank_owned(),
        .sink_valid(sink_valid),.sink_ready(sink_weight?sink_ready:aux_ready),.sink_data(sink_data),.sink_last(),
        .sink_abort(sink_abort),.consumer_done(bank_done),.consumer_aborted(bank_aborted),
        .result_valid(result_valid),.result_ready(accept_result),.error_code(error_code),.error_index(error_index),
        .reset_required(reset_required),.range_valid(range_valid),.range_ready(range_ready),
        .range_start(range_start),.range_words(range_words),.range_weight(range_weight),
        .finish_frame(finish_frame),.bank_close(bank_close),.sink_index(sink_index),.sink_weight(sink_weight),
        .sink_range_last(sink_range_last));

    kwt_indexed_weight_banks banks (
        .clk(nice_clk),.rst_n(nice_rst_n),.bank_request(bank_request),.packet_common(packet_common),
        .bank_available(bank_available),.bank_grant(bank_grant),
        .sink_valid(sink_valid&&sink_weight),.sink_last(1'b0),.sink_abort(sink_abort),.quarantine(reset_required),
        .sink_data(sink_data),.sink_ready(sink_ready),.consumer_aborted(bank_aborted),.consumer_done(bank_done),
        .tile_valid(tile_valid),.tile_id(tile_id),.tile_deep(tile_deep),.tile_done(tile_done),.tile_read(tile_read),
        .tile_addr(tile_addr),.tile_ready(tile_ready),.tile_response(tile_response),.tile_data(tile_data),
        .compute_en(compute_en),.compute_we(compute_we),.compute_addr(compute_addr),.compute_wdata(compute_wdata),
        .compute_rdata(compute_rdata),.sink_word_index(sink_index),.close_frame(bank_close));
endmodule
