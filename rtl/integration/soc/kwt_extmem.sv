// =============================================================================
// kwt_extmem -- behavioural external memory on the E203 sysmem ICB port
// -----------------------------------------------------------------------------
// Why this block exists
//   The vendor e203_soc_top leaves the sysmem port as a stub that answers every
//   access with rdata = 0 and no error. That is fine for a boot smoke test but
//   the SoC-level functional regression has to stream the real network
//   coefficients into kwt1_mmio (common 4144 words + 12 x 15432 words = 757 KiB)
//   and neither ITCM nor DTCM is big enough (64 KiB each). A real board would
//   fetch them over QSPI/SDIO from a serial flash, so an external memory model
//   on 0x2000_0000 is the honest equivalent, not a test-only shortcut.
//
// Address map (as seen by the CPU)
//   0x2000_0000 + 4*i  ->  mem[i]      (1 MiB, mirrored inside the 0x2000_0000
//                                        region that e203_subsys_mems decodes
//                                        with O3_BASE_REGION_LSB = 29)
//
// Protocol (ICB, single outstanding, same shape as sirv_mrom_top)
//   accept  : cmd_valid && cmd_ready
//   answer  : one cycle later, rsp_valid is held until rsp_ready
//   rsp_err : always 0 -- every address inside the window is backed by memory
//
// The array is deliberately NOT reset: the testbench preloads it with
// $readmemh before releasing reset, exactly like a flash device that already
// holds an image at power-on.
// =============================================================================
`timescale 1ns/1ps

module kwt_extmem #(
  parameter AW = 18,          // 2^18 words = 1 MiB
  parameter DW = 32
)(
  input  wire          clk,
  input  wire          rst_n,

  // ---- ICB slave: command channel --------------------------------------
  input  wire          cmd_valid,
  output wire          cmd_ready,
  input  wire [31:0]   cmd_addr,
  input  wire          cmd_read,
  input  wire [31:0]   cmd_wdata,
  input  wire [3:0]    cmd_wmask,

  // ---- ICB slave: response channel -------------------------------------
  output wire          rsp_valid,
  input  wire          rsp_ready,
  output wire          rsp_err,
  output wire [DW-1:0] rsp_rdata
);

  localparam DEPTH = (1 << AW);

  reg [DW-1:0] mem [0:DEPTH-1];

  reg          rsp_valid_r;
  reg [DW-1:0] rsp_rdata_r;

  wire [AW-1:0] idx    = cmd_addr[AW+1:2];
  // A new command may be accepted in the same cycle the previous response is
  // taken, so a back-to-back stream of loads/stores never bubbles.
  assign cmd_ready = !rsp_valid_r || rsp_ready;

  wire accept = cmd_valid && cmd_ready;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rsp_valid_r <= 1'b0;
      rsp_rdata_r <= {DW{1'b0}};
    end else if (accept) begin
      rsp_valid_r <= 1'b1;
      if (cmd_read) begin
        rsp_rdata_r <= mem[idx];
      end else begin
        if (cmd_wmask[0]) mem[idx][7:0]   <= cmd_wdata[7:0];
        if (cmd_wmask[1]) mem[idx][15:8]  <= cmd_wdata[15:8];
        if (cmd_wmask[2]) mem[idx][23:16] <= cmd_wdata[23:16];
        if (cmd_wmask[3]) mem[idx][31:24] <= cmd_wdata[31:24];
        rsp_rdata_r <= {DW{1'b0}};
      end
    end else if (rsp_valid_r && rsp_ready) begin
      rsp_valid_r <= 1'b0;
    end
  end

  assign rsp_valid = rsp_valid_r;
  assign rsp_err   = 1'b0;
  assign rsp_rdata = rsp_rdata_r;

endmodule
