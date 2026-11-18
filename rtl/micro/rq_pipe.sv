// Metadata travels in the same elastic slots as products: no uncharged FIFO.
module rq_pipe #(parameter TAG_W=16)(
 input logic clk,rst_n,req_valid,output logic req_ready,
 input logic req_signed,input logic [63:0] req_a,req_b,
 input logic signed [7:0] req_shift,input logic [5:0] req_sat_bits,
 input logic [TAG_W-1:0] req_tag,
 output logic resp_valid,input logic resp_ready,output logic [63:0] resp_result,
 output logic resp_error,output logic [TAG_W-1:0] resp_tag
);
 wire mv,mr,me;wire [63:0] product;wire [TAG_W+13:0] metadata;
 mul_pipe #(.TAG_W(TAG_W+14)) mul(clk,rst_n,req_valid,req_ready,req_signed,req_a,req_b,
   {req_tag,req_sat_bits,req_shift},mv,mr,product,me,metadata);
 rne_pipe #(.TAG_W(TAG_W)) rne(clk,rst_n,mv,mr,product,$signed(metadata[7:0]),metadata[13:8],me,
   metadata[TAG_W+13:14],resp_valid,resp_ready,resp_result,resp_error,resp_tag);
endmodule
