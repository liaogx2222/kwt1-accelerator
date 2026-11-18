// Adds the dense consumer to the validated E203 supply subsystem.
module e203_subsys_nice_core (
    input wire nice_clk,nice_rst_n,
    output wire nice_active,nice_mem_holdup,
    input wire nice_req_valid,
    output wire nice_req_ready,
    input wire [31:0] nice_req_inst,nice_req_rs1,nice_req_rs2,
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
    output wire lease_hold,reset_required,
    input wire range_valid,range_weight,finish_frame,
    input wire [14:0] range_start,range_words,
    output wire range_ready,
    output wire aux_valid,
    input wire aux_ready,
    output wire [14:0] aux_index,
    output wire [31:0] aux_data,
    output wire aux_last,
    output wire tile_valid,
    output wire [2:0] tile_id,
    output wire tile_deep,
    input wire dense_start,dense_wide,act_write,
    output wire dense_ready,act_ready,dense_done,
    input wire [8:0] act_addr,
    input wire [127:0] act_data,
    output wire raw_accept,
    output wire [9:0] raw_tag,
    output wire [127:0] raw_data,
    output wire dense_valid,
    input wire dense_result_ready,
    output wire [9:0] dense_tag,
    output wire [31:0] dense_data,
    output wire dense_error,coeff_phase,mac_phase,rq_phase,
    input wire [3:0] scratch_en,scratch_we,
    input wire [47:0] scratch_addr,
    input wire [63:0] scratch_wdata,
    output wire [63:0] scratch_rdata
);
    wire physical_range_ready,physical_aux_valid,coeff_request,coeff_ready,bank_abort;
    wire [14:0] coeff_start;
    wire a_en,a_we,tile_read,tile_ready,tile_response;
    wire [9:0] a_addr,tile_addr;
    wire [127:0] a_wdata,tile_data;
    wire [191:0] compute_rdata;
    wire [95:0] a_addresses={8{{2'b0,a_addr}}};
    wire dense_abort=cancel||reset_required||bank_abort;
    assign range_ready=physical_range_ready&&!coeff_request;
    assign aux_valid=physical_aux_valid&&!coeff_phase;
    assign scratch_rdata=compute_rdata[191:128];

    kwt_e203_dense_body supply (
        .nice_clk(nice_clk),.nice_rst_n(nice_rst_n),.nice_active(nice_active),.nice_mem_holdup(nice_mem_holdup),
        .nice_req_valid(nice_req_valid),.nice_req_ready(nice_req_ready),.nice_req_inst(nice_req_inst),
        .nice_req_rs1(nice_req_rs1),.nice_req_rs2(nice_req_rs2),.nice_rsp_valid(nice_rsp_valid),
        .nice_rsp_ready(nice_rsp_ready),.nice_rsp_rdat(nice_rsp_rdat),.nice_rsp_err(nice_rsp_err),
        .nice_icb_cmd_valid(nice_icb_cmd_valid),.nice_icb_cmd_ready(nice_icb_cmd_ready),
        .nice_icb_cmd_addr(nice_icb_cmd_addr),.nice_icb_cmd_read(nice_icb_cmd_read),
        .nice_icb_cmd_wdata(nice_icb_cmd_wdata),.nice_icb_cmd_size(nice_icb_cmd_size),
        .nice_icb_rsp_valid(nice_icb_rsp_valid),.nice_icb_rsp_ready(nice_icb_rsp_ready),
        .nice_icb_rsp_rdata(nice_icb_rsp_rdata),.nice_icb_rsp_err(nice_icb_rsp_err),
        .lease_valid(lease_valid),.cancel(cancel||dense_error),.bank_available(bank_available),
        .lease_base(lease_base),.lease_words(lease_words),.lease_epoch(lease_epoch),
        .lease_hold(lease_hold),.reset_required(reset_required),
        .range_valid(coeff_request||range_valid),.range_weight(!coeff_request&&range_weight),.finish_frame(finish_frame&&!coeff_phase),
        .range_start(coeff_request?coeff_start:range_start),.range_words(coeff_request?15'd16:range_words),
        .range_ready(physical_range_ready),.aux_valid(physical_aux_valid),.aux_ready(coeff_phase?coeff_ready:aux_ready),
        .aux_index(aux_index),.aux_data(aux_data),.aux_last(aux_last),
        .tile_valid(tile_valid),.tile_id(tile_id),.tile_deep(tile_deep),.tile_done(dense_done),
        .tile_read(tile_read),.tile_addr(tile_addr),.tile_ready(tile_ready),.tile_response(tile_response),.tile_data(tile_data),
        .compute_en({scratch_en,{8{a_en}}}),.compute_we({scratch_we,{8{a_we}}}),
        .compute_addr({scratch_addr,a_addresses}),.compute_wdata({scratch_wdata,a_wdata}),.compute_rdata(compute_rdata),
        .bank_abort(bank_abort));

    kwt_compact_dense dense (
        .clk(nice_clk),.rst_n(nice_rst_n),.abort(dense_abort),
        .start_valid(dense_start),.wide_a(dense_wide),.start_ready(dense_ready),
        .act_write(act_write),.act_addr(act_addr),.act_data(act_data),.act_ready(act_ready),
        .a_en(a_en),.a_we(a_we),.a_addr(a_addr),.a_wdata(a_wdata),.a_rdata(compute_rdata[127:0]),
        .tile_valid(tile_valid),.tile_id(tile_id),.tile_done(dense_done),.tile_read(tile_read),
        .tile_addr(tile_addr),.tile_ready(tile_ready),.tile_response(tile_response),.tile_data(tile_data),
        .coeff_request(coeff_request),.coeff_grant(physical_range_ready),.coeff_start(coeff_start),
        .aux_valid(physical_aux_valid),.aux_ready(coeff_ready),.aux_index(aux_index),.aux_data(aux_data),.aux_last(aux_last),
        .raw_accept(raw_accept),.raw_tag(raw_tag),.raw_data(raw_data),.result_valid(dense_valid),
        .result_ready(dense_result_ready),.result_tag(dense_tag),.result_data(dense_data),.error(dense_error),
        .coeff_phase(coeff_phase),.mac_phase(mac_phase),.rq_phase(rq_phase));
endmodule
