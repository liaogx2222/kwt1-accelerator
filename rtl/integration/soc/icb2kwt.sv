// =============================================================================
// icb2kwt -- E203 sysper ICB slave  ->  kwt1_mmio request/response bridge
// -----------------------------------------------------------------------------
// E203 side (source: e203_hbirdv2/rtl/e203/subsys/e203_subsys_top.v:127-138)
//   sysper_icb_cmd_valid / _ready : request accepted at valid && ready
//   sysper_icb_cmd_addr[31:0]     : E203_ADDR_SIZE = 32 (core/config.v:43)
//   sysper_icb_cmd_read           : 1 = read,  0 = write
//   sysper_icb_cmd_wdata[31:0]
//   sysper_icb_cmd_wmask[3:0]
//   sysper_icb_rsp_valid / _ready : response consumed at valid && ready
//   sysper_icb_rsp_err / _rdata
//   (sysper_icb_cmd_lock / _excl / _size / _burst are NOT brought out of
//    e203_subsys_perips.v, so AMO and unaligned split accesses cannot be
//    expressed on this port; firmware must use plain LW/SW.)
//
// Keyword-transformer side (source: rtl/v2/kwt1_mmio.sv)
//   req_valid/ready, req_write, req_addr[31:0], req_wdata, req_wstrb[3:0]
//   resp_valid/ready, resp_rdata, resp_error
//
// Mapping
//   req_write = ~icb_cmd_read        <-- polarity is INVERTED, this is the
//                                        single most common integration bug
//   req_addr  = {16'h0, icb_cmd_addr[15:0]}
//   req_wstrb = icb_cmd_wmask        (kwt1_mmio accepts only 4'hf; a partial
//                                     write is answered with resp_error, which
//                                     is the intended behaviour -- see
//                                     INTERFACE_CONTRACT.md "只支持完整字写入")
//
// Address decode
//   Every request reaching this bridge has already missed ITCM(0x8000_0000),
//   DTCM(0x9000_0000), CLINT(0x0200_0000), PLIC(0x0C00_0000), FIO(0xF000_0000),
//   PPI(0x1000_0000) and the APB peripherals: sysper is the 12th and last port
//   of the perips ICB fanout (e203_subsys_perips.v:679-700).  We still decode
//   addr[31:16] == BASE_HI, so that a runaway access into an unmapped region is
//   answered with rsp_err instead of being mistaken for a START command
//   (a write of 0x0000_0001 to offset 0 would launch a task).
//   BASE_HI defaults to 0x4000 because E203 occupies none of that window:
//     0x0200_0000 CLINT | 0x0C00_0000 PLIC | 0x1000_0000 PPI
//     0x8000_0000 ITCM  | 0x9000_0000 DTCM | 0xF000_0000 FIO
//
// Response arbitration
//   kwt1_mmio holds resp_valid until resp_ready, and its resp_ready is exactly
//   icb_rsp_ready.  An unmapped request is answered by the one-shot register
//   err_rsp_valid.  The two can never be valid at the same time because an
//   unmapped request is only accepted while (!resp_valid && !err_rsp_valid),
//   so the ICB master never sees two responses for one request.
//
// Reset
//   rst_n is asynchronous-assert / synchronous-deassert at SoC level (see
//   INTERFACE_CONTRACT.md, "总线").  This module only uses it asynchronously
//   for its own single flop; the reset synchroniser lives in soc_top.
// =============================================================================
`timescale 1ns/1ps

module icb2kwt #(
  parameter [15:0] BASE_HI = 16'h4000    // addr[31:16] must equal this
)(
  input  wire        clk,
  input  wire        rst_n,

  // ---- E203 sysper ICB slave port --------------------------------------
  input  wire        icb_cmd_valid,
  output wire        icb_cmd_ready,
  input  wire [31:0] icb_cmd_addr,
  input  wire        icb_cmd_read,
  input  wire [31:0] icb_cmd_wdata,
  input  wire [3:0]  icb_cmd_wmask,

  output wire        icb_rsp_valid,
  input  wire        icb_rsp_ready,
  output wire        icb_rsp_err,
  output wire [31:0] icb_rsp_rdata,

  // ---- kwt1_mmio request/response --------------------------------------
  output wire        req_valid,
  input  wire        req_ready,
  output wire        req_write,
  output wire [31:0] req_addr,
  output wire [31:0] req_wdata,
  output wire [3:0]  req_wstrb,

  input  wire        resp_valid,
  output wire        resp_ready,
  input  wire [31:0] resp_rdata,
  input  wire        resp_error,

  // ---- decode observability (bridge TB only) ---------------------------
  output wire        dec_hit
);

  // ------------------------------------------------------------- decode
  wire in_range = (icb_cmd_addr[31:16] == BASE_HI);
  assign dec_hit = in_range;

  // --------------------------------------------------------- request path
  assign req_valid = icb_cmd_valid && in_range;
  assign req_write = ~icb_cmd_read;
  assign req_addr  = {16'h0000, icb_cmd_addr[15:0]};
  assign req_wdata = icb_cmd_wdata;
  assign req_wstrb = icb_cmd_wmask;

  // ------------------------------------------------- unmapped response path
  reg  err_rsp_valid;
  wire err_accept = icb_cmd_valid && !in_range && !err_rsp_valid && !resp_valid;
  wire err_take   = err_rsp_valid && icb_rsp_ready && !resp_valid;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)          err_rsp_valid <= 1'b0;
    else if (err_take)   err_rsp_valid <= 1'b0;
    else if (err_accept) err_rsp_valid <= 1'b1;
  end

  assign icb_cmd_ready = in_range ? req_ready : err_accept;

  // ------------------------------------------------------ response path
  // resp_valid has priority: it belongs to a request accepted earlier.
  assign icb_rsp_valid = resp_valid | err_rsp_valid;
  assign icb_rsp_err   = resp_valid ? resp_error : 1'b1;
  assign icb_rsp_rdata = resp_valid ? resp_rdata : 32'h0000_0000;
  assign resp_ready    = icb_rsp_ready && !err_rsp_valid;

endmodule
