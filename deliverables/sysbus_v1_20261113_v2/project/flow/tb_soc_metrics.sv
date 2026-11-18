`timescale 1ns/1fs
module tb_soc_metrics;
 reg hfextclk=0,lfextclk=0,erst_n=0;
 always #3.333333333 hfextclk=~hfextclk;
 always #15258.7890625 lfextclk=~lfextclk;
 reg host_en=0;reg [16:0] host_addr=0;reg [31:0] host_wdata=0;
 wire host_ready;reg bootrom_n=0;reg[31:0]gpioa=0,gpiob=0;
 wire hfxoscen,lfxoscen,accel_irq;wire[31:0]gpioa_o,gpioa_oe,gpiob_o,gpiob_oe;
 wire pv,pr,pread,rv,rr,rerr,mv,mr,mread,mrv,mrr,xv,xr,xread,bi,bp;
 wire [31:0] pa,pw,rd,ma,mw,xa,xw;
 // DUT_INSTANCE is generated from the unchanged physical pad port list.
 // Connections below retain diagnostic ports as zero-load observations.
  kwt_soc_joint dut (
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
    .shmem_host_ready            (host_ready),
    .shmem_host_addr             (host_addr),
    .shmem_host_wdata            (host_wdata),
    .mon_pv(pv),
    .mon_pr(pr),
    .mon_pread(pread),
    .mon_pa(pa),
    .mon_pw(pw),
    .mon_rv(rv),
    .mon_rr(rr),
    .mon_rerr(rerr),
    .mon_rd(rd),
    .mon_mv(mv),
    .mon_mr(mr),
    .mon_mread(mread),
    .mon_ma(ma),
    .mon_mw(mw),
    .mon_mrv(mrv),
    .mon_mrr(mrr),
    .mon_xv(xv),
    .mon_xr(xr),
    .mon_xread(xread),
    .mon_xa(xa),
    .mon_xw(xw),
    .mon_bi(bi),
    .mon_bp(bp)
  );
 reg [31:0] image[0:15431],expected[0:1583];
 integer ack=0,packets=0,params=0,inputs=0,outputs=0,host_words=0;
 reg [31:0] last_addr=0;reg last_read=0,id_seen=0,done=0,marker_pending=0,compute_seen=0;
 reg started=0;reg [63:0] ticks=0,first_tick=0,last_tick=0;
 integer mode=0,recovered=0,k,case_id=0;string fixtures,outdir,fn;
 reg activity_started=0,activity_closed=0;realtime activity_begin,activity_end;
 string saif_filename;integer saif_fd;
 always @(posedge hfextclk)begin
  ticks<=ticks+1;
  if(!erst_n)begin
   ack<=0;packets<=0;params<=0;inputs<=0;outputs<=0;host_words<=0;
   id_seen<=0;done<=0;marker_pending<=0;compute_seen<=0;started<=0;
   last_addr<=0;last_read<=0;first_tick<=0;last_tick<=0;
  end else begin
   if(pv&&pr)begin
    last_addr<=pa;last_read<=pread;
    if(!pread&&pa==32'h11000008)packets<=packets+1;
    if(!pread&&pa==32'h11000000&&pw==1)compute_seen<=1;
   end
   if(rv&&rr)begin
    if(rerr)$fatal(1,"SOC_BUS_ERROR");
    if(last_read&&last_addr==32'h11000048&&rd==32'h4b575433)id_seen<=1;
   end
   if(bp)params<=params+1;
   if(bi)inputs<=inputs+1;
   if(host_en&&host_ready)begin host_words<=host_words+1;if(!started)begin started<=1;first_tick<=ticks;end end
   if(xv&&xr&&!xread)begin
    if(xa==32'ha0000004)ack<=xw;
    if(xa>=32'ha0022000&&xa<32'ha00238c0)begin
     if(outputs>=1584||xa!==32'ha0022000+4*outputs)$fatal(1,"SOC_OUTPUT_ADDRESS");
     if(xw!==expected[outputs])$fatal(1,"SOC_OUTPUT_MISMATCH index=%0d got=%08h expected=%08h",outputs,xw,expected[outputs]);
     outputs<=outputs+1;
    end
   end
   if(mv&&mr&&!mread)begin
    if(ma==32'ha0000008&&mw==32'hbad00000)$fatal(1,"SOC_FIRMWARE_ERROR");
    if(ma==32'ha0000008&&mw==32'h5a5)marker_pending<=1;
   end
   if(marker_pending&&mrv&&mrr)begin done<=1;last_tick<=ticks;marker_pending<=0;end
  end
 end
 task host_write(input [16:0] addr,input [31:0] data);
  begin
   @(negedge hfextclk);host_en=1;host_addr=addr;host_wdata=data;
`ifdef SOC_SAIF
   if(!activity_started&&(!mode||recovered))begin
    $set_toggle_region(dut);$toggle_start;activity_begin=$realtime;activity_started=1;
   end
`endif
   @(posedge hfextclk);while(!host_ready)@(posedge hfextclk);
   @(negedge hfextclk);host_en=0;repeat(4)@(negedge hfextclk);
  end
 endtask
 task push(input integer base,input integer count);
  integer z;begin for(z=0;z<count;z=z+1)host_write(base+z,image[z]);end
 endtask
 task supply;
  integer layer;begin
   wait(id_seen===1);repeat(20)@(posedge hfextclk);
   $readmemh({fixtures,"/common.bin.hex"},image,0,4143);push('h400,4144);
   fn=$sformatf("%s/input_%03d.hex",fixtures,case_id);$readmemh(fn,image,0,3167);push('h10000,3168);
   $readmemh({fixtures,"/layer_00.bin.hex"},image,0,15431);push('h9000,15432);host_write(0,1);
   for(layer=1;layer<12;layer=layer+1)begin
    wait(ack==layer);fn=$sformatf("%s/layer_%02d.bin.hex",fixtures,layer);
    $readmemh(fn,image,0,15431);push('h9000,15432);host_write(0,layer+1);
   end
   wait(done===1);
  end
 endtask
 always @(negedge hfextclk)begin
`ifdef SOC_SAIF
  if(done&&activity_started&&!activity_closed)begin
   $toggle_stop;activity_end=$realtime;
   saif_filename={outdir,"/task.saif"};
   $toggle_report(saif_filename,1.0e-9,"tb_soc_metrics.dut");
   saif_fd=$fopen(saif_filename,"r");
   if(saif_fd==0)$fatal(1,"SOC_SAIF_NOT_CREATED");
   if($fgetc(saif_fd)==-1)$fatal(1,"SOC_SAIF_EMPTY");
   $fclose(saif_fd);
   $display("SOC_ACTIVITY_WINDOW_NS begin=%0.6f end=%0.6f duration=%0.6f",activity_begin,activity_end,activity_end-activity_begin);
   activity_closed=1;
  end
`endif
 end
 initial begin
  if(!$value$plusargs("FIXTURES=%s",fixtures))fixtures="fixtures";
  if(!$value$plusargs("OUT=%s",outdir))outdir=".";
  if(!$value$plusargs("RECOVERY=%d",mode))mode=0;
  if(!$value$plusargs("CASE=%d",case_id))case_id=0;
  fn=$sformatf("%s/expected_%03d.hex",fixtures,case_id);$readmemh(fn,expected);
  repeat(40)@(posedge lfextclk);@(negedge hfextclk);erst_n=1;
  if(mode)begin
   fork:partial_task
    begin supply();$fatal(1,"RECOVERY_POINT_MISSED");end
    begin
     wait(compute_seen===1);repeat(20000)@(negedge hfextclk);
     $display("SOC_GATE_RESET_IN_FLIGHT outputs=%0d packets=%0d",outputs,packets);
    end
   join_any
   disable partial_task;
   erst_n=0;host_en=0;host_addr=0;host_wdata=0;
   repeat(40)@(posedge lfextclk);@(negedge hfextclk);recovered=1;erst_n=1;
  end
  supply();repeat(2)@(negedge hfextclk);
  if(params!=189328||inputs!=3168||outputs!=1584||packets!=13||host_words!=192508)$fatal(1,"SOC_TOTALS params=%0d in=%0d out=%0d packets=%0d host=%0d",params,inputs,outputs,packets,host_words);
  $display("SOC_GATE_METRICS cycles=%0d params=%0d input_words=%0d output_words=%0d host_words=%0d",last_tick-first_tick+1,params,inputs,outputs,host_words);
  $display("PASS SOC_INPUT16_GATE recovery=%0d case=%0d words=1584 mismatches=0",mode,case_id);
  $finish;
 end
 initial begin #2000000000;$fatal(1,"SOC_GATE_WATCHDOG");end
endmodule
