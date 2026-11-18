module tb_icb_kwt_bridge;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,abort_hw=0,drop=0,cv=0,rr=1,cread=0,hr=1,hrv=0,ar=0,arv=0,ae=0;
 reg [31:0] ca=0,cw=0,hrd=0,ard=0;reg [3:0] cm=15;
 wire cr,rv,hv,hread,hrr,av,awrite,arr;wire [31:0] rd,ha,hw,aa,ad;wire [3:0] hm,am;wire signed [31:0] err;wire [31:0] count;
 icb_kwt_bridge dut(clk,rst_n,abort_hw,16'd3,drop,cv,cr,ca,cw,cread,cm,rv,rr,rd,hv,hr,ha,hw,hread,hm,hrv,hrr,hrd,av,ar,awrite,aa,ad,am,arv,arr,ard,ae,err,count);
 task command(input [31:0] a,input [31:0] v,input read);
  begin @(negedge clk);ca=a;cw=v;cread=read;cv=1;do @(posedge clk);while(!cr);@(negedge clk);cv=0;end
 endtask
 task response(input [31:0] v,input integer error);
  begin wait(rv);#1;if(rd!==v||err!==error)$fatal(1,"response mismatch");@(posedge clk);@(negedge clk);end
 endtask
 initial begin
  repeat(3)@(negedge clk);rst_n=1;
  command(32'h10000010,32'h12345678,0);if(!av||!awrite||aa!=16||ad!=32'h12345678||am!=15)$fatal(1,"payload");
  repeat(2)begin @(negedge clk);if(!av||ad!=32'h12345678)$fatal(1,"request stall");end
  ar=1;@(negedge clk);ar=0;ard=32'h87654321;arv=1;
  rr=0;wait(rv);#1;if(count!=1)$fatal(1,"count");repeat(3)begin @(negedge clk);if(!rv||rd!=32'h87654321)$fatal(1,"response stall");end
  arv=0;rr=1;response(32'h87654321,0);
  // A send timeout waits threshold+1 edges; callbacks see -2 without a CPU trap.
  command(32'h10000004,0,1);response(0,-2);
  command(32'h10000004,0,1);ar=1;@(negedge clk);ar=0;drop=1;arv=1;ard=77;
  response(0,-2);arv=0;drop=0;
  // Host hard reset clears sideband fault but must preserve this host reply.
  command(32'h10010030,1,0);wait(hv);@(negedge clk);abort_hw=1;hrv=1;hrd=99;@(negedge clk);abort_hw=0;hrv=0;response(99,0);
  command(32'h10000004,0,1);ar=1;@(negedge clk);ar=0;arv=1;ard=33;ae=1;
  response(33,-1);arv=0;ae=0;
  command(32'h10000010,42,0);rst_n=0;@(negedge clk);if(rv||av||count||err)$fatal(1,"reset discard");rst_n=1;
  command(32'h10000004,0,1);ar=1;@(negedge clk);ar=0;arv=1;ard=55;response(55,0);arv=0;
  $display("PASS ICB bridge request/response stall, send/response timeout, reset discard, host reset reply, error, counter");$finish;
 end
 initial begin #10000;$fatal(1,"bridge watchdog");end
endmodule
