// =============================================================================
// kwt_soc_shared_sram -- 512 KiB system shared SRAM (competition platform block)
// -----------------------------------------------------------------------------
// SPEC (competition_original.txt, p4):
//   "system shared SRAM is 512 KB; the accelerator's internal storage must use
//    the designated 16b x 128 / 16b x 1024 / 16b x 4096 single- or dual-port
//    SRAM macros."
//   "Parameter loading is hierarchical. The organiser provides a parameter
//    loading simulation environment that writes parameters and input data into
//    the shared SRAM through an existing platform port. E203 does driver,
//    scheduling and data movement. The full model weights need NOT be resident
//    in the shared SRAM at the same time. No DDR or other external memory
//    controller is added."
//   "Area: the reused 512 KB shared SRAM is NOT counted in the 2.25 mm2 budget
//    (reported separately); its power IS counted."
//
// So this block is the platform's shared SRAM, built here from the same
// 4096 x 16 macro boundary the accelerator banks already use (kwt_sram_sp,
// which binds to RAMSP4096X16 in the SMIC40 flow). 512 KiB = 131072 x 32 bit
// = 32 pages x (4096 x 32) = 64 macros of 4096 x 16 (low/high half per page).
//
// Two ports
//   * CPU side  : E203 sysmem ICB slave, single outstanding, 1-cycle read
//                 latency. Sits on 0xa000_0000 (sysmem = mems o4, base
//                 0x8000_0000, region LSB 31, i.e. everything that is not
//                 ITCM 0x8000_xxxx or DTCM 0x9000_xxxx).
//   * Host side : the organiser's parameter-loading port. One 32-bit word per
//                 cycle, write only. It has priority over the CPU port; the
//                 loader is only active while the CPU waits for parameters, so
//                 contention is bounded and visible in cmd_ready.
//
// Address map used by the firmware / testbench (bytes, absolute):
//   0xa000_0000  mailbox / boot scratch          (4 KiB)
//   0xa000_1000  common parameters, 4144 words  (16576 B)
//   0xa002_0000  input,            1584 words   ( 6336 B)
//   0xa002_2000  output,           1584 words   ( 6336 B)
//   0xa002_4000  packet lease,    15432 words   (61728 B, one layer)
//   0xa007_c000  stack top 0xa008_0000           (16 KiB)
// Peak use is exactly 512 KiB; the remaining hole is unallocated.
// =============================================================================
`timescale 1ns/1ps

module kwt_soc_shared_sram #(
  parameter AW = 17,          // 2^17 words = 512 KiB
  parameter DW = 32
)(
  input  wire          clk,
  input  wire          rst_n,

  // ---- CPU side: E203 sysmem ICB slave ---------------------------------
  input  wire          cmd_valid,
  output wire          cmd_ready,
  input  wire [31:0]   cmd_addr,
  input  wire          cmd_read,
  input  wire [31:0]   cmd_wdata,
  input  wire [3:0]    cmd_wmask,

  output wire          rsp_valid,
  input  wire          rsp_ready,
  output wire          rsp_err,
  output wire [DW-1:0] rsp_rdata,

  // ---- platform loader port (organiser parameter staging) --------------
  input  wire          host_en,
  output wire          host_ready,
  input  wire [AW-1:0] host_addr,
  input  wire [DW-1:0] host_wdata
);

  localparam PW    = AW - 12;             // page index width (5 for 512 KiB)
  localparam NPAGE = (32'd1 << PW);       // 32 pages of 4096 x 32

  // ---- address decode ---------------------------------------------------
  wire [AW-1:0] widx  = cmd_addr[AW+1:2];
  wire [PW-1:0] cpage = widx[AW-1:12];
  wire [11:0]   crow  = widx[11:0];

  // ---- macro array ------------------------------------------------------
  reg  [NPAGE-1:0] mac_en;
  reg  [NPAGE-1:0] mac_we;
  reg  [11:0]      mac_row;
  reg  [15:0]      mac_wd_lo;
  reg  [15:0]      mac_wd_hi;
  wire [15:0]      rd_lo [0:NPAGE-1];
  wire [15:0]      rd_hi [0:NPAGE-1];

  genvar g;
  generate
    for (g = 0; g < NPAGE; g = g + 1) begin : bank
      kwt_sram_sp u_lo (
        .clk (clk), .en (mac_en[g]), .we (mac_we[g]),
        .addr(mac_row), .wdata(mac_wd_lo), .rdata(rd_lo[g])
      );
      kwt_sram_sp u_hi (
        .clk (clk), .en (mac_en[g]), .we (mac_we[g]),
        .addr(mac_row), .wdata(mac_wd_hi), .rdata(rd_hi[g])
      );
    end
  endgenerate

  // ---- request bookkeeping ---------------------------------------------
  reg [PW-1:0] p_q;
  reg [11:0]   r_q;
  reg [DW-1:0] wd_q;
  reg [3:0]    wm_q;

  reg rpend;      // read data lands this cycle
  reg wpend;      // write response pending
  reg rmw;        // read-modify-write second half of a sub-word store

  wire accept    = cmd_valid && cmd_ready;
  wire rsp_take  = rsp_valid && rsp_ready;
  wire full_word = (cmd_wmask == 4'hF);
  assign host_ready = rst_n && !rmw;

  assign cmd_ready = rst_n && !host_en && !rmw && (!rsp_valid || rsp_ready);
  assign rsp_valid = rpend || wpend;
  assign rsp_err   = 1'b0;
  assign rsp_rdata = {rd_hi[p_q], rd_lo[p_q]};

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      p_q <= {PW{1'b0}};
      r_q <= 12'd0;
      wd_q <= {DW{1'b0}};
      wm_q <= 4'h0;
      rpend <= 1'b0;
      wpend <= 1'b0;
      rmw   <= 1'b0;
    end else begin
      if (rsp_take) begin
        rpend <= 1'b0;
        wpend <= 1'b0;
      end
      if (accept) begin
        p_q  <= cpage;
        r_q  <= crow;
        wd_q <= cmd_wdata;
        wm_q <= cmd_wmask;
        if (cmd_read) begin
          rpend <= 1'b1;
        end else if (full_word) begin
          wpend <= 1'b1;
        end else begin
          rmw <= 1'b1;              // needs the old half-words first
        end
      end
      if (rmw) begin
        rmw   <= 1'b0;
        wpend <= 1'b1;
      end
    end
  end

  // ---- macro port mux ---------------------------------------------------
  wire [DW-1:0] mask32 = {{8{wm_q[3]}}, {8{wm_q[2]}}, {8{wm_q[1]}}, {8{wm_q[0]}}};
  wire [DW-1:0] rmw_data = (wd_q & mask32) | ({rd_hi[p_q], rd_lo[p_q]} & ~mask32);

  reg [PW-1:0] apage;
  reg [11:0]   arow;
  reg          aen;
  reg          awe;
  reg [15:0]   awd_lo;
  reg [15:0]   awd_hi;
  integer      i;

  always @* begin
    apage  = cpage;
    arow   = crow;
    aen    = 1'b0;
    awe    = 1'b0;
    awd_lo = cmd_wdata[15:0];
    awd_hi = cmd_wdata[31:16];

    if (rmw) begin
      apage  = p_q;
      arow   = r_q;
      aen    = 1'b1;
      awe    = 1'b1;
      awd_lo = rmw_data[15:0];
      awd_hi = rmw_data[31:16];
    end else if (host_en && host_ready) begin
      apage  = host_addr[AW-1:12];
      arow   = host_addr[11:0];
      aen    = 1'b1;
      awe    = 1'b1;
      awd_lo = host_wdata[15:0];
      awd_hi = host_wdata[31:16];
    end else if (accept) begin
      apage  = cpage;
      arow   = crow;
      aen    = 1'b1;
      // Partial writes must first READ the old word, then commit RMW.
      awe    = !cmd_read && full_word;
    end

    for (i = 0; i < NPAGE; i = i + 1) begin
      mac_en[i] = rst_n && aen && (apage == i);
      mac_we[i] = rst_n && aen && (apage == i) && awe;
    end
    mac_row = arow;
    mac_wd_lo = awd_lo;
    mac_wd_hi = awd_hi;
  end

endmodule
