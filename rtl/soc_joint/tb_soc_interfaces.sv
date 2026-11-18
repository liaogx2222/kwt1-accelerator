`timescale 1ns/1ps
module tb_soc_interfaces;
 reg clk=0;always #5 clk=~clk;
 reg rst=0;
 reg cv=0,crd=1,rr=0;reg [31:0] ca=0,cwd=0;reg[3:0] cm=15;
 wire cq,rv,re;wire[31:0] rd;
 reg hv=0;wire hr;reg[16:0] ha=0;reg[31:0] hd=0;
 kwt_soc_shared_sram ram(clk,rst,cv,cq,ca,crd,cwd,cm,rv,rr,re,rd,hv,hr,ha,hd);
 reg bv=0,brd=1,brr=0;reg[31:0] ba=0,bwd=0;reg[3:0] bm=15;
 wire bq,brv,bre;wire[31:0] brdata;
 wire qv,qw,qr;wire[31:0] qa,qd;wire[3:0] qm;
 reg ready=1,response=0;reg[31:0] response_data=0;
 wire hit;
 kwt_soc_icb_bridge bridge(clk,rst,bv,bq,ba,brd,bwd,bm,brv,brr,bre,brdata,qv,ready,qw,qa,qd,qm,response,qr,response_data,1'b0,hit);
 integer writes=0,reads=0,checks=0;
 task host(input[16:0] a,input[31:0] data);
 begin @(negedge clk);hv=1;ha=a;hd=data;@(posedge clk);while(!hr)@(posedge clk);@(negedge clk);hv=0;end endtask
 task memory(input bit read_mode,input[31:0] addr,input[31:0] data,input[3:0] mask,input[31:0] expected);
 reg[31:0] held;
 begin
  @(negedge clk);cv=1;crd=read_mode;ca=addr;cwd=data;cm=mask;rr=0;
  @(posedge clk);while(!cq)@(posedge clk);@(negedge clk);cv=0;
  while(!rv)@(negedge clk);
  held=rd;
  repeat(4)begin @(negedge clk);if(!rv||re||rd!==held)$fatal(1,"shared response backpressure");end
  if(read_mode&&rd!==expected)$fatal(1,"shared got=%h expected=%h",rd,expected);
  rr=1;@(negedge clk);rr=0;checks=checks+1;
 end endtask
 initial begin
  repeat(3)@(negedge clk);rst=1;
  host(0,32'h11223344);host(17'h1ffff,32'h55667788);
  memory(1,32'ha0000000,0,15,32'h11223344);
  memory(1,32'ha007fffc,0,15,32'h55667788);
  memory(0,32'ha0000000,32'haabbccdd,4'b0101,0);
  memory(1,32'ha0000000,0,15,32'h11bb33dd);
  // Host request arrives during RMW. It must wait while CPU commits; neither
  // transfer may be lost, and masked-off bytes must survive.
  @(negedge clk);cv=1;crd=0;ca=32'ha0000000;cwd=32'h99007700;cm=4'b1010;
  @(posedge clk);while(!cq)@(posedge clk);
  @(negedge clk);cv=0;hv=1;ha=1;hd=32'hcafef00d;
  if(hr)$fatal(1,"host overwrote in-flight RMW");
  @(posedge clk);@(negedge clk);if(!hr)$fatal(1,"host did not resume");
  @(posedge clk);@(negedge clk);hv=0;rr=1;@(negedge clk);rr=0;
  memory(1,32'ha0000000,0,15,32'h99bb77dd);
  // Stale commands/host-valid can outlive reset assertion across the SoC's
  // reset synchronizers. No request or macro write may commit while reset.
  @(negedge clk);rst=0;cv=1;crd=0;ca=32'ha0000000;cwd=32'hdeadbeef;cm=15;
  hv=1;ha=0;hd=32'hbad0bad0;
  repeat(3)begin #1;if(cq||hr||rv||brv)$fatal(1,"request accepted under reset");@(negedge clk);end
  cv=0;hv=0;rst=1;
  memory(1,32'ha0000000,0,15,32'h99bb77dd);
  memory(1,32'ha0000004,0,15,32'hcafef00d);
  // Reset clears the pending response, preserves SRAM contents.
  @(negedge clk);cv=1;crd=1;ca=32'ha0000000;
  @(posedge clk);@(negedge clk);cv=0;rst=0;@(negedge clk);rst=1;
  if(rv||brv)$fatal(1,"reset response ghost");
  memory(1,32'ha0000000,0,15,32'h99bb77dd);
  // Decode error held under backpressure must block a later mapped request.
  @(negedge clk);bv=1;ba=32'h11010000;
  @(posedge clk);if(!bq)$fatal(1,"error request rejected");
  @(negedge clk);ba=32'h11000048;
  repeat(5)begin if(bq||qv||!brv||!bre)$fatal(1,"bridge reordered held error");@(negedge clk);end
  brr=1;#1;if(!bq||!qv)$fatal(1,"bridge same-cycle handoff");
  @(posedge clk);@(negedge clk);bv=0;brr=0;response=1;response_data=32'h4b575431;
  repeat(4)begin #1;if(!brv||bre||brdata!==32'h4b575431||qr)$fatal(1,"mapped response hold");@(negedge clk);end
  brr=1;@(posedge clk);@(negedge clk);response=0;brr=0;
  if(brv)$fatal(1,"extra response");
  $display("PASS SOC_INTERFACES memory_checks=%0d partial_rmw_host=1 error_handoff=1 reset=1",checks);$finish;
 end
 initial begin #100000;$fatal(1,"interface watchdog");end
endmodule
