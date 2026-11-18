// Exact unsigned division / radix-four square root; held response interface.
// Optional four restoring steps for the two existing constant numerators,
// and two sqrt digits/clock. Defaults preserve the old latency modes.
module kwt_iterative #(parameter SHORT_CONST_DIV=0,parameter RADIX4_CONST=0,
 parameter RADIX16_CONST=0,parameter DOUBLE_SQRT=0)(input wire clk,rst_n,input wire req_valid,output wire req_ready,
 input wire sqrt_mode,input wire [63:0] a,b,output reg resp_valid,input wire resp_ready,
 output reg [63:0] result,remainder,output reg error);
 reg [1:0] state;reg [5:0] count;reg double_step,quad_step;
 reg [63:0] x,d,q;reg [31:0] root;reg [64:0] remd;reg [33:0] rems;
 wire [64:0] trial_d={remd[63:0],x[63]};
 wire ge_first=trial_d>={1'b0,d};
 wire [64:0] remainder_first=ge_first?trial_d-{1'b0,d}:trial_d;
 wire [64:0] trial_second={remainder_first[63:0],x[62]};
 wire ge_second=trial_second>={1'b0,d};
 wire [64:0] remainder_second=ge_second?trial_second-{1'b0,d}:trial_second;
 wire [64:0] trial_third={remainder_second[63:0],x[61]};
 wire ge_third=trial_third>={1'b0,d};
 wire [64:0] remainder_third=ge_third?trial_third-{1'b0,d}:trial_third;
 wire [64:0] trial_fourth={remainder_third[63:0],x[60]};
 wire ge_fourth=trial_fourth>={1'b0,d};
 wire [64:0] remainder_fourth=ge_fourth?trial_fourth-{1'b0,d}:trial_fourth;
 wire [63:0] quotient_next=quad_step?((q<<4)|{60'd0,ge_first,ge_second,ge_third,ge_fourth}):
  double_step?((q<<2)|{62'd0,ge_first,ge_second}):((q<<1)|ge_first);
 wire [64:0] remainder_next=quad_step?remainder_fourth:double_step?remainder_second:remainder_first;
 wire sqrt_start=req_valid&&req_ready&&sqrt_mode;
 wire [63:0] sqrt_x=sqrt_start?a:x;
 wire [31:0] sqrt_root=sqrt_start?32'd0:root;
 wire [33:0] sqrt_rem=sqrt_start?34'd0:rems;
 // Before the last digit, root<2^31 and rem<=2*root<2^32.
 // Thus a shifted trial uses at most34bits; final root32/rem33 suffice.
 wire [35:0] shifted_s1_full={sqrt_rem,sqrt_x[63:62]};
 wire [33:0] shifted_s1=shifted_s1_full[33:0];
 wire [33:0] trial_s1={sqrt_root,2'b01};
 wire gs1=shifted_s1>=trial_s1;
 wire [33:0] rem_s1=gs1?shifted_s1-trial_s1:shifted_s1;
 wire [32:0] root_s1={sqrt_root,1'b0}|{32'd0,gs1};
 wire [35:0] shifted_s2_full={rem_s1,sqrt_x[61:60]};
 wire [33:0] shifted_s2=shifted_s2_full[33:0];
 wire [33:0] trial_s2={root_s1[31:0],2'b01};
 wire gs2=shifted_s2>=trial_s2;
 wire [33:0] rem_s2=gs2?shifted_s2-trial_s2:shifted_s2;
 wire [32:0] root_s2={root_s1[31:0],1'b0}|{32'd0,gs2};
 wire [31:0] sqrt_next=DOUBLE_SQRT?root_s2[31:0]:root_s1[31:0];
 wire [33:0] sqrt_remainder_next=DOUBLE_SQRT?rem_s2:rem_s1;
 wire div40=SHORT_CONST_DIV&&(a==64'h10000000000);
 wire div47=SHORT_CONST_DIV&&(a==64'h800000000000);
 assign req_ready=rst_n&&state==0&&(!resp_valid||resp_ready);
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin state<=0;count<=0;double_step<=0;quad_step<=0;x<=0;d<=0;q<=0;root<=0;remd<=0;rems<=0;resp_valid<=0;result<=0;remainder<=0;error<=0;end
  else begin
   if(resp_valid&&resp_ready)resp_valid<=0;
   if(req_valid&&req_ready)begin
    error<=0;double_step<=0;quad_step<=0;
    if(sqrt_mode)begin
     state<=2;count<=DOUBLE_SQRT?15:31;x<=DOUBLE_SQRT?a<<4:a<<2;root<=sqrt_next;rems<=sqrt_remainder_next;
    end else if(b==0)begin result<=0;remainder<=0;error<=1;resp_valid<=1;end
    else if(div40||div47)begin
     state<=1;x<=0;d<=b;
     if(RADIX16_CONST)begin
      quad_step<=1;count<=div40?10:11;
      // Consume first1/4 leading bits (value1/8), leaving40/44 zero bits.
      if(div40)begin q<=b==1;remd<=b==1?65'd0:65'd1;end
      else case(b)
       1:begin q<=8;remd<=0;end
       2:begin q<=4;remd<=0;end
       3:begin q<=2;remd<=2;end
       4:begin q<=2;remd<=0;end
       default:if(b<=8)begin q<=1;remd<=65'd8-{1'b0,b};end else begin q<=0;remd<=8;end
      endcase
     end else if(RADIX4_CONST)begin
      double_step<=1;count<=div40?6'd20:6'd23;
      q<=div40?(b==1):(b==1?64'd2:b==2?64'd1:64'd0);
      remd<=div40?(b==1?65'd0:65'd1):(b<=2?65'd0:65'd2);
     end else begin count<=div40?6'd40:6'd47;q<=b==1;remd<=b==1?65'd0:65'd1;end
    end else begin
     state<=1;count<=63;x<=a<<1;d<=b;q<=({63'd0,a[63]}>=b);
     remd<=({63'd0,a[63]}>=b)?({64'd0,a[63]}-{1'b0,b}):{64'd0,a[63]};
    end
   end else if(state==1)begin
    x<=quad_step?x<<4:double_step?x<<2:x<<1;q<=quotient_next;remd<=remainder_next;
    if(count==1)begin state<=0;resp_valid<=1;result<=quotient_next;remainder<=remainder_next;end
    else count<=count-1;
   end else if(state==2)begin
    x<=DOUBLE_SQRT?x<<4:x<<2;root<=sqrt_next;rems<=sqrt_remainder_next;
    if(count==1)begin state<=0;resp_valid<=1;result<={32'd0,sqrt_next};remainder<={30'd0,sqrt_remainder_next};end
    else count<=count-1;
   end
  end
 end
 `ifdef KWT_SIM
 always @(posedge clk)if(rst_n)begin
  if(state==1&&(d==0||remd>={1'b0,d}))$fatal(1,"ITER restoring remainder invariant");
  if(sqrt_start||state==2)begin
   if(shifted_s1_full[35:34]!=0||root_s1[32])$fatal(1,"ITER sqrt first step width");
   if(DOUBLE_SQRT&&(shifted_s2_full[35:34]!=0||root_s2[32]))$fatal(1,"ITER sqrt second step width");
   if(state==2&&count==1&&sqrt_remainder_next[33])$fatal(1,"ITER sqrt final remainder width");
  end
 end
 `endif
endmodule
