// ===========================================================================
// tb_gate_tasks.sv -- gate-level single-task driver for kwt1_mmio
// ---------------------------------------------------------------------------
// Replays exactly the MMIO sequence of rtl/v2/driver/kwt1.c:
//
//   abort(0 <- 2)
//   common packet : frame = 256 (bit8 = common flag), 4144 words via reg 16
//   layer 0       : frame = 0,                        15432 words via reg 16
//   1584 input words via reg 20, last flag (reg 12 <- 1) on the final word
//   start (0 <- 1)
//   layer 1..11   : wait need_parameters (status bit6), verify layer field,
//                   then frame = L and 15432 words
//   1584 output reads via reg 24 (read-consume acks the last one)
//   wait done (status bit1), read cycles (reg 32/36)
//
// One run yields all three signoff numbers:
//   * functional  : compare output against expected_000.hex
//   * throughput  : cycles -> 1 / (cycles * 6.666667 ns)
//   * power       : SAIF, when compiled with +define+KWT_SAIF
//
// Fixtures live in deliverables/local_port_20261103/fixtures/, cases 000..011.
// The case is selected at run time:
//     ./simv                  -> case 0  (identical to the original behaviour)
//     ./simv +CASE=7          -> input_007.hex / expected_007.hex
// One binary serves all twelve tasks; each case must still be a separate
// process so every run starts from a cold SRAM.
// ===========================================================================
`timescale 1ns/1ps

`define FIXDIR "/path/to/project/server_signoff_20261106/keyword-transformer/deliverables/local_port_20261103/fixtures"
`define HALF   3.333334

module tb_gate_tasks;

  // ---- clock / reset ------------------------------------------------------
  reg clk = 1'b0;
  always #(`HALF) clk = ~clk;

  reg rst_n = 1'b0;

  // ---- bus ----------------------------------------------------------------
  reg         req_valid = 1'b0;
  reg         req_write = 1'b0;
  reg  [31:0] req_addr  = 32'd0;
  reg  [31:0] req_wdata = 32'd0;
  reg  [3:0]  req_wstrb = 4'hf;
  reg         resp_ready = 1'b1;

  wire        req_ready;
  wire        resp_valid;
  wire [31:0] resp_rdata;
  wire        resp_error;
  wire        irq;

  kwt1_mmio dut (
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

  // ---- fixtures -----------------------------------------------------------
  localparam integer N_COMMON = 4144;
  localparam integer N_LAYER  = 15432;
  localparam integer N_IO     = 1584;
  localparam integer N_CASES  = 12;         // fixtures: cases 000..011

  reg [31:0] common [0:N_COMMON-1];
  reg [31:0] lyr    [0:12*N_LAYER-1];
  reg [31:0] inp    [0:N_IO-1];
  reg [31:0] expd   [0:N_IO-1];
  reg [31:0] outp   [0:N_IO-1];

  integer i, k, c, mism;
  integer errors = 0;
  integer case_idx;

  reg [31:0] rq;
  reg        re;
  reg [31:0] st, w;
  reg [31:0] rq2;
  reg [31:0] cyc_lo, cyc_hi;
  longint    cyc64;
  reg [8*260-1:0] fn;

  // ---- bus primitives -----------------------------------------------------
  // One transaction. req_ready may stall (frame_ready / cfg_ready /
  // input_ready / out_valid gate it), so hold req_valid until accepted.
  task automatic bus(input wr, input [31:0] a, input [31:0] d,
                     output [31:0] q, output e);
    begin
      @(negedge clk);
      req_valid = 1'b1;
      req_write = wr;
      req_addr  = a;
      req_wdata = d;
      req_wstrb = 4'hf;
      @(posedge clk);
      while (!req_ready) @(posedge clk);
      @(negedge clk);
      req_valid = 1'b0;
      req_write = 1'b0;
      q = resp_rdata;
      e = resp_error;
      @(posedge clk);          // resp_valid clears here (resp_ready is tied 1)
    end
  endtask

  task automatic wr(input [31:0] a, input [31:0] d);
    begin
      bus(1'b1, a, d, rq, re);
      if (re) begin
        errors = errors + 1;
        $display("BUS_ERR  wr addr=%0d data=%h", a, d);
      end
    end
  endtask

  task automatic rd(input [31:0] a, output [31:0] q);
    begin
      bus(1'b0, a, 32'h0, q, re);
      if (re) begin
        errors = errors + 1;
        $display("BUS_ERR  rd addr=%0d", a);
      end
    end
  endtask

  // Dump the two diagnostic registers.  reg 4 = status, reg 28 = {dbg_state, err_code}
  task automatic dump(input [8*32-1:0] tag);
    begin
      rd(32'd4, rq);
      rd(32'd28, rq2);
      $display("STATUS[%0s] t=%0t st=%h busy=%b done=%b err=%b cv=%b lv=%b np=%b aa=%b sr=%b fr=%b cr=%b ir=%b ov=%b layer=%0d | err_code=%0d dbg_state=%0d",
               tag, $time, rq,
               rq[0], rq[1], rq[2], rq[3], rq[5], rq[6], rq[7],
               rq[8], rq[9], rq[10], rq[11], rq[12],
               rq[19:16], rq2[7:0], rq2[15:8]);
    end
  endtask

  // Poll status (reg 4) until every bit in mask is set.
  task automatic poll(input [31:0] mask, input integer limit);
    integer n;
    reg ok;
    begin
      ok = 1'b0;
      n  = 0;
      while (!ok && (n < limit)) begin
        rd(32'd4, rq);
        if (rq[2]) begin
          $display("HW_ERROR code=%0d state=%0d", rq[15:8], rq[23:16]);
          errors = errors + 1;
          ok = 1'b1;
        end else if ((rq & mask) == mask) begin
          ok = 1'b1;
        end
        n = n + 1;
      end
      if (!ok) begin
        $display("TIMEOUT  mask=%h after %0d polls", mask, n);
        errors = errors + 1;
        dump("timeout");
        $display("FAIL KWT_GATE_TASK stopped at first timeout");
        $finish;
      end
    end
  endtask

  // Poll status while watching debug_state (reg 28 high byte).  Reports the
  // last healthy core state before it turns X -- that pinpoints the failing
  // transition without needing hierarchical probes into the netlist.
  task automatic poll_dbg(input [31:0] mask, input integer limit);
    integer n;
    reg ok;
    reg [7:0] last_dbg;
    begin
      ok = 1'b0;
      n  = 0;
      last_dbg = 8'hff;
      while (!ok && (n < limit)) begin
        rd(32'd4, rq);
        rd(32'd28, rq2);
        if ((^rq2[15:8]) === 1'bx) begin
          $display("X_ENTER  t=%0t last_healthy_state=%0d status=%h", $time, last_dbg, rq);
          errors = errors + 1;
          ok = 1'b1;
        end else begin
          last_dbg = rq2[15:8];
          if ((n % 8192) == 0)
            $display("  dbg=%0d t=%0t st=%h", rq2[15:8], $time, rq);
          if (rq[2]) begin
            $display("HW_ERROR code=%0d state=%0d", rq[15:8], rq[23:16]);
            errors = errors + 1;
            ok = 1'b1;
          end else if ((rq & mask) == mask) begin
            ok = 1'b1;
          end
        end
        n = n + 1;
      end
      if (!ok) begin
        $display("TIMEOUT  mask=%h after %0d polls", mask, n);
        errors = errors + 1;
        dump("timeout");
        $display("FAIL KWT_GATE_TASK stopped at first timeout");
        $finish;
      end
    end
  endtask

  // Send one packet: frame word, then N data words through reg 16.
  task automatic packet(input [31:0] frame, input integer base, input integer nwords);
    integer j;
    begin
      poll(32'h0000_0200, 20000);            // bit9  frame_ready
      wr(32'd8, frame);
      for (j = 0; j < nwords; j = j + 1) begin
        poll(32'h0000_0400, 20000);          // bit10 cfg_ready
        if (j == nwords-1) wr(32'd12, 32'd1);  // last word of this packet
        if (base < 0) wr(32'd16, common[j]);
        else          wr(32'd16, lyr[base + j]);
        if ((j % 2048) == 0)
          $display("  packet frame=%0d word %0d/%0d t=%0t", frame, j, nwords, $time);
      end
      dump("packet-end");
    end
  endtask

  // ---- stimulus -----------------------------------------------------------
  initial begin
    // Case selection: no plusarg means case 0, i.e. the file names are the
    // literal input_000.hex / expected_000.hex -- byte-identical to the
    // single-case build that produced the historical results.
    if (!$value$plusargs("CASE=%d", case_idx)) case_idx = 0;
    if (case_idx < 0 || case_idx >= N_CASES) begin
      $display("BAD_CASE %0d (valid 0..%0d)", case_idx, N_CASES-1);
      $finish;
    end
    $display("KWT_GATE_TASK start  case=%0d clk half=%0.6f ns", case_idx, `HALF);

    $readmemh({`FIXDIR, "/common.bin.hex"},    common);
    fn = $sformatf("%s/input_%03d.hex",    `FIXDIR, case_idx);
    $readmemh(fn, inp);
    fn = $sformatf("%s/expected_%03d.hex", `FIXDIR, case_idx);
    $readmemh(fn, expd);
    for (i = 0; i < 12; i = i + 1) begin
      fn = $sformatf("%s/layer_%02d.bin.hex", `FIXDIR, i);
      $readmemh(fn, lyr, i*N_LAYER, i*N_LAYER + N_LAYER - 1);
    end

    rst_n = 1'b0;
    repeat (20) @(posedge clk);
    rst_n = 1'b1;
    repeat (10) @(posedge clk);

    // identity check: proves the bus path and the build are sane
    rd(32'd72, w);
    if (w !== 32'h4b57_5431) begin
      $display("BAD_MAGIC %h (expected 4b575431)", w);
      errors = errors + 1;
    end else begin
      $display("MAGIC_OK 4b575431");
    end

`ifdef KWT_SAIF
    $set_toggle_region(dut);
    $toggle_start;
`endif

    // ---- abort, then common packet (frame = 256, common flag in bit8) ----
    wr(32'd0, 32'd2);
    repeat (8) @(posedge clk);

    packet(32'd256, -1, N_COMMON);
    poll(32'h0000_0008, 200000);             // bit3 common_valid

    // ---- layer 0 --------------------------------------------------------
    packet(32'd0, 0, N_LAYER);
    poll(32'h0000_0020, 200000);             // bit5 layer_valid

    // ---- 1584 input words ----------------------------------------------
    for (k = 0; k < N_IO; k = k + 1) begin
      poll(32'h0000_0800, 20000);            // bit11 input_ready
      if (k == N_IO-1) wr(32'd12, 32'd1);
      wr(32'd20, inp[k]);
    end

    // ---- start ----------------------------------------------------------
    poll(32'h0000_0100, 200000);             // bit8 start_ready
    wr(32'd0, 32'd1);
    dump("after-start");

    // ---- layers 1..11 ---------------------------------------------------
    // Each iteration waits for the accelerator to ASK for layer c, then sends
    // that layer's coefficients.  c == 11 is the LAST layer: after its packet
    // is loaded the accel finishes RUN and jumps straight to OUTPUT_READ
    // (kwt1_accel.sv:102, `current_layer==11`), so it never enters WAIT_LAYER
    // again and need_parameters never rises.  Do NOT poll bit6 after this.
    for (c = 1; c < 12; c = c + 1) begin
      poll_dbg(32'h0000_0040, 400000);       // bit6 need_parameters
      rd(32'd4, st);
      if (((st >> 16) & 15) != c) begin
        $display("LAYER_MISMATCH exp=%0d got=%0d", c, (st >> 16) & 15);
        errors = errors + 1;
      end
      packet(c, c*N_LAYER, N_LAYER);
      poll(32'h0000_0020, 400000);           // bit5 layer_valid
      $display("LAYER_LOADED %0d t=%0t", c, $time);
    end
    $display("ALL_LAYERS_LOADED t=%0t (no further need_parameters)", $time);

    // ---- drain 1584 output words ---------------------------------------
    for (k = 0; k < N_IO; k = k + 1) begin
      poll(32'h0000_1000, 400000);           // bit12 out_valid
      rd(32'd24, w);
      outp[k] = w;
      if ((k % 256) == 0) $display("  drain %0d/%0d t=%0t", k, N_IO, $time);
    end

    poll(32'h0000_0002, 400000);             // bit1 done
    dump("after-done");

`ifdef KWT_SAIF
    $toggle_stop;
    // case suffix is mandatory: twelve gate runs share one out/gate_sim dir
    fn = $sformatf("/path/to/project/out/gate_sim/kwt1_gate_c%0d.saif", case_idx);
    $toggle_report(fn, 1.0e-9, "tb_gate_tasks.dut");
    $display("KWT_SAIF_WRITTEN %0s", fn);
`endif

    // ---- results --------------------------------------------------------
    rd(32'd32, cyc_lo);
    rd(32'd36, cyc_hi);

    mism = 0;
    for (k = 0; k < N_IO; k = k + 1)
      if (outp[k] !== expd[k]) mism = mism + 1;

    $display("KWT_OUTPUT mismatches=%0d of %0d  (case %0d)", mism, N_IO, case_idx);
    cyc64 = cyc_hi * 4294967296 + cyc_lo;
    $display("KWT_CYCLES %0d (hi=%0d lo=%0d)", cyc64, cyc_hi, cyc_lo);
    $display("KWT_NS %0d", cyc64 * 6666667 / 1000);

    if ((errors == 0) && (mism == 0))
      $display("PASS KWT_GATE_TASK case=%0d cycles=%0d", case_idx, cyc64);
    else
      $display("FAIL KWT_GATE_TASK case=%0d errors=%0d mismatches=%0d", case_idx, errors, mism);

    repeat (10) @(posedge clk);
    $finish;
  end

  // watchdog.  Measured on RTL 2026-11-09: layer 11's packet finishes at
  // t = 38.0 ms and the accel is still computing, so the whole task plus the
  // 1584-word drain is well past the old 60 ms limit.  300 ms is generous.
  initial begin
    #(300_000_000);
    $display("FAIL KWT_GATE_TASK watchdog timeout");
    $finish;
  end

endmodule
