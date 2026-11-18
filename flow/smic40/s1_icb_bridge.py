# -*- coding: utf-8 -*-
import io, os, sys, stat

ROOT = os.environ.get("KWT1_CHIP", "/path/to/project/kwt1_chip")
if not os.path.isdir(ROOT):
    print("MISS_ROOT", ROOT)
    sys.exit(1)

NEED_RTL = ["mul_pipe.sv", "rne_pipe.sv", "kwt_sram_sp.sv", "kwt_mac8x8.sv",
            "kwt_iterative.sv", "kwt_math.sv", "kwt_packet_loader.sv",
            "kwt_layer_banked.sv", "kwt1_accel.sv", "kwt1_mmio.sv"]
accel = os.path.join(ROOT, "rtl", "accel")
have = set(os.listdir(accel)) if os.path.isdir(accel) else set()
miss = [n for n in NEED_RTL if n not in have]
if miss:
    print("MISS_RTL", " ".join(miss))
    sys.exit(1)

for rel in ("rtl/soc", "tb", "sim/icb"):
    d = os.path.join(ROOT, rel)
    if not os.path.isdir(d):
        os.makedirs(d)
        print("MKDIR", rel)

ICB2KWT = '''// =============================================================================
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
'''

TB = '''// =============================================================================
// tb_icb_bridge -- stand-alone testbench for icb2kwt + kwt1_mmio
// -----------------------------------------------------------------------------
// S1 of the SoC integration plan: prove the ICB bridge BEFORE any CPU, any
// firmware, any linker script is involved.  If this TB passes, every remaining
// integration bug is above the bus (soc_top wiring, firmware, boot flow).
//
// What is checked (all hard assertions):
//   T1  read  ACCEL+0x48  -> 0x4B575431        (decode + read path + ID)
//   T2  read  0x5000_0000 -> rsp_err=1, data=0 (unmapped window is rejected,
//                                               and is NOT mistaken for START)
//   T3  read  ACCEL+0x04  -> rsp_err=0         (STATUS is readable; bits are
//                                               printed, not asserted, because
//                                               the reset value of the status
//                                               word is not part of the frozen
//                                               contract)
//   T4  write ACCEL+0x0C  -> rsp_err=0         (legal full-word write)
//   T5  write ACCEL+0x08 with wmask=4'b0001
//                         -> rsp_err=1         (partial word must be rejected,
//                                               INTERFACE_CONTRACT.md "只支持
//                                               完整字写入")
//   T6  read  ACCEL+0x02  -> rsp_err=1         (unaligned address rejected)
//
// Clock: 150 MHz (6.667 ns), the sign-off frequency.
// SRAM : behavioural model (kwt_sram_sp) because KWT_TECH_SRAM is NOT defined.
//        KWT_SIM must come from the command line (+define+KWT_SIM), NOT from a
//        `define here: VCS compiles the file list in order, so a macro defined
//        in this file would be too late for kwt_sram_sp.sv, and redefining it
//        would only add a warning.
// =============================================================================
`timescale 1ns/1ps

module tb_icb_bridge;

  // ------------------------------------------------------------- clock/reset
  reg clk   = 1'b0;
  reg rst_n = 1'b0;
  always #3.333 clk = ~clk;                 // 150.0 MHz

  localparam [31:0] ACCEL_BASE = 32'h4000_0000;

  integer errors = 0;

  // ------------------------------------------------------ ICB master model
  reg         m_cmd_valid;
  wire        m_cmd_ready;
  reg  [31:0] m_cmd_addr;
  reg         m_cmd_read;
  reg  [31:0] m_cmd_wdata;
  reg  [3:0]  m_cmd_wmask;
  wire        m_rsp_valid;
  reg         m_rsp_ready;
  wire        m_rsp_err;
  wire [31:0] m_rsp_rdata;

  // -------------------------------------------------- bridge <-> accel bus
  wire        req_valid, req_ready, req_write;
  wire [31:0] req_addr, req_wdata;
  wire [3:0]  req_wstrb;
  wire        resp_valid, resp_ready, resp_error;
  wire [31:0] resp_rdata;
  wire        dec_hit;
  wire        irq;

  // ------------------------------------------------------------------ bridge
  icb2kwt #(.BASE_HI(16'h4000)) u_bridge (
    .clk           (clk),
    .rst_n         (rst_n),
    .icb_cmd_valid (m_cmd_valid),
    .icb_cmd_ready (m_cmd_ready),
    .icb_cmd_addr  (m_cmd_addr),
    .icb_cmd_read  (m_cmd_read),
    .icb_cmd_wdata (m_cmd_wdata),
    .icb_cmd_wmask (m_cmd_wmask),
    .icb_rsp_valid (m_rsp_valid),
    .icb_rsp_ready (m_rsp_ready),
    .icb_rsp_err   (m_rsp_err),
    .icb_rsp_rdata (m_rsp_rdata),
    .req_valid     (req_valid),
    .req_ready     (req_ready),
    .req_write     (req_write),
    .req_addr      (req_addr),
    .req_wdata     (req_wdata),
    .req_wstrb     (req_wstrb),
    .resp_valid    (resp_valid),
    .resp_ready    (resp_ready),
    .resp_rdata    (resp_rdata),
    .resp_error    (resp_error),
    .dec_hit       (dec_hit)
  );

  // -------------------------------------------------------------- accelerator
  kwt1_mmio u_dut (
    .clk        (clk),
    .rst_n      (rst_n),
    .abort_hw   (1'b0),
    .core_enable(1'b1),
    .mem_enable (1'b1),
    .req_valid  (req_valid),
    .req_ready  (req_ready),
    .req_write  (req_write),
    .req_addr   (req_addr),
    .req_wdata  (req_wdata),
    .req_wstrb  (req_wstrb),
    .resp_valid (resp_valid),
    .resp_ready (resp_ready),
    .resp_rdata (resp_rdata),
    .resp_error (resp_error),
    .irq        (irq)
  );

  // ---------------------------------------------------------------- ICB xfer
  // Drive on negedge, sample on posedge: no race with the DUT's flops.
  task automatic icb_xfer(
    input  [31:0] addr,
    input         rd,
    input  [31:0] wdata,
    input  [3:0]  wmask,
    output [31:0] rdata,
    output        err
  );
    begin
      @(negedge clk);
      m_cmd_valid = 1'b1;
      m_cmd_addr  = addr;
      m_cmd_read  = rd;
      m_cmd_wdata = wdata;
      m_cmd_wmask = wmask;
      @(posedge clk);
      while (!m_cmd_ready) @(posedge clk);
      @(negedge clk);
      m_cmd_valid = 1'b0;
      m_cmd_addr  = 32'h0;
      m_cmd_read  = 1'b0;
      m_cmd_wdata = 32'h0;
      m_cmd_wmask = 4'h0;

      m_rsp_ready = 1'b1;
      @(posedge clk);
      while (!m_rsp_valid) @(posedge clk);
      rdata = m_rsp_rdata;
      err   = m_rsp_err;
      @(negedge clk);
      m_rsp_ready = 1'b0;
      @(posedge clk);
    end
  endtask

  // ---------------------------------------------------------------- checking
  reg [31:0] d;
  reg        e;

  task automatic expect_read(input [31:0] addr, input [31:0] want, input integer tag);
    begin
      icb_xfer(addr, 1'b1, 32'h0, 4'hf, d, e);
      if (e !== 1'b0) begin
        errors = errors + 1;
        $display("FAIL T%0d  addr=%08x  unexpected rsp_err=1", tag, addr);
      end else if (d !== want) begin
        errors = errors + 1;
        $display("FAIL T%0d  addr=%08x  got %08x want %08x", tag, addr, d, want);
      end else begin
        $display("PASS T%0d  addr=%08x  rdata=%08x", tag, addr, d);
      end
    end
  endtask

  task automatic expect_read_err(input [31:0] addr, input integer tag);
    begin
      icb_xfer(addr, 1'b1, 32'h0, 4'hf, d, e);
      if (e !== 1'b1) begin
        errors = errors + 1;
        $display("FAIL T%0d  addr=%08x  expected rsp_err=1, got 0 (rdata=%08x)",
                 tag, addr, d);
      end else begin
        $display("PASS T%0d  addr=%08x  rsp_err=1 rdata=%08x", tag, addr, d);
      end
    end
  endtask

  task automatic expect_write(input [31:0] addr, input [31:0] wdata,
                              input [3:0] wmask, input want_err, input integer tag);
    begin
      icb_xfer(addr, 1'b0, wdata, wmask, d, e);
      if (e !== want_err) begin
        errors = errors + 1;
        $display("FAIL T%0d  addr=%08x wmask=%b  expected rsp_err=%b, got %b",
                 tag, addr, wmask, want_err, e);
      end else begin
        $display("PASS T%0d  addr=%08x wmask=%b  rsp_err=%b", tag, addr, wmask, e);
      end
    end
  endtask

  // -------------------------------------------------------------------- main
  initial begin
    m_cmd_valid = 1'b0;
    m_cmd_addr  = 32'h0;
    m_cmd_read  = 1'b0;
    m_cmd_wdata = 32'h0;
    m_cmd_wmask = 4'h0;
    m_rsp_ready = 1'b0;

    $display("=== tb_icb_bridge: icb2kwt + kwt1_mmio ===");
    $display("BASE_HI=0x4000  ACCEL_BASE=0x%08x  clk=150MHz", ACCEL_BASE);

    repeat (8) @(posedge clk);
    rst_n = 1'b1;
    repeat (8) @(posedge clk);

    // T1: ID register -- proves decode, read path, response path
    expect_read(ACCEL_BASE + 32'h48, 32'h4B57_5431, 1);

    // T2: an address outside the window must be rejected, not executed
    expect_read_err(32'h5000_0000, 2);

    // T3: STATUS readable (value printed, not asserted)
    icb_xfer(ACCEL_BASE + 32'h04, 1'b1, 32'h0, 4'hf, d, e);
    if (e !== 1'b0) begin
      errors = errors + 1;
      $display("FAIL T3  STATUS read got rsp_err=1");
    end else begin
      $display("PASS T3  STATUS=%08x  busy=%b done=%b err=%b common=%b input=%b layer=%b need=%b await=%b start_rdy=%b frame_rdy=%b cfg_rdy=%b in_rdy=%b out_vld=%b layer=%0d",
               d, d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7],
               d[8], d[9], d[10], d[11], d[12], d[19:16]);
    end

    // T4: legal full-word write (LAST flag clear) must be accepted
    expect_write(ACCEL_BASE + 32'h0C, 32'h0000_0000, 4'hF, 1'b0, 4);

    // T5: partial word write must be rejected by the accelerator contract
    expect_write(ACCEL_BASE + 32'h08, 32'h0000_0000, 4'b0001, 1'b1, 5);

    // T6: unaligned address must be rejected
    expect_read_err(ACCEL_BASE + 32'h02, 6);

    // T7: after all of the above the bridge must be idle again -- this catches
    //     a leaked err_rsp_valid (which would swallow the next real response)
    expect_read(ACCEL_BASE + 32'h48, 32'h4B57_5431, 7);

    repeat (4) @(posedge clk);

    if (errors == 0) $display("TEST PASS  tb_icb_bridge");
    else             $display("TEST FAIL  tb_icb_bridge  errors=%0d", errors);

    $finish;
  end

  // global watchdog: the BRIDGE must never hang
  initial begin
    #200000;
    $display("TEST FAIL  tb_icb_bridge  TIMEOUT (no $finish within 200 us)");
    $finish;
  end

endmodule
'''

FLIST = '''+incdir+../../rtl/accel/generated
../../rtl/accel/mul_pipe.sv
../../rtl/accel/rne_pipe.sv
../../rtl/accel/kwt_sram_sp.sv
../../rtl/accel/kwt_mac8x8.sv
../../rtl/accel/kwt_iterative.sv
../../rtl/accel/kwt_math.sv
../../rtl/accel/kwt_packet_loader.sv
../../rtl/accel/kwt_layer_banked.sv
../../rtl/accel/kwt1_accel.sv
../../rtl/accel/kwt1_mmio.sv
../../rtl/soc/icb2kwt.sv
../../tb/tb_icb_bridge.sv
'''

RUN = '''#!/bin/bash
# S1: stand-alone ICB bridge test. No CPU, no firmware, no linker script.
# 150 MHz, behavioural SRAM (KWT_TECH_SRAM undefined), ~10 us of simulation.
set -e
cd "$(dirname "$0")"
vcs -full64 -sverilog +v2k -timescale=1ns/1ps -error+50 +define+KWT_SIM -f filelist.f -o simv_icb -l compile_icb.log
./simv_icb | tee run_icb.log
'''

total = 0

def put(rel, text, exec_bit=False):
    global total
    p = os.path.join(ROOT, rel)
    io.open(p, "w", newline="\n").write(text)
    n = len(text.encode("utf-8"))
    total += n
    if exec_bit:
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print("WROTE %-26s %6d B" % (rel, n))

put("rtl/soc/icb2kwt.sv",  ICB2KWT)
put("tb/tb_icb_bridge.sv", TB)
put("sim/icb/filelist.f",  FLIST)
put("sim/icb/run_icb.sh",  RUN, exec_bit=True)

print("DONE files=4 bytes=%d" % total)
