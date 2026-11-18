// Elastic 32x32 -> 64, three register stages, initiation interval one.
// Stage 0: four 16x16 partial products; 1: combine; 2: signed correction.
module mul_pipe #(parameter TAG_W=16)(
 input logic clk,rst_n,req_valid,output logic req_ready,
 input logic req_signed,input logic [63:0] req_a,req_b,
 input logic [TAG_W-1:0] req_tag,
 output logic resp_valid,input logic resp_ready,
 output logic [63:0] resp_result,output logic resp_error,
 output logic [TAG_W-1:0] resp_tag
);
 logic [2:0] v,r;logic [31:0] p00,p01,p10,p11,ma,mb;
 logic neg0,neg1,err0,err1,err2;logic [63:0] combined,result;
 logic [TAG_W-1:0] tag0,tag1,tag2;
 assign r[2]=!v[2]||resp_ready;assign r[1]=!v[1]||r[2];assign r[0]=!v[0]||r[1];
 assign req_ready=rst_n&&r[0];assign resp_valid=rst_n&&v[2];
 assign resp_result=result;assign resp_error=err2;assign resp_tag=tag2;
 always @* begin
  ma=req_signed&&req_a[31] ? (~req_a[31:0]+32'd1):req_a[31:0];
  mb=req_signed&&req_b[31] ? (~req_b[31:0]+32'd1):req_b[31:0];
 end
 always_ff @(posedge clk or negedge rst_n) begin
  if(!rst_n) begin
   v<=0;p00<=0;p01<=0;p10<=0;p11<=0;neg0<=0;neg1<=0;
   err0<=0;err1<=0;err2<=0;combined<=0;result<=0;tag0<=0;tag1<=0;tag2<=0;
  end else begin
   if(r[0]) begin
    v[0]<=req_valid;
    if(req_valid) begin
     p00<=ma[15:0]*mb[15:0];p01<=ma[15:0]*mb[31:16];
     p10<=ma[31:16]*mb[15:0];p11<=ma[31:16]*mb[31:16];
     neg0<=req_signed&&(req_a[31]^req_b[31]);tag0<=req_tag;
     err0<=req_signed ? ((req_a[63:32]!={32{req_a[31]}})||(req_b[63:32]!={32{req_b[31]}})) : (|req_a[63:32]|| |req_b[63:32]);
    end
   end
   if(r[1]) begin
    v[1]<=v[0];if(v[0]) begin
     combined<={32'b0,p00}+({32'b0,p01}<<16)+({32'b0,p10}<<16)+({32'b0,p11}<<32);
     neg1<=neg0;err1<=err0;tag1<=tag0;
    end
   end
   if(r[2]) begin
    v[2]<=v[1];if(v[1]) begin
     result<=err1 ? 64'd0 : (neg1 ? (~combined+64'd1):combined);err2<=err1;tag2<=tag1;
    end
   end
  end
 end
endmodule
