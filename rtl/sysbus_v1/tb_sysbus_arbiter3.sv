`timescale 1ns/1ps
module tb_sysbus_arbiter3;
 reg clk=0,rst_n=0;always #5 clk=~clk;
 reg [2:0] cv=0,crr=7;wire [2:0] cr,rv,re;
 reg [95:0] ca={32'h300,32'h200,32'h100},cw={32'h33,32'h22,32'h11};
 wire [95:0] rd;reg [2:0] read=7;reg [11:0] mask=12'hfff;
 wire bv,brspready,bread;wire [31:0] ba,bw;wire [3:0] bm;
 reg zero_latency=1,ready=1,response=0,error=0;reg [31:0] data=32'h12345678;
 wire br=zero_latency?brspready:ready;
 wire brv=zero_latency?bv:response;
 kwt_sysbus_arbiter3 dut(clk,rst_n,cv,cr,ca,cw,read,mask,rv,crr,rd,re,
  bv,br,ba,bw,bread,bm,brv,brspready,data,error);
 integer i;
 task reset;
 begin @(negedge clk);rst_n=0;cv=0;response=0;repeat(2)@(negedge clk);
 if(bv||rv||cr||brspready)$fatal(1,"RESET_QUALIFICATION");rst_n=1;end
 endtask
 initial begin
 reset();cv=7;
 for(i=0;i<3;i=i+1)begin
  @(posedge clk);
  if(!bv||!br||!brspready||rv!==(3'b001<<i)||cr!==(3'b001<<i)||ba!==32'h100*(i+1))
   $fatal(1,"ZERO_LATENCY_ROUND_ROBIN i=%0d addr=%h ready=%b rsp=%b",i,ba,cr,rv);
  #1;cv[i]=0;
 end
 reset();zero_latency=0;ready=0;cv=2;
 @(posedge clk);#1;
 @(negedge clk);cv=3;
 repeat(3)begin @(posedge clk);if(!bv||ba!==32'h200||bw!==32'h22)$fatal(1,"STALLED_REQUEST_CHANGED");end
 @(negedge clk);ready=1;
 @(posedge clk);if(cr!==3'b010)$fatal(1,"GRANT_NOT_PRESERVED");
 #1;cv=1;crr=3'b101;
 @(negedge clk);response=1;error=1;
 repeat(3)begin
  @(posedge clk);
  if(bv||rv!==3'b010||re[1]!==1||rd[63:32]!==data||brspready)$fatal(1,"RESPONSE_BACKPRESSURE_OWNER");
 end
 @(negedge clk);crr=7;
 @(posedge clk);if(!brspready||rv!==2)$fatal(1,"RESPONSE_NOT_CONSUMED");
 #1;response=0;error=0;
 @(posedge clk);if(!bv||ba!==32'h100||cr!==1)$fatal(1,"NEXT_MASTER_NOT_ACCEPTED");
 #1;cv=0;
 // Reset with an outstanding response discards it and prevents stale routing.
 reset();response=1;
 @(posedge clk);if(rv||brspready)$fatal(1,"STALE_RESPONSE_AFTER_RESET");
 #1;response=0;
 $display("PASS SYSBUS_ARBITER3 zero_latency=3 fair=1 request_stall=1 response_stall=1 error_owner=1 inflight_reset=1");
 $finish;
 end
 initial begin #10000;$fatal(1,"WATCHDOG");end
endmodule
