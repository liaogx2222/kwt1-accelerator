// =============================================================================
// tb_soc.sv -- SoC-level functional regression: real 12-case network on the CPU
//
// Platform model
//   Per the competition spec the parameters are not "preloaded somewhere off
//   chip": the organiser's environment writes them through an existing port
//   into the 512 KiB system shared SRAM, and the E203 core does the scheduling
//   and the data movement. This testbench is that environment.
//
//   Shared SRAM (word offsets in the host port address space):
//     0x00000  mailbox   [0]=host sequence, [1]=CPU ack
//     0x00400  common      4144 words  ( 16 576 B)
//     0x08000  input       1584 words  (  6 336 B)
//     0x09000  layer lease 15432 words ( 61 728 B, one layer at a time)
//
//   Full weight set is 757 312 B > 512 KiB, so the spec's layered parameter
//   loading is used: the host fills common+input+layer0, sets seq=1, then for
//   every ack it drops the next layer into the same lease and bumps seq.
//
// Firmware (bootrom.hex, built by flow/smic40/mk_bootrom.py)
//     abort -> wait seq=1 -> common packet -> layer 0 -> ack 1
//           -> 1584 input words -> start
//           -> 11 x (wait need_parameters -> wait seq=k+1 -> layer k -> ack)
//           -> drain 1584 outputs into DTCM[0..1583] -> marker 0x5A5 @DTCM[1584]
//
// Pass criteria
//   P1  accelerator ID read over sysper == 0x4B575431
//   P2  no sysper rsp_err during the whole run
//   P3  DTCM[1584] == 0x0000_05A5
//   P4  DTCM[0..1583] == expected_<case>.hex  (bit exact, 1584/1584)
//
// Run from sim/soc (bootrom.hex must be in the working directory):
//   ./simv_soc            -> case 0
//   ./simv_soc +CASE=7    -> case 7
// =============================================================================
`timescale 1ns/1ps

`define FIXDIR "/path/to/project/server_signoff_20261106/keyword-transformer/deliverables/local_port_20261103/fixtures"

module tb_soc;

  localparam integer N_COMMON = 4144;
  localparam integer N_LAYER  = 15432;
  localparam integer N_IO     = 1584;
  localparam integer N_CASES  = 12;

  localparam integer MAILBOX_W = 0;                       // 0xa000_0000
  localparam integer COMMON_W  = 32'h0000_1000 >> 2;      // 0x00400
  localparam integer INPUT_W   = 32'h0002_0000 >> 2;      // 0x08000
  localparam integer LEASE_W   = 32'h0002_4000 >> 2;      // 0x09000

  localparam [31:0] KWT_ID     = 32'h4B575431;
  localparam [31:0] KWT_MARKER = 32'h0000_05A5;

  // ---------------------------------------------------------------- clocks --
  reg hfextclk = 1'b0;
  always #5 hfextclk = ~hfextclk;               // 100 MHz core clock

  reg lfextclk = 1'b0;
  always #33 lfextclk = ~lfextclk;              // 15 MHz, only to spin the PMU

  // ------------------------------------------------------------ pad inputs --
  reg         erst_n    = 1'b0;
  reg         bootrom_n = 1'b0;
  reg  [31:0] gpioa     = 32'h0;
  reg  [31:0] gpiob     = 32'h0;

  wire        accel_irq;
  wire        hfxoscen, lfxoscen;
  wire [31:0] gpioa_o, gpioa_oe, gpiob_o, gpiob_oe;

  // ------------------------------------------- platform parameter loader ---
  reg         host_en    = 1'b0;
  reg  [16:0] host_addr  = 17'h0;
  reg  [31:0] host_wdata = 32'h0;

  soc_top dut (
    .hfextclk                    (hfextclk),
    .hfxoscen                    (hfxoscen),
    .lfextclk                    (lfextclk),
    .lfxoscen                    (lfxoscen),

    .io_pads_jtag_TCK_i_ival     (1'b0),
    .io_pads_jtag_TMS_i_ival     (1'b0),
    .io_pads_jtag_TDI_i_ival     (1'b0),
    .io_pads_jtag_TDO_o_oval     (),
    .io_pads_jtag_TDO_o_oe       (),

    .io_pads_gpioA_i_ival        (gpioa),
    .io_pads_gpioA_o_oval        (gpioa_o),
    .io_pads_gpioA_o_oe          (gpioa_oe),
    .io_pads_gpioB_i_ival        (gpiob),
    .io_pads_gpioB_o_oval        (gpiob_o),
    .io_pads_gpioB_o_oe          (gpiob_oe),

    .io_pads_qspi0_sck_o_oval    (),
    .io_pads_qspi0_cs_0_o_oval   (),
    .io_pads_qspi0_dq_0_i_ival   (1'b0),
    .io_pads_qspi0_dq_0_o_oval   (),
    .io_pads_qspi0_dq_0_o_oe     (),
    .io_pads_qspi0_dq_1_i_ival   (1'b0),
    .io_pads_qspi0_dq_1_o_oval   (),
    .io_pads_qspi0_dq_1_o_oe     (),
    .io_pads_qspi0_dq_2_i_ival   (1'b0),
    .io_pads_qspi0_dq_2_o_oval   (),
    .io_pads_qspi0_dq_2_o_oe     (),
    .io_pads_qspi0_dq_3_i_ival   (1'b0),
    .io_pads_qspi0_dq_3_o_oval   (),
    .io_pads_qspi0_dq_3_o_oe     (),

    .io_pads_aon_erst_n_i_ival   (erst_n),
    .io_pads_dbgmode0_n_i_ival   (1'b1),
    .io_pads_dbgmode1_n_i_ival   (1'b1),
    .io_pads_dbgmode2_n_i_ival   (1'b1),
    .io_pads_bootrom_n_i_ival    (bootrom_n),
    .io_pads_aon_pmu_dwakeup_n_i_ival (1'b1),

    .io_pads_aon_pmu_padrst_o_oval      (),
    .io_pads_aon_pmu_vddpaden_o_oval    (),

    .accel_irq                   (accel_irq),

    .shmem_host_en               (host_en),
    .shmem_host_addr             (host_addr),
    .shmem_host_wdata            (host_wdata)
  );

  // --------------------------------------------------- sysper ICB monitor ---
  integer    n_rd = 0, n_wr = 0;
  reg [31:0] last_addr = 32'h0;
  reg        last_rd   = 1'b0;
  reg        seen_id   = 1'b0;
  reg        seen_err  = 1'b0;
  reg [31:0] id_rdata  = 32'h0;
  integer    n_pkt     = 0;

  wire cmd_hs = dut.sysper_icb_cmd_valid & dut.sysper_icb_cmd_ready;
  wire rsp_hs = dut.sysper_icb_rsp_valid & dut.sysper_icb_rsp_ready;
  wire [31:0] eff_addr = cmd_hs ? dut.sysper_icb_cmd_addr : last_addr;
  wire        eff_rd   = cmd_hs ? dut.sysper_icb_cmd_read : last_rd;

  always @(posedge hfextclk) begin
    if (cmd_hs) begin
      last_addr <= dut.sysper_icb_cmd_addr;
      last_rd   <= dut.sysper_icb_cmd_read;
      if (dut.sysper_icb_cmd_read) n_rd <= n_rd + 1;
      else                         n_wr <= n_wr + 1;
      if (!dut.sysper_icb_cmd_read && dut.sysper_icb_cmd_addr[15:0] == 16'h0008) begin
        n_pkt <= n_pkt + 1;
        $display("[%0t] packet %0d starts: frame=%0d (bit8 common=%b)",
                 $time, n_pkt, dut.sysper_icb_cmd_wdata[3:0],
                 dut.sysper_icb_cmd_wdata[8]);
        $fflush;
      end
    end
    if (rsp_hs) begin
      if (dut.sysper_icb_rsp_err) seen_err <= 1'b1;
      if (eff_rd && eff_addr[15:0] == 16'h0048) begin
        id_rdata <= dut.sysper_icb_rsp_rdata;
        if (dut.sysper_icb_rsp_rdata == KWT_ID) seen_id <= 1'b1;
      end
    end
  end

  // ------------------------------------------------ CPU ack from the mailbox --
  integer ack_val = 0;
  always @(posedge hfextclk) begin
    if (dut.sysmem_icb_cmd_valid && dut.sysmem_icb_cmd_ready &&
        !dut.sysmem_icb_cmd_read && dut.sysmem_icb_cmd_addr == 32'ha000_0004)
      ack_val <= dut.sysmem_icb_cmd_wdata;
  end

  // ------------------------------------------------------- host transfers ---
  reg [31:0] img [0:N_LAYER-1];

  task host_wr(input [16:0] wa, input [31:0] wd);
    begin
      @(posedge hfextclk);
      host_en    <= 1'b1;
      host_addr  <= wa;
      host_wdata <= wd;
      @(posedge hfextclk);
      host_en    <= 1'b0;
    end
  endtask

  task push(input [16:0] base, input integer n);
    integer j;
    begin
      for (j = 0; j < n; j = j + 1) host_wr(base + j[16:0], img[j]);
    end
  endtask

  // ------------------------------------------------------------- sequence ---
  integer case_idx, i, k, c, mism, first_bad;
  reg [31:0] expd [0:N_IO-1];
  string fn;
  reg done = 1'b0;
  reg [31:0] rd_word;

  initial begin
    if (!$value$plusargs("CASE=%d", case_idx)) case_idx = 0;
    if (case_idx < 0 || case_idx >= N_CASES) begin
      $display("BAD_CASE %0d", case_idx);
      $finish;
    end

    fn = $sformatf("%s/expected_%03d.hex", `FIXDIR, case_idx);
    $readmemh(fn, expd);

    erst_n = 1'b0;
    repeat (40) @(posedge lfextclk);
    $display("[%0t] release reset, pc_rtvec=0x%08h", $time,
             dut.u_e203_subsys_top.pc_rtvec);
    $fflush;
    erst_n = 1'b1;

    for (i = 0; i < 30000000 && !done; i = i + 1) begin
      @(posedge hfextclk);
      if (dut.u_e203_subsys_top.u_e203_subsys_main.u_e203_cpu_top
            .u_e203_srams.u_e203_dtcm_ram.u_e203_dtcm_gnrl_ram
            .u_sirv_sim_ram.mem_r[N_IO] == KWT_MARKER) done = 1'b1;
      if ((i % 2000000) == 0 && i != 0)
        $display("[%0t] running... %0d cycles, sysper rd=%0d wr=%0d packets=%0d ack=%0d",
                 $time, i, n_rd, n_wr, n_pkt, ack_val);
      if ((i % 2000000) == 0) $fflush;
    end

    #200;

    mism = 0;
    first_bad = -1;
    for (k = 0; k < N_IO; k = k + 1) begin
      rd_word = dut.u_e203_subsys_top.u_e203_subsys_main.u_e203_cpu_top
                  .u_e203_srams.u_e203_dtcm_ram.u_e203_dtcm_gnrl_ram
                  .u_sirv_sim_ram.mem_r[k];
      if (rd_word !== expd[k]) begin
        if (first_bad < 0) first_bad = k;
        if (mism < 8)
          $display("  MISMATCH out[%0d] got %08h expect %08h", k, rd_word, expd[k]);
        mism = mism + 1;
      end
    end

    $display("");
    $display("=== SoC 12-case regression, case %03d ===", case_idx);
    $display("  pc_rtvec        = 0x%08h (expect 0x00001000)", dut.u_e203_subsys_top.pc_rtvec);
    $display("  sysper reads    = %0d, writes = %0d, packets = %0d", n_rd, n_wr, n_pkt);
    $display("  P1 accel ID     : %s  rdata=0x%08h", seen_id ? "OK  " : "FAIL", id_rdata);
    $display("  P2 sysper err   : %s", seen_err ? "FAIL (rsp_err seen)" : "OK  (never)");
    $display("  P3 DTCM[1584]   : %s  got 0x%08h", done ? "OK  " : "FAIL",
             dut.u_e203_subsys_top.u_e203_subsys_main.u_e203_cpu_top
               .u_e203_srams.u_e203_dtcm_ram.u_e203_dtcm_gnrl_ram
               .u_sirv_sim_ram.mem_r[N_IO]);
    $display("  P4 output words : %0d/%0d match (%0d mismatches, first bad = %0d)",
             N_IO - mism, N_IO, mism, first_bad);
    $display("  sim time        = %0t", $time);

    if (seen_id && !seen_err && done && mism == 0)
      $display("RESULT: PASS case=%03d words=%0d", case_idx, N_IO);
    else
      $display("RESULT: FAIL case=%03d", case_idx);
    $fflush;

    $finish;
  end

  // ---------------------------------------------- platform loader (host) ----
  initial begin
    wait (erst_n === 1'b1);
    repeat (20) @(posedge hfextclk);

    $display("[%0t] host: loading fixtures for case %03d from %0s", $time, case_idx, `FIXDIR);
    $readmemh({`FIXDIR, "/common.bin.hex"}, img, 0, N_COMMON-1);
    push(COMMON_W[16:0], N_COMMON);
    $display("[%0t] host: common  %0d words @0xa000_1000", $time, N_COMMON);
    $fflush;

    fn = $sformatf("%s/input_%03d.hex", `FIXDIR, case_idx);
    $readmemh(fn, img, 0, N_IO-1);
    push(INPUT_W[16:0], N_IO);
    $display("[%0t] host: input   %0d words @0xa002_0000", $time, N_IO);
    $fflush;

    fn = $sformatf("%s/layer_%02d.bin.hex", `FIXDIR, 0);
    $readmemh(fn, img, 0, N_LAYER-1);
    push(LEASE_W[16:0], N_LAYER);
    host_wr(MAILBOX_W[16:0], 32'd1);
    $display("[%0t] host: layer 0 %0d words @0xa002_4000, seq=1", $time, N_LAYER);
    $fflush;

    for (k = 1; k < N_CASES; k = k + 1) begin
      wait (ack_val == k);
      fn = $sformatf("%s/layer_%02d.bin.hex", `FIXDIR, k);
      $readmemh(fn, img, 0, N_LAYER-1);
      push(LEASE_W[16:0], N_LAYER);
      host_wr(MAILBOX_W[16:0], k + 1);
      $display("[%0t] host: ack %0d seen, layer %0d loaded, seq=%0d",
               $time, k, k, k + 1);
      $fflush;
    end
    $display("[%0t] host: all 12 layers delivered", $time);
    $fflush;
  end

  // hard watchdog
  initial begin
    #400000000;
    $display("RESULT: FAIL (watchdog at %0t)", $time);
    $finish;
  end

endmodule
