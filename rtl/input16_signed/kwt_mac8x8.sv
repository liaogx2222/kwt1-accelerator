// Experimental S16-first-input complete 8x8 baseline. Not the 16x16 model.
// 64 signed32 output-stationary PEs, one shared operand per row / column.
module kwt_mac8x8(input wire clk,rst_n,input wire load,en,unsigned_a,
 input wire [7:0] row_mask,col_mask,input wire [127:0] a,input wire [63:0] b,
 input wire [255:0] bias,output wire [2047:0] accumulators);
 reg signed [31:0] acc[0:63];genvar r,c;
 generate for(r=0;r<8;r=r+1)begin:rows for(c=0;c<8;c=c+1)begin:cols
  wire signed [16:0] av=unsigned_a?$signed({1'b0,a[r*16+:16]}):$signed({a[r*16+15],a[r*16+:16]});
  wire signed [7:0] bv=$signed(b[c*8+:8]);
  wire signed [24:0] product=av*bv;
  assign accumulators[(r*8+c)*32+:32]=acc[r*8+c];
  always @(posedge clk or negedge rst_n)begin
   if(!rst_n)acc[r*8+c]<=0;
   else if(load)acc[r*8+c]<=$signed(bias[c*32+:32]);
   else if(en&&row_mask[r]&&col_mask[c])acc[r*8+c]<=acc[r*8+c]+product;
  end
 end end endgenerate
endmodule
