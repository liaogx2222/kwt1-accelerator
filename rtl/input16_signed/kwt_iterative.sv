// Experimental S16-first-input complete 8x8 baseline. Not the 16x16 model.
// Dedicated unsigned divider / radix-four sqrt. First step at request capture.
// Valid operations L=64/32, same-op minimum II=64/32. Held response.
module kwt_iterative(input wire clk,rst_n,input wire req_valid,output wire req_ready,
 input wire sqrt_mode,input wire [63:0] a,b,output reg resp_valid,input wire resp_ready,
 output reg [63:0] result,remainder,output reg error);
 reg [1:0] state;reg [5:0] count;
 reg [63:0] x,d,q,root;reg [64:0] remd;reg [65:0] rems;
 wire [64:0] trial_d={remd[63:0],x[63]};
 wire [65:0] shifted_s=(rems<<2)|{64'd0,x[63:62]};
 wire [65:0] trial_s=({2'd0,root}<<2)|66'd1;
 assign req_ready=rst_n&&state==0&&(!resp_valid||resp_ready);
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin state<=0;count<=0;x<=0;d<=0;q<=0;root<=0;remd<=0;rems<=0;resp_valid<=0;result<=0;remainder<=0;error<=0;end
  else begin
   if(resp_valid&&resp_ready)resp_valid<=0;
   if(req_valid&&req_ready)begin
    error<=0;
    if(sqrt_mode)begin
     state<=2;count<=31;x<=a<<2;root<=a[63:62]>=1;
     rems<=a[63:62]>=1?{64'd0,a[63:62]}-66'd1:{64'd0,a[63:62]};
    end else if(b==0)begin result<=0;remainder<=0;error<=1;resp_valid<=1;end
    else begin
     state<=1;count<=63;x<=a<<1;d<=b;q<=({63'd0,a[63]}>=b);
     remd<=({63'd0,a[63]}>=b)?({64'd0,a[63]}-{1'b0,b}):{64'd0,a[63]};
    end
   end else if(state==1)begin
    x<=x<<1;q<=(q<<1)|(trial_d>={1'b0,d});remd<=trial_d>={1'b0,d}?trial_d-{1'b0,d}:trial_d;
    if(count==1)begin state<=0;resp_valid<=1;result<=(q<<1)|(trial_d>={1'b0,d});remainder<=trial_d>={1'b0,d}?trial_d-{1'b0,d}:trial_d;end
    else count<=count-1;
   end else if(state==2)begin
    x<=x<<2;root<=(root<<1)|(shifted_s>=trial_s);rems<=shifted_s>=trial_s?shifted_s-trial_s:shifted_s;
    if(count==1)begin state<=0;resp_valid<=1;result<=(root<<1)|(shifted_s>=trial_s);remainder<=shifted_s>=trial_s?shifted_s-trial_s:shifted_s;end
    else count<=count-1;
   end
  end
 end
endmodule
