`timescale 1ns/1ps
module tb_nice_prefetch2;
 parameter EXPECT_DEPTH=2;
 localparam T=32;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,req=0,cpu_ready=0,cancel=0,sink_error=0;
 reg[31:0]inst=0,rs1=0,rs2=0;wire req_ready,reply,reply_error,active,holdup;wire[31:0]status;
 wire mv,mr,mread,rv,rr,rerr,sv,sr,sl,si,oa,ov,orr,ol,ack;
 wire[31:0]ma,mw,rd,sd,od;
 wire unused_cv,unused_rr;wire[31:0]unused_ca,unused_cw;wire unused_read;wire[1:0]unused_size;
 e203_subsys_nice_core #(.TIMEOUT(T)) dut(clk,rst_n,active,holdup,req,req_ready,inst,rs1,rs2,reply,cpu_ready,status,reply_error,
  unused_cv,1'b0,unused_ca,unused_read,unused_cw,unused_size,1'b0,unused_rr,32'hxxxxxxxx,1'b0,
  mv,mr,ma,mread,mw,rv,rr,rd,rerr,sv,sr,sd,sl,si,sink_error,cancel,oa,ov,orr,od,ol,ack);
 integer cycle=0,test=0,kind=0,length=0,error_at=-1;
 reg[31:0]base=0;
 reg block_cmd=0,block_rsp=0,block_sink=0,block_source=0,fixed_ready=0,bad_last=0,late_response=0;
 integer sent=0,responded=0,consumed=0,produced=0,acks=0,peak=0,wp=0,rp=0,used=0;
 reg[31:0]queue_data[0:7];reg queue_error[0:7];integer due[0:7];
 function automatic[31:0]word(input integer index);begin word=32'hb58a1703^(index*32'h01030711);end endfunction
 assign mr=rst_n&&!block_cmd&&used<8&&(fixed_ready||cycle%7!=0);
 assign rv=late_response||(rst_n&&used>0&&due[rp]<=cycle&&!block_rsp);
 assign rd=rv?queue_data[rp]:32'hxxxxxxxx;assign rerr=rv?queue_error[rp]:1'b0;
 assign sr=!block_sink&&(fixed_ready||cycle%11>3);
 assign ov=rst_n&&!block_source&&produced<length&&(fixed_ready||cycle%5!=0);
 assign od=ov?word(produced):32'hxxxxxxxx;assign ol=bad_last?! (produced==length-1):produced==length-1;
 reg req_held=0,sink_held=0;reg[64:0]held_req;reg[33:0]held_sink;
 reg push,pop;integer j;
 always @(negedge clk)cycle=cycle+1;
 always @(posedge clk)begin
  if(!rst_n)begin
   sent=0;responded=0;consumed=0;produced=0;acks=0;peak=0;
   wp<=0;rp<=0;used<=0;req_held=0;sink_held=0;
  end else begin
   push=mv&&mr;pop=rv&&rr;
   if(unused_cv||unused_rr)$fatal(1,"unexpected LSU NICE request");
   if(req_held&&(!mv||{ma,mw,mread}!==held_req))$fatal(1,"visible request withdrawn/changed test=%0d",test);
   req_held=mv&&!mr;held_req={ma,mw,mread};
   // Explicit cancel, sink error or timeout may terminate a held word.
   // Ordinary backpressure and a later prefetched memory error may not.
   if(sink_held&&!cancel&&!sink_error&&!reply&&sv&&{sd,sl,si}!==held_sink)$fatal(1,"held sink data changed test=%0d",test);
   if(sink_held&&!cancel&&!sink_error&&!reply&&!sv&&cycle-held_since<T-1)$fatal(1,"held sink withdrawn early test=%0d",test);
   if(sv&&!sr&&!sink_held)held_since=cycle;
   sink_held=sv&&!sr;held_sink={sd,sl,si};
   if(push)begin
    if(ma!==base+sent*4||mread!==(kind!=2))$fatal(1,"request range/order test=%0d index=%0d addr=%h",test,sent,ma);
    if(sent>=length)$fatal(1,"read beyond supplied range");
    if(kind==2&&mw!==word(sent))$fatal(1,"wrong output payload");
    queue_data[wp]<=word(sent);queue_error[wp]<=sent==error_at;due[wp]<=cycle+3+(fixed_ready?0:sent%3);
    wp<=(wp+1)%8;sent=sent+1;
   end
   if(pop)begin rp<=(rp+1)%8;responded=responded+1;end
   case({push,pop})2'b10:used<=used+1;2'b01:used<=used-1;default:used<=used;endcase
   if(sent-responded>peak)peak=sent-responded;
   if(sent-responded>EXPECT_DEPTH)$fatal(1,"request credit exceeded");
   if(sv&&sr)begin
    if(kind==2||sd!==word(consumed)||sl!==(consumed==length-1)||si!==(kind==1))$fatal(1,"sink order/data/tag test=%0d index=%0d",test,consumed);
    consumed=consumed+1;
   end
   if(ov&&orr)produced=produced+1;
   if(ack)begin
    if(kind!=2||responded!=length||sent!=length)$fatal(1,"ACK before final physical response");acks=acks+1;
   end
   if(reply&&(used!=0||mv))$fatal(1,"work survives instruction completion test=%0d pending=%0d",test,used);
  end
 end
 integer held_since=0,guard,start_cycle,successes=0,failures=0,request_deadlines=0,response_deadlines=0,sink_deadlines=0;
 task reset_all;
 begin
  @(negedge clk);rst_n=0;req=0;cpu_ready=0;cancel=0;sink_error=0;
  block_cmd=0;block_rsp=0;block_sink=0;block_source=0;fixed_ready=0;bad_last=0;error_at=-1;late_response=0;
  repeat(3)@(negedge clk);rst_n=1;repeat(2)@(negedge clk);
  if(reply||mv||sv||ack)$fatal(1,"stale reset outputs");
 end endtask
 task start(input integer k,input[31:0]address,input integer n);
 begin
  test=test+1;kind=k;base=address;length=n;
  sent=0;responded=0;consumed=0;produced=0;acks=0;peak=0;req_held=0;sink_held=0;
  @(negedge clk);inst=((7'h28+k)<<25)|(7<<12)|7'h7b;rs1=address;rs2=n;req=1;start_cycle=cycle;
  @(posedge clk);while(!req_ready)@(posedge clk);
  @(negedge clk);req=0;inst=32'hxxxxxxxx;rs1=32'hxxxxxxxx;rs2=32'hxxxxxxxx;
 end endtask
 task finish(input integer code,input integer cursor,input integer committed);
 reg[31:0]expected,held_status;
 begin
  guard=0;
  while(!reply)begin @(negedge clk);guard=guard+1;if(guard>200000)$fatal(1,"reply watchdog test=%0d",test);end
  #1;expected=code==0?0:(32'h80000000|(committed?32'h40000000:0)|(cursor<<8)|code);
  if(status!==expected||reply_error!==0)$fatal(1,"status test=%0d got=%h expected=%h",test,status,expected);
  if(kind!=2&&consumed!=cursor)$fatal(1,"wrong committed read prefix test=%0d got=%0d expected=%0d",test,consumed,cursor);
  if(sent!=responded||used!=0||mv)$fatal(1,"physical response not drained");
  held_status=status;
  repeat(4)begin @(negedge clk);if(!reply||status!==held_status||!active||!holdup||mv||sv||orr)$fatal(1,"CPU response hold");end
  if(kind==2&&acks!=(code==0?1:0))$fatal(1,"final write ACK contract");
  if(code==0)successes=successes+1;else failures=failures+1;
  $display("NICE_CASE test=%0d kind=%0d words=%0d code=%0d cursor=%0d issued=%0d peak=%0d cycles=%0d",test,kind,length,code,cursor,sent,peak,cycle-start_cycle);
  cpu_ready=1;@(negedge clk);cpu_ready=0;cancel=0;sink_error=0;
  if(!req_ready||mv)$fatal(1,"not ready after completion");
 end endtask
 integer n,k;
 initial begin
  reset_all();
  // Same object, varied cold instructions, including both pointer wraps and
  // ABI boundary lengths. No reset between these successful instructions.
  for(k=0;k<2;k=k+1)begin
   for(n=1;n<=257;n=n==1?2:n==2?3:n==3?31:n==31?64:n==64?257:258)begin
    start(k,k==0?32'ha0024000:32'ha0040000,n);finish(0,n,0);
   end
  end
  if(EXPECT_DEPTH==2&&peak!=2)$fatal(1,"prefetch depth never used");
  start(0,32'ha0024000,15432);finish(0,15432,0);
  start(1,32'ha0040000,3168);finish(0,3168,0);
  for(k=0;k<4;k=k+1)begin
   reset_all();error_at=k==0?0:k==1?1:k==2?7:31;start(0,32'ha0024000,64);finish(1,error_at,0);
  end
  reset_all();block_cmd=1;start(0,32'ha0024000,8);wait(mv);repeat(3)@(negedge clk);cancel=1;
  repeat(3)begin @(negedge clk);if(!mv||reply)$fatal(1,"cancelled visible request not retained");end
  block_cmd=0;finish(3,0,0);
  reset_all();block_rsp=1;error_at=0;start(0,32'ha0024000,8);wait(sent>0);@(negedge clk);cancel=1;
  repeat(3)@(negedge clk);if(reply)$fatal(1,"cancel replied before drain");sink_error=1;block_rsp=0;finish(3,0,0);
  reset_all();block_sink=1;start(1,32'ha0040000,8);wait(sv);@(negedge clk);cancel=1;finish(3,0,0);
  reset_all();block_sink=1;start(1,32'ha0040000,8);wait(sv);@(negedge clk);sink_error=1;finish(5,0,0);
  // Progress on the last permitted edge wins; one extra blocked edge times out.
  for(k=0;k<2;k=k+1)begin
   reset_all();fixed_ready=1;block_cmd=1;start(0,32'ha0024000,1);wait(mv);
   repeat(k==0?T-1:T+1)@(posedge clk);@(negedge clk);block_cmd=0;finish(k==0?0:2,k==0?1:0,0);request_deadlines=request_deadlines+1;
   reset_all();fixed_ready=1;block_rsp=1;start(0,32'ha0024000,1);wait(sent==1);
   repeat(k==0?T-1:T+1)@(posedge clk);@(negedge clk);block_rsp=0;finish(k==0?0:2,k==0?1:0,0);response_deadlines=response_deadlines+1;
   reset_all();fixed_ready=1;block_sink=1;start(0,32'ha0024000,1);wait(sv);@(posedge clk);
   repeat(k==0?T-1:T+1)@(posedge clk);@(negedge clk);block_sink=0;finish(k==0?0:2,k==0?1:0,0);sink_deadlines=sink_deadlines+1;
  end
  // Reset with outstanding reads, then a complete successful instruction.
  reset_all();block_rsp=1;start(0,32'ha0024000,31);wait(sent-responded==EXPECT_DEPTH);reset_all();
  start(0,32'ha0024000,31);finish(0,31,0);
  reset_all();block_cmd=1;start(0,32'ha0024000,31);wait(mv&&!mr);reset_all();late_response=1;
  repeat(4)begin @(negedge clk);if(rr||reply||mv||sv)$fatal(1,"unsolicited late response after reset");end
  late_response=0;start(1,32'ha0040000,31);finish(0,31,0);
  // Original output behavior: no early final ACK, late physical write after
  // cancel is reported via bit30, and length/source errors remain enabled.
  reset_all();start(2,32'ha0022000,32);finish(0,32,0);
  reset_all();block_rsp=1;start(2,32'ha0022000,1);wait(sent==1);@(negedge clk);cancel=1;
  repeat(3)@(negedge clk);if(reply||ack)$fatal(1,"write completed before physical response");block_rsp=0;finish(3,0,1);
  reset_all();bad_last=1;start(2,32'ha0022000,2);finish(6,0,0);
  reset_all();block_source=1;start(2,32'ha0022000,1);finish(2,0,0);
  reset_all();start(0,32'ha0024000,0);finish(4,0,0);
  reset_all();start(0,32'ha0024002,4);finish(4,0,0);
  reset_all();start(0,32'ha0024000,15433);finish(4,0,0);
  $display("PASS NICE_PREFETCH depth=%0d successes=%0d faults=%0d request_deadlines=%0d response_deadlines=%0d sink_deadlines=%0d",EXPECT_DEPTH,successes,failures,request_deadlines,response_deadlines,sink_deadlines);$finish;
 end
 initial begin #20000000;$fatal(1,"global watchdog");end
endmodule
