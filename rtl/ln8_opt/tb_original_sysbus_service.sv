// Standalone protocol/capacity probe, NEVER a full-SoC port or bypass.
// Identical original decoder + single-ICB shared SRAM; eager legal 32b source.
`timescale 1ns/1ps
module tb_original_sysbus_service;
 parameter USE_ARBITER=0;
 localparam N=256;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;integer sent=0,taken=0,tick=0,first=-1,last_shared=-1,min_gap=999,max_gap=0,shared_count=0;
 integer stall=0;
 wire valid=rst_n&&sent<2*N;wire ready,rv,rr,err;wire[31:0]rdata;
 wire[31:0]addr=32'ha0000000+4*(sent%N),wd=32'hb5071000^(sent%N);
 wire rd=sent>=N;
 assign rr=!stall||tick%13>2;
 wire mv,mq,mrd,mrv,mrr,me;wire[31:0]ma,mw,mrdata;wire[3:0]mm;
 generate if(USE_ARBITER)begin:arb
  wire[2:0]cq,vr,errors;wire[95:0]results;
  kwt_sysbus_arbiter3 a(clk,rst_n,{2'b0,valid},cq,{64'b0,addr},{64'b0,wd},{2'b0,rd},{8'b0,4'hf},
   vr,{2'b11,rr},results,errors,mv,mq,ma,mw,mrd,mm,mrv,mrr,mrdata,me);
  assign ready=cq[0];assign rv=vr[0];assign rdata=results[31:0];assign err=errors[0];
 end else begin:direct
  assign mv=valid;assign ready=mq;assign ma=addr;assign mw=wd;assign mrd=rd;assign mm=4'hf;
  assign rv=mrv;assign mrr=rr;assign rdata=mrdata;assign err=me;
 end endgenerate
 wire sv,sq,srd,srv,srr,se;wire[31:0]sa,sw,sdata;wire[3:0]sm;
 e203_subsys_mems decoder(.clk(clk),.rst_n(rst_n),.bus_rst_n(rst_n),
  .mem_icb_cmd_valid(mv),.mem_icb_cmd_ready(mq),.mem_icb_cmd_addr(ma),.mem_icb_cmd_read(mrd),.mem_icb_cmd_wdata(mw),.mem_icb_cmd_wmask(mm),
  .mem_icb_rsp_valid(mrv),.mem_icb_rsp_ready(mrr),.mem_icb_rsp_err(me),.mem_icb_rsp_rdata(mrdata),
  .sysmem_icb_cmd_valid(sv),.sysmem_icb_cmd_ready(sq),.sysmem_icb_cmd_addr(sa),.sysmem_icb_cmd_read(srd),.sysmem_icb_cmd_wdata(sw),.sysmem_icb_cmd_wmask(sm),
  .sysmem_icb_rsp_valid(srv),.sysmem_icb_rsp_ready(srr),.sysmem_icb_rsp_err(se),.sysmem_icb_rsp_rdata(sdata),
  .qspi0_ro_icb_cmd_ready(1'b0),.qspi0_ro_icb_rsp_valid(1'b0),.qspi0_ro_icb_rsp_err(1'b0),.qspi0_ro_icb_rsp_rdata(32'b0),
  .dm_icb_cmd_ready(1'b0),.dm_icb_rsp_valid(1'b0),.dm_icb_rsp_rdata(32'b0));
 kwt_soc_shared_sram ram(clk,rst_n,sv,sq,sa,srd,sw,sm,srv,srr,se,sdata);
 reg held=0;reg[31:0]held_data;integer accepted_at[0:2*N-1];
 always @(posedge clk)if(rst_n)begin
  tick=tick+1;
  if(tick<16)$display("BUS_TRACE t=%0d sent=%0d taken=%0d cmd=%b/%b shared=%b/%b srsp=%b/%b rsp=%b/%b addr=%h",tick,sent,taken,mv,mq,sv,sq,srv,srr,rv,rr,ma);
  if(valid&&ready)begin
   if(first<0)first=tick;accepted_at[sent]=tick;sent<=sent+1;
  end
  if(sv&&sq)begin
   if(last_shared>=0)begin
    if(tick-last_shared<min_gap)min_gap=tick-last_shared;
    if(tick-last_shared>max_gap)max_gap=tick-last_shared;
   end
   last_shared=tick;shared_count=shared_count+1;
  end
  if(held&&(!rv||rdata!==held_data))$fatal(1,"held response changed");
  held=rv&&!rr;held_data=rdata;
  if(rv&&rr)begin
   if(err||taken>=sent)$fatal(1,"unexpected response");
   if(taken>=N&&rdata!==(32'hb5071000^(taken-N)))$fatal(1,"read mismatch index=%0d got=%h",taken-N,rdata);
   if(taken==2*N-1)begin
    if(shared_count!=2*N)$fatal(1,"shared totals");
    $display("PASS ORIGINAL_BUS arbiter=%0d stall=%0d commands=%0d window_cycles=%0d min_shared_gap=%0d max_shared_gap=%0d",USE_ARBITER,stall,shared_count,tick-first+1,min_gap,max_gap);$finish;
   end
   taken<=taken+1;
  end
  if(tick>20000)$fatal(1,"watchdog sent=%0d taken=%0d shared=%0d",sent,taken,shared_count);
 end
 initial begin
  if(!$value$plusargs("STALL=%d",stall))stall=0;
  repeat(3)@(negedge clk);rst_n=1;
 end
endmodule
