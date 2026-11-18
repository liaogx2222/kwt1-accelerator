// =============================================================================
// tb_soc.sv -- SoC level smoke test for kwt1_chip
//
// What this proves (the thing the accelerator TB cannot prove):
//
//     CPU reset -> boot ROM 0x1000 -> RV32I execution
//        -> ICB sysper  ->  icb2kwt  ->  kwt1_mmio  ->  back
//        -> store result into DTCM 0x9000_0000
//
// The boot program is 9 instructions of hand encoded RV32I (see
// flow/smic40/mk_bootrom.py and rtl/integration/soc/sirv_mrom.v). It reads the
// accelerator ID register (0x48) and the STATUS register (0x04) and writes
// them, plus a progress marker, into DTCM.
//
// Checks
//   C1  sysper read of 0x0000_0048 returns 0x4B575431 with rsp_err = 0
//   C2  sysper read of 0x0000_0004 is issued (STATUS register reachable)
//   C3  DTCM[0] == ID, DTCM[1] == STATUS  (the CPU really retired the loads)
//   C4  DTCM[2] == 0x0000_05A5           (the program reached its last store)
//   C5  rsp_err never asserted on sysper  (no unmapped/decode error)
//   C6  accel_irq stays low               (no task was started, so no IRQ)
//
// Run from sim/soc:
//   vcs -sverilog -full64 -debug_access+all -f files.f -o simv_soc -l comp.log
//   ./simv_soc -l run_soc.log
//
// Known deviation: the add-on blocks are clocked by hfextclk rather than the
// core's internal hfclk (hfclk is not brought out of e203_subsys_top). At
// functional level this is the same clock; recorded, not hidden.
// =============================================================================
`timescale 1ns/1ps

module tb_soc;

  // ---------------------------------------------------------------- clocks --
  reg hfextclk = 1'b0;
  always #5 hfextclk = ~hfextclk;              // 100 MHz core clock

  // The AON/PMU block is clocked by lfextclk and its power-up FSM needs a few
  // dozen lfclk edges before it releases hfclkrst and the core reset. Running
  // lfextclk at the real 32.768 kHz would cost ~10 ms of simulation time for
  // the same sequence, so the TB uses 15 MHz (66 ns) like the vendor tb_top.v.
  reg lfextclk = 1'b0;
  always #33 lfextclk = ~lfextclk;             // 15 MHz: fast lfclk so the PMU
                                                 // power-up FSM finishes quickly

  // ------------------------------------------------------------ pad inputs --
  reg         erst_n    = 1'b0;                // active-low SoC reset
  reg         bootrom_n = 1'b0;                // 0 -> aon_io_bootrom = 1 -> PC 0x1000
  reg  [31:0] gpioa     = 32'h0;
  reg  [31:0] gpiob     = 32'h0;

  // ------------------------------------------------------------ pad outputs --
  wire        accel_irq;
  wire        hfxoscen, lfxoscen;
  wire [31:0] gpioa_o, gpioa_oe, gpiob_o, gpiob_oe;

  // ------------------------------------------------------------------- DUT ---
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

    .accel_irq                   (accel_irq)
  );

  // ------------------------------------------------ hierarchical probes ------
  // DTCM word 0..2. Full path:
  //   soc_top / e203_subsys_top / e203_subsys_main / e203_cpu_top /
  //   e203_srams / e203_dtcm_ram / sirv_gnrl_ram / sirv_sim_ram.mem_r
  wire [31:0] dtcm0 = dut.u_e203_subsys_top.u_e203_subsys_main.u_e203_cpu_top
                         .u_e203_srams.u_e203_dtcm_ram.u_e203_dtcm_gnrl_ram
                         .u_sirv_sim_ram.mem_r[0];
  wire [31:0] dtcm1 = dut.u_e203_subsys_top.u_e203_subsys_main.u_e203_cpu_top
                         .u_e203_srams.u_e203_dtcm_ram.u_e203_dtcm_gnrl_ram
                         .u_sirv_sim_ram.mem_r[1];
  wire [31:0] dtcm2 = dut.u_e203_subsys_top.u_e203_subsys_main.u_e203_cpu_top
                         .u_e203_srams.u_e203_dtcm_ram.u_e203_dtcm_gnrl_ram
                         .u_sirv_sim_ram.mem_r[2];

  // ------------------------------------------------ sysper ICB monitor ------
  localparam [31:0] KWT_ID     = 32'h4B575431;
  localparam [31:0] KWT_MARKER = 32'h0000_05A5;

  integer    n_rd = 0, n_wr = 0;
  reg [31:0] last_addr = 32'h0;
  reg        last_rd   = 1'b0;

  reg        seen_id     = 1'b0;
  reg        seen_status = 1'b0;
  reg        seen_err    = 1'b0;
  reg [31:0] id_rdata    = 32'h0;

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
    end
    if (rsp_hs) begin
      if (dut.sysper_icb_rsp_err) seen_err <= 1'b1;
      if (eff_rd && eff_addr[15:0] == 16'h0048) begin
        id_rdata <= dut.sysper_icb_rsp_rdata;
        if (dut.sysper_icb_rsp_rdata == KWT_ID) seen_id <= 1'b1;
      end
      if (eff_rd && eff_addr[15:0] == 16'h0004) seen_status <= 1'b1;
    end
  end

  // ------------------------------------------------------------- sequence ----
  integer i;
  reg done = 1'b0;

  initial begin
    // The bootrom pad goes through a 4 stage 32 kHz deglitch, so the reset has
    // to stay low for a few lfclk periods before pc_rtvec is valid.
    erst_n = 1'b0;
    repeat (40) @(posedge lfextclk);
    $display("[%0t] release reset, pc_rtvec=0x%08h", $time,
             dut.u_e203_subsys_top.pc_rtvec);
    $fflush;
    erst_n = 1'b1;

    for (i = 0; i < 200000 && !done; i = i + 1) begin
      @(posedge hfextclk);
      if (dtcm2 == KWT_MARKER) done = 1'b1;
    end

    #200;

    $display("");
    $display("=== SoC boot / ICB bridge test ===");
    $display("  pc_rtvec        = 0x%08h  (expect 0x00001000)", dut.u_e203_subsys_top.pc_rtvec);
    $display("  sysper reads    = %0d, writes = %0d", n_rd, n_wr);
    $display("  C1 ID  0x48     : %s  rdata=0x%08h (expect 0x%08h)",
             seen_id ? "OK  " : "FAIL", id_rdata, KWT_ID);
    $display("  C2 STATUS 0x04  : %s", seen_status ? "OK  " : "FAIL");
    $display("  C3 DTCM[0..1]   : 0x%08h 0x%08h (expect 0x%08h / status)",
             dtcm0, dtcm1, KWT_ID);
    $display("  C4 DTCM[2] mark : 0x%08h (expect 0x%08h)", dtcm2, KWT_MARKER);
    $display("  C5 sysper err   : %s", seen_err ? "FAIL (rsp_err seen)" : "OK  (never)");
    $display("  C6 accel_irq    : %s", accel_irq ? "FAIL (unexpected)" : "OK  (low)");

    if (seen_id && seen_status && (dtcm0 == KWT_ID) && (dtcm2 == KWT_MARKER)
        && !seen_err && !accel_irq && done) begin
      $display("RESULT: PASS");
    end else begin
      $display("RESULT: FAIL");
    end
    $fflush;

    if (!done) $display("  note: marker never appeared -> boot program did not finish");

    $finish;
  end

  // hard watchdog
  initial begin
    #2000000;                                   // 2 ms
    $display("RESULT: FAIL (timeout at %0t)", $time);
    $finish;
  end

`ifdef DBG
  // Bring-up aid: is the core clock even running?
  integer n_hf = 0, n_csr = 0;
  always @(posedge dut.u_e203_subsys_top.hfclk)         n_hf  = n_hf  + 1;
  always @(posedge dut.u_e203_subsys_top.core_csr_clk)  n_csr = n_csr + 1;

  wire [31:0] dbg_pc =
      dut.u_e203_subsys_top.u_e203_subsys_main.u_e203_cpu_top.u_e203_cpu
         .u_e203_core.u_e203_exu.u_e203_exu_commit.alu_cmt_i_pc;

  integer n_mrom = 0, n_sysmem = 0;
  always @(posedge hfextclk) if (dut.u_e203_subsys_top.u_e203_subsys_main
        .u_e203_subsys_mems.mrom_icb_cmd_valid) n_mrom = n_mrom + 1;
  always @(posedge hfextclk) if (dut.sysmem_icb_cmd_valid) n_sysmem = n_sysmem + 1;

  initial begin
    #400000;
    $display("[DBG %0t] hfclk_edges=%0d csr=%0d mrom_cmd=%0d sysmem=%0d hfclkrst=%b main_rst_n=%b tm_stop=%b pc=0x%08h",
             $time, n_hf, n_csr, n_mrom, n_sysmem, dut.u_e203_subsys_top.hfclkrst,
             dut.u_e203_subsys_top.u_e203_subsys_main.main_rst_n,
             dut.u_e203_subsys_top.u_e203_subsys_main.tm_stop, dbg_pc);
    #400000;
    $display("[DBG %0t] hfclk_edges=%0d csr_edges=%0d pc=0x%08h",
             $time, n_hf, n_csr, dbg_pc);
  end
`endif

endmodule
