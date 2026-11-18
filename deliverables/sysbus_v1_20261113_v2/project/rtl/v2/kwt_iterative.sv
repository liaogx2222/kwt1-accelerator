// Dedicated unsigned divider / radix-four sqrt. First step at request capture.
// Default valid operations L=64/32, same-op minimum II=64/32. Held response.
// Optional exact 2^40/2^47 numerator specialization: skip only leading zeros.
module kwt_iterative #(parameter SHORT_CONST_DIV=0,parameter RADIX4_CONST=0)(input wire clk,rst_n,input wire req_valid,output wire req_ready,
 input wire sqrt_mode,input wire [63:0] a,b,output reg resp_valid,input wire resp_ready,
 output reg [63:0] result,remainder,output reg error);
 reg [1:0] state;reg [5:0] count;reg double_step;
 reg [63:0] x,d,q,root;reg [64:0] remd;reg [65:0] rems;
 wire [64:0] trial_d={remd[63:0],x[63]};
 wire ge_first=trial_d>={1'b0,d};
 wire [64:0] remainder_first=ge_first?trial_d-{1'b0,d}:trial_d;
 wire [64:0] trial_second={remainder_first[63:0],x[62]};
 wire ge_second=trial_second>={1'b0,d};
 wire [64:0] remainder_second=ge_second?trial_second-{1'b0,d}:trial_second;
 wire [63:0] quotient_next=double_step?((q<<2)|{62'd0,ge_first,ge_second}):((q<<1)|ge_first);
 wire [64:0] remainder_next=double_step?remainder_second:remainder_first;
 wire [65:0] shifted_s=(rems<<2)|{64'd0,x[63:62]};
 wire [65:0] trial_s=({2'd0,root}<<2)|66'd1;
 wire div40=SHORT_CONST_DIV&&(a==64'h10000000000);
 wire div47=SHORT_CONST_DIV&&(a==64'h800000000000);
 assign req_ready=rst_n&&state==0&&(!resp_valid||resp_ready);
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin state<=0;count<=0;double_step<=0;x<=0;d<=0;q<=0;root<=0;remd<=0;rems<=0;resp_valid<=0;result<=0;remainder<=0;error<=0;end
  else begin
   if(resp_valid&&resp_ready)resp_valid<=0;
   if(req_valid&&req_ready)begin
    error<=0;double_step<=0;
    if(sqrt_mode)begin
     state<=2;count<=31;x<=a<<2;root<=a[63:62]>=1;
     rems<=a[63:62]>=1?{64'd0,a[63:62]}-66'd1:{64'd0,a[63:62]};
    end else if(b==0)begin result<=0;remainder<=0;error<=1;resp_valid<=1;end
    else if(div40||div47)begin
     // After all leading zeros and the first one have been consumed, the
     // unconsumed dividend is zero. Continue the original exact recurrence
     // for the remaining 40/47 bits with the actual captured divisor.
     state<=1;double_step<=RADIX4_CONST;x<=0;d<=b;
     if(RADIX4_CONST)begin
      // Consume 1 bit for 2^40, 2 bits for 2^47, leaving an even number
      // of zero bits. Every later cycle performs TWO exact restoring steps.
      count<=div40?6'd20:6'd23;
      q<=div40?(b==1):(b==1?64'd2:b==2?64'd1:64'd0);
      remd<=div40?(b==1?65'd0:65'd1):(b<=2?65'd0:65'd2);
     end else begin count<=div40?6'd40:6'd47;q<=b==1;remd<=b==1?65'd0:65'd1;end
    end else begin
     state<=1;count<=63;x<=a<<1;d<=b;q<=({63'd0,a[63]}>=b);
     remd<=({63'd0,a[63]}>=b)?({64'd0,a[63]}-{1'b0,b}):{64'd0,a[63]};
    end
   end else if(state==1)begin
    x<=double_step?x<<2:x<<1;q<=quotient_next;remd<=remainder_next;
    if(count==1)begin state<=0;resp_valid<=1;result<=quotient_next;remainder<=remainder_next;end
    else count<=count-1;
   end else if(state==2)begin
    x<=x<<2;root<=(root<<1)|(shifted_s>=trial_s);rems<=shifted_s>=trial_s?shifted_s-trial_s:shifted_s;
    if(count==1)begin state<=0;resp_valid<=1;result<=(root<<1)|(shifted_s>=trial_s);remainder<=shifted_s>=trial_s?shifted_s-trial_s:shifted_s;end
    else count<=count-1;
   end
  end
 end
endmodule
