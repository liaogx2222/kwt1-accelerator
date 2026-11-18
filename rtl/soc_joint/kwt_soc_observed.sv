// Simulation monitor only. CPU, subsystem, bus and accelerator remain RTL.
module kwt_soc_observed(input clk,lfclk,rst_n,host_valid,
 output host_ready,input[16:0]host_addr,input[31:0]host_data,
 output mv,mready,mread,mrv,mrr,merr,output[31:0]ma,mw,mrd,
 output pv,pready,pread,prv,prr,perr,output[31:0]pa,pw,prd,
 output[7:0]accel_state,output[31:0]pc,output retired);
 kwt_soc_joint dut(
 .hfextclk(clk),.lfextclk(lfclk),.hfxoscen(),.lfxoscen(),
 .io_pads_jtag_TCK_i_ival(1'b0),.io_pads_jtag_TMS_i_ival(1'b1),.io_pads_jtag_TDI_i_ival(1'b1),
 .io_pads_jtag_TDO_o_oval(),.io_pads_jtag_TDO_o_oe(),
 .io_pads_gpioA_i_ival(32'd0),.io_pads_gpioA_o_oval(),.io_pads_gpioA_o_oe(),
 .io_pads_gpioB_i_ival(32'd0),.io_pads_gpioB_o_oval(),.io_pads_gpioB_o_oe(),
 .io_pads_qspi0_sck_o_oval(),.io_pads_qspi0_cs_0_o_oval(),
 .io_pads_qspi0_dq_0_i_ival(1'b0),.io_pads_qspi0_dq_0_o_oval(),.io_pads_qspi0_dq_0_o_oe(),
 .io_pads_qspi0_dq_1_i_ival(1'b0),.io_pads_qspi0_dq_1_o_oval(),.io_pads_qspi0_dq_1_o_oe(),
 .io_pads_qspi0_dq_2_i_ival(1'b0),.io_pads_qspi0_dq_2_o_oval(),.io_pads_qspi0_dq_2_o_oe(),
 .io_pads_qspi0_dq_3_i_ival(1'b0),.io_pads_qspi0_dq_3_o_oval(),.io_pads_qspi0_dq_3_o_oe(),
 .io_pads_aon_erst_n_i_ival(rst_n),
 .io_pads_dbgmode0_n_i_ival(1'b1),.io_pads_dbgmode1_n_i_ival(1'b1),.io_pads_dbgmode2_n_i_ival(1'b1),
 .io_pads_bootrom_n_i_ival(1'b0),.io_pads_aon_pmu_dwakeup_n_i_ival(1'b1),
 .io_pads_aon_pmu_padrst_o_oval(),.io_pads_aon_pmu_vddpaden_o_oval(),.accel_irq(),
 .shmem_host_en(host_valid),.shmem_host_ready(host_ready),.shmem_host_addr(host_addr),.shmem_host_wdata(host_data));
 assign mv=dut.sysmem_icb_cmd_valid,mready=dut.sysmem_icb_cmd_ready,mread=dut.sysmem_icb_cmd_read;
 assign ma=dut.sysmem_icb_cmd_addr,mw=dut.sysmem_icb_cmd_wdata;
 assign mrv=dut.sysmem_icb_rsp_valid,mrr=dut.sysmem_icb_rsp_ready,merr=dut.sysmem_icb_rsp_err,mrd=dut.sysmem_icb_rsp_rdata;
 assign pv=dut.sysper_icb_cmd_valid,pready=dut.sysper_icb_cmd_ready,pread=dut.sysper_icb_cmd_read;
 assign pa=dut.sysper_icb_cmd_addr,pw=dut.sysper_icb_cmd_wdata;
 assign prv=dut.sysper_icb_rsp_valid,prr=dut.sysper_icb_rsp_ready,perr=dut.sysper_icb_rsp_err,prd=dut.sysper_icb_rsp_rdata;
 assign accel_state=dut.u_kwt1_mmio.debug_state;
 assign pc=dut.u_e203_subsys_top.u_e203_subsys_main.u_e203_cpu_top.inspect_pc;
 assign retired=dut.u_e203_subsys_top.u_e203_subsys_main.u_e203_cpu_top.u_e203_cpu.u_e203_core.u_e203_exu.u_e203_exu_csr.nonflush_cmt_ena;
endmodule
