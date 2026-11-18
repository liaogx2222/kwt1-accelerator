// Parameterized signed32 output-stationary PEs, default8x16. Qualified operands are shared by row
// and column, avoiding work in padded rows/columns and idle array cycles.
module kwt_mac_array #(parameter ROWS=8,COLS=16)(input wire clk,rst_n,input wire load,en,unsigned_a,
 input wire [ROWS-1:0] row_mask,input wire [COLS-1:0] col_mask,
 input wire [ROWS*16-1:0] a,input wire [COLS*8-1:0] b,
 input wire [COLS*32-1:0] bias,output wire [ROWS*COLS*32-1:0] accumulators);
 reg signed [31:0] acc[0:ROWS*COLS-1];genvar r,c;
 generate for(r=0;r<ROWS;r=r+1)begin:rows
  wire signed [16:0] av=!(en&&row_mask[r])?17'sd0:
   unsigned_a?$signed({1'b0,a[r*16+:16]}):$signed({a[r*16+15],a[r*16+:16]});
  for(c=0;c<COLS;c=c+1)begin:cols
   wire signed [7:0] bv=(en&&col_mask[c])?$signed(b[c*8+:8]):8'sd0;
   wire signed [24:0] product=av*bv;
   assign accumulators[(r*COLS+c)*32+:32]=acc[r*COLS+c];
   always @(posedge clk or negedge rst_n)begin
    if(!rst_n)acc[r*COLS+c]<=0;
    else if(load)acc[r*COLS+c]<=$signed(bias[c*32+:32]);
    else if(en&&row_mask[r]&&col_mask[c])acc[r*COLS+c]<=acc[r*COLS+c]+product;
   end
  end
 end endgenerate
endmodule
