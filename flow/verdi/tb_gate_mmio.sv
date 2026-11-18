// =============================================================================
// Port-only gate-level smoke testbench for the DC-mapped kwt1_mmio netlist.
// -----------------------------------------------------------------------------
// WHY THIS EXISTS:
//   rtl/integration/tb_mmio.sv defines a BEHAVIORAL kwt1_accel stub and pokes
//   dut.accel.value / cfg_allow / cfg_taken / acks. rtl/v2/tb_accel.sv pokes
//   dut.core.* and dut.banks.bank[8].ram.mem[]. After compile_ultra those
//   registers/nets no longer exist under those names, so neither TB can be
//   reused on a mapped netlist. This TB touches TOP-LEVEL PORTS ONLY.
//
// SCOPE: bus protocol / reset / abort smoke + waveform generation.
//   It does NOT run the 12-layer task, does NOT prove encoder equivalence,
//   does NOT produce throughput, power or area. Full regression is S7.
//
// Compile-time switches (pick one dumper):
//   +define+FSDB   $fsdbDumpfile (needs Verdi PLI, see SERVER_VERDI_GATE_SIM)
//   +define+VCD    $dumpfile / $dumpvars (any simulator, then vcd2fsdb)
//   +define+SDF    $sdf_annotate, pass +sdf=<path>
//   +define+CLK_HALF=<ns>   default 3.333334 (150 MHz, 6.666667 ns period)
//   +define+SAMPLE_DLY=<ns> default 1.0; increase if SDF clk->q arcs are longer
// =============================================================================
`timescale 1ns/1ps
`ifndef CLK_HALF
`define CLK_HALF 3.333334
`endif
// Sample offset after posedge. 1 ns works for zero-delay functional sim and
// for most SDF-annotated cell arcs; override (+define+SAMPLE_DLY=2.0) if the
// authorized library has longer clk->q paths.
`ifndef SAMPLE_DLY
`define SAMPLE_DLY 1.0
`endif

module tb_gate_mmio;
  reg clk = 1'b0;
  always #(`CLK_HALF) clk = ~clk;

  reg        rst_n      = 1'b0;
  reg        abort_hw   = 1'b0;
  reg        core_enable= 1'b1;
  reg        mem_enable = 1'b1;
  reg        req_valid  = 1'b0;
  reg        req_write  = 1'b0;
  reg [31:0] req_addr   = 32'd0;
  reg [31:0] req_wdata  = 32'd0;
  reg [3:0]  req_wstrb  = 4'hf;
  reg        resp_ready = 1'b1;

  wire        req_ready;
  wire        resp_valid;
  wire        resp_error;
  wire        irq;
  wire [31:0] resp_rdata;

  // Named connections: DC keeps top-level port names but may reorder them.
  kwt1_mmio dut (
    .clk        (clk),
    .rst_n      (rst_n),
    .abort_hw   (abort_hw),
    .core_enable(core_enable),
    .mem_enable (mem_enable),
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

  // ---------------- waveform dumps ----------------
`ifdef FSDB
  initial begin
    $fsdbDumpfile("gate.fsdb");
    $fsdbDumpvars(0, tb_gate_mmio);
  end
`endif
`ifdef VCD
  initial begin
    $dumpfile("gate.vcd");
    $dumpvars(0, tb_gate_mmio);
  end
`endif
`ifdef SDF
  reg [1023:0] sdf_path;
  initial begin
    if (!$value$plusargs("sdf=%s", sdf_path)) sdf_path = "mapped.sdf";
    $display("KWT_SDF_ANNOTATE %0s", sdf_path);
    $sdf_annotate(sdf_path, dut);
  end
`endif

  // ---------------- response monitor ----------------
  // A response is captured at posedge + SAMPLE_DLY. Capturing in a monitor
  // (instead of polling resp_valid inside the task) is essential: after a
  // software-abort write, req_ready drops for one cycle while the response is
  // already being retired, so a "wait for req_ready then read resp_*" sequence
  // silently loses that response.
  reg [31:0] cap_rdata  = 32'd0;
  reg        cap_error  = 1'b0;
  integer    resp_count = 0;
  always @(posedge clk) #(`SAMPLE_DLY) begin
    if (rst_n === 1'b1 && resp_valid === 1'b1 && resp_ready === 1'b1) begin
      cap_rdata  = resp_rdata;
      cap_error  = resp_error;
      resp_count = resp_count + 1;
    end
  end

  // ---------------- one MMIO exchange ----------------
  // req_valid is asserted for exactly ONE clock, after req_ready is known high.
  task automatic exchange(input wr, input [31:0] a, input [31:0] d,
                          output [31:0] rd, output er);
    integer n0;
    begin
      n0 = resp_count;
      @(negedge clk);
      while (req_ready !== 1'b1) begin @(negedge clk); end
      req_valid = 1'b1; req_write = wr; req_addr = a;
      req_wdata = d;    req_wstrb = 4'hf;
      @(posedge clk); #(`SAMPLE_DLY);
      @(negedge clk);
      req_valid = 1'b0;
      while (resp_count == n0) begin @(posedge clk); #(`SAMPLE_DLY); end
      rd = cap_rdata;
      er = cap_error;
      @(negedge clk);
    end
  endtask

  reg [31:0] rd;
  reg        er;
  integer    txn = 0;

  initial begin
    $display("KWT_GATE_SIM start clk_half=%0.6f ns", `CLK_HALF);
    repeat (4) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);

    // ID register -----------------------------------------------------------
    exchange(1'b0, 32'd72, 32'd0, rd, er); txn = txn + 1;
    if (er !== 1'b0 || rd !== 32'h4b575431)
      $fatal(1, "KWT_GATE ID mismatch rd=%h err=%b", rd, er);

    // Status register: must be a legal read ----------------------------------
    exchange(1'b0, 32'd4, 32'd0, rd, er); txn = txn + 1;
    if (er !== 1'b0) $fatal(1, "KWT_GATE status read flagged error");

    // Two illegal reads must raise resp_error --------------------------------
    exchange(1'b0, 32'd256, 32'd0, rd, er); txn = txn + 1;
    if (er !== 1'b1) $fatal(1, "KWT_GATE bad address did not raise error");
    exchange(1'b0, 32'd6, 32'd0, rd, er); txn = txn + 1;
    if (er !== 1'b1) $fatal(1, "KWT_GATE unaligned read did not raise error");

    // Legal / illegal control writes (NO task start) ------------------------
    exchange(1'b1, 32'd12, 32'd0, rd, er); txn = txn + 1;
    if (er !== 1'b0) $fatal(1, "KWT_GATE last_flag write flagged error");
    exchange(1'b1, 32'd12, 32'd3, rd, er); txn = txn + 1;
    if (er !== 1'b1) $fatal(1, "KWT_GATE bad last_flag value accepted");

    // A few idle transactions so the waveform has something to show ---------
    repeat (3) begin
      exchange(1'b0, 32'd72, 32'd0, rd, er); txn = txn + 1;
      if (rd !== 32'h4b575431) $fatal(1, "KWT_GATE ID unstable");
    end

    // Hard abort: no request accepted, no ghost response --------------------
    @(negedge clk);
    abort_hw = 1'b1; req_valid = 1'b1; req_write = 1'b0; req_addr = 32'd72;
    @(posedge clk); #(`SAMPLE_DLY);
    if (req_ready !== 1'b0) $fatal(1, "KWT_GATE request accepted during hard abort");
    @(negedge clk);
    abort_hw = 1'b0; req_valid = 1'b0;
    repeat (4) @(negedge clk);
    if (resp_valid === 1'b1 || irq === 1'b1)
      $fatal(1, "KWT_GATE hard-abort ghost response");

    // Software abort on MMIO addr 0 -----------------------------------------
    exchange(1'b1, 32'd0, 32'd2, rd, er); txn = txn + 1;
    if (er !== 1'b0) $fatal(1, "KWT_GATE software abort flagged error");

    // Cold reset: no ghost response ------------------------------------------
    @(negedge clk); rst_n = 1'b0;
    repeat (3) @(negedge clk);
    rst_n = 1'b1;
    repeat (4) @(negedge clk);
    if (resp_valid === 1'b1 || irq === 1'b1)
      $fatal(1, "KWT_GATE reset ghost response");

    exchange(1'b0, 32'd72, 32'd0, rd, er); txn = txn + 1;
    if (er !== 1'b0 || rd !== 32'h4b575431)
      $fatal(1, "KWT_GATE ID after reset mismatch");

    repeat (5) @(negedge clk);
    $display("PASS KWT_GATE_SIM txn=%0d (port-only gate-level smoke)", txn);
    $finish;
  end

  initial begin
    #500000;
    $fatal(1, "KWT_GATE watchdog timeout txn=%0d", txn);
  end
endmodule
