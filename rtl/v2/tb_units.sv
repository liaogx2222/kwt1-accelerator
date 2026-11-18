module tb_units;
 reg clk=0;always #5 clk=~clk;
 reg rst=0,mv=0,mr=1;wire mq,ov,oe;reg [2:0] op=0;reg [63:0] a=0,b=0;reg signed [7:0] sh=0;reg [5:0] sat=0;reg [7:0] tag=0;wire [63:0] result;wire [7:0] ot;
 kwt_math m(clk,rst,mv,mq,op,a,b,sh,sat,tag,ov,mr,result,oe,ot);
 reg iv=0,ir=0,sqrt_mode=0;reg [63:0] ia=0,ib=0;wire iq,iov,ie;wire [63:0] iresult,irem;
 kwt_iterative it(clk,rst,iv,iq,sqrt_mode,ia,ib,iov,ir,iresult,irem,ie);
 reg load=0,en=0,uns=0;reg [7:0] rm=0,cm=0;reg [63:0] pa=0,pb=0;reg [255:0] bias=0;wire [2047:0] acc;
 kwt_mac8x8 pe(clk,rst,load,en,uns,rm,cm,pa,pb,bias,acc);
 reg se=0,sw=0;reg [11:0] sa=0;reg [15:0] sd=0;wire [15:0] so;
 kwt_sram_sp ram(clk,se,sw,sa,sd,so);
 reg [4095:0] root,path;integer fd,rc,k,n=0,taken=0,cycle=0,groups=0,iter_count=0,latency,expected_error,mode;
 reg [63:0] ea[0:4095];reg ee[0:4095];reg [7:0] et[0:4095];reg checking=0,held=0,no_bp=0,burst=0;reg [63:0] held_value;
 integer first_issue,first_response,pair_group;
 reg [63:0] va,vb,ve,vr;reg [7:0] vs,vt;integer vop,verr,vl;
 always @(negedge clk)begin cycle=cycle+1;mr=no_bp||cycle%13>2;end
 always @(posedge clk)if(rst&&checking)begin
  if(held&&(!ov||result!==held_value))$fatal(1,"math held response changed");
  held=ov&&!mr;held_value=result;
  if(ov&&mr)begin
   if(burst&&taken==2400)begin first_response=cycle;if(first_response-first_issue!=4)$fatal(1,"RQ latency is not 4");end
   if(taken>=n||result!==ea[taken]||oe!==ee[taken]||ot!==et[taken])$fatal(1,"math vector %0d got=%h expected=%h error=%b/%b tag=%d/%d",taken,result,ea[taken],oe,ee[taken],ot,et[taken]);
   taken=taken+1;
  end
 end else held=0;
 task reset_all;
  begin @(negedge clk);rst=0;mv=0;iv=0;en=0;load=0;checking=0;repeat(3)@(negedge clk);rst=1;repeat(5)@(negedge clk);if(ov||iov)$fatal(1,"stale unit reset");end
 endtask
 initial begin
  if(!$value$plusargs("root=%s",root))$fatal(1,"missing root");reset_all();
  // Synchronous SRAM reads, held output and write without corrupting old output.
  se=1;sw=1;sa=7;sd=16'h1234;@(negedge clk);sw=0;@(negedge clk);if(so!==16'h1234)$fatal(1,"SRAM synchronous read");
  se=0;sa=8;repeat(4)@(negedge clk);if(so!==16'h1234)$fatal(1,"SRAM hold");
  // PE boundaries, masks and hold. Every cell has the same expected value.
  load=1;@(negedge clk);load=0;en=1;uns=1;rm=8'h07;cm=8'h1f;pa={8{8'hff}};pb={8{8'h81}};
  repeat(256)@(negedge clk);en=0;
  for(k=0;k<64;k=k+1)if($signed(acc[k*32+:32])!==((k/8<3&&k%8<5)?-8290560:0))$fatal(1,"PE unsigned/mask");
  repeat(7)@(negedge clk);if($signed(acc[31:0])!==-8290560)$fatal(1,"PE stall");
  load=1;@(negedge clk);load=0;uns=0;pa={8{8'h81}};pb={8{8'h7f}};rm=255;cm=255;en=1;
  repeat(256)@(negedge clk);en=0;for(k=0;k<64;k=k+1)if($signed(acc[k*32+:32])!==-4129024)$fatal(1,"PE signed");
  // Homogeneous request groups drive consecutive requests every clock whenever
  // accepted. Separate II=1 burst below has response backpressure disabled.
  fd=$fopen({root,"/math.txt"},"r");checking=1;
  while(!$feof(fd))begin
   rc=$fscanf(fd,"%h %h %h %h %h %h %h\n",vop,va,vb,vs,vt,ve,verr);
   if(rc==7)begin
    if(n>0&&vop!=op)begin @(negedge clk);mv=0;while(taken<n)@(negedge clk);groups=groups+1;end
    @(negedge clk);op=vop;a=va;b=vb;sh=vs;sat=vt;tag=n%256;ea[n]=ve;ee[n]=verr;et[n]=n%256;n=n+1;mv=1;
    @(posedge clk);while(!mq)@(posedge clk);
   end
  end
  @(negedge clk);mv=0;while(taken<n)@(negedge clk);checking=0;$fclose(fd);
  no_bp=1;checking=1;burst=1;op=3;sh=1;sat=0;b=3;
  for(k=0;k<64;k=k+1)begin
   @(negedge clk);a=k*2;tag=n%256;ea[n]=k*3;ee[n]=0;et[n]=n%256;n=n+1;mv=1;
   @(posedge clk);if(k==0)first_issue=cycle;if(!mq)$fatal(1,"RQ II=1 burst not accepted");
  end
  @(negedge clk);mv=0;while(taken<n)@(negedge clk);checking=0;burst=0;no_bp=0;
  // Exact residual: two products, one final RNE (including paired half ties).
  for(pair_group=0;pair_group<2;pair_group=pair_group+1)begin
  no_bp=pair_group==0;checking=1;op=4;sh=1;sat=16;
  for(k=0;k<128;k=k+1)begin
   @(negedge clk);tag=k;mv=1;
   a=k%2?-(k/2*2):k/2*2;b=k%2?5:3;
   if(k/2==0)begin a=1;b=1;end
   if(k/2==1)begin a=-1;b=1;end
   if(k/2==2)begin a=127;b=32'h7fffffff;end
   if(k/2==3)begin a=-127;b=32'h7fffffff;end
   if(k/2==4)begin a=k%2?1:64'h10000000000;b=1;end
   if(k%2==0)begin ea[n]=k/2==0?1:k/2==1?-1:k/2==2?32767:k/2==3?-32767:k/2==4?0:-(k/2*2);ee[n]=k/2==4;et[n]=k/2;end
   else n=n+1;
   @(posedge clk);if(no_bp&&!mq)$fatal(1,"residual paired II=1 request stalled");while(!mq)@(posedge clk);
  end
  @(negedge clk);mv=0;while(taken<n)@(negedge clk);checking=0;no_bp=0;
  end
  // A half-pair has retired into the internal partial register, then reset.
  @(negedge clk);op=4;tag=0;a=17;b=23;mv=1;@(posedge clk);while(!mq)@(posedge clk);@(negedge clk);mv=0;
  repeat(7)@(negedge clk);if(ov)$fatal(1,"half residual emitted a response");reset_all();repeat(10)begin @(negedge clk);if(ov)$fatal(1,"paired reset ghost");end
  // Abort each arithmetic datapath while in flight, then no ghost response.
  mv=1;op=3;a=17;b=123;repeat(2)@(negedge clk);reset_all();repeat(10)begin @(negedge clk);if(ov)$fatal(1,"math reset ghost");end
  fd=$fopen({root,"/iter.txt"},"r");
  while(!$feof(fd))begin
   rc=$fscanf(fd,"%h %h %h %h %h %h %d\n",mode,va,vb,ve,vr,verr,vl);
   if(rc==7)begin
    @(negedge clk);sqrt_mode=mode;ia=va;ib=vb;iv=1;ir=0;
    @(posedge clk);while(!iq)@(posedge clk);latency=1;
    @(negedge clk);iv=0;
    while(!iov)begin @(negedge clk);latency=latency+1;if(latency>65)$fatal(1,"iterative timeout");end
    if(iresult!==ve||irem!==vr||ie!==verr[0]||latency!=vl)$fatal(1,"iter vector %0d result=%h/%h rem=%h/%h L=%0d/%0d",iter_count,iresult,ve,irem,vr,latency,vl);
    repeat(7)begin @(negedge clk);if(!iov||iresult!==ve||irem!==vr)$fatal(1,"iterative hold");end
    ir=1;@(negedge clk);ir=0;iter_count=iter_count+1;
   end
  end
  for(k=0;k<2;k=k+1)begin @(negedge clk);sqrt_mode=k;ia=64'hffffffffffffffff;ib=17;iv=1;@(negedge clk);iv=0;repeat(12)@(negedge clk);reset_all();repeat(70)begin @(negedge clk);if(iov)$fatal(1,"iterative reset ghost");end end
  $display("PASS math=%0d iterative=%0d PE=64 SRAM=1 resets=5",taken,iter_count);$finish;
 end
endmodule
