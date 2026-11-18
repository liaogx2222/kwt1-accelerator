// One elastic stage. Symmetric signed64 domain, optional symmetric saturation.
module rne_pipe #(parameter TAG_W=16)(
 input logic clk,rst_n,req_valid,output logic req_ready,
 input logic [63:0] req_a,input logic signed [7:0] req_shift,
 input logic [5:0] req_sat_bits,input logic req_error,input logic [TAG_W-1:0] req_tag,
 output logic resp_valid,input logic resp_ready,output logic [63:0] resp_result,
 output logic resp_error,output logic [TAG_W-1:0] resp_tag
);
 logic v,err;logic [63:0] result,mag,q,remn,half,maskn,qmax;
 logic [127:0] wide;integer sh;logic bad;logic [63:0] rounded;
 assign req_ready=rst_n&&(!v||resp_ready);assign resp_valid=rst_n&&v;
 assign resp_result=result;assign resp_error=err;
 always @* begin
  mag=req_a[63] ? (~req_a+64'd1):req_a;q=0;remn=0;half=0;maskn=0;wide=0;
  sh=$signed(req_shift);bad=req_error||(req_a==64'h8000000000000000);
  if(sh<0) begin
   wide={64'd0,mag}<<(-sh);
   if(mag!=0 && ((-sh)>127 || |wide[127:63]))bad=1;
   q=wide[63:0];
  end else if(sh==0) q=mag;
  else if(sh<64) begin
   maskn=(64'd1<<sh)-1;half=64'd1<<(sh-1);remn=mag&maskn;q=mag>>sh;
   if(remn>half || (remn==half && q[0]))q=q+1;
  end
  qmax=64'h7fffffffffffffff;
  if(req_sat_bits==8)qmax=127;
  else if(req_sat_bits==16)qmax=32767;
  else if(req_sat_bits!=0)bad=1;
  if(q>qmax && req_sat_bits!=0)q=qmax;
  rounded=bad ? 64'd0 : (req_a[63] ? (~q+64'd1):q);
 end
 always_ff @(posedge clk or negedge rst_n) begin
  if(!rst_n)begin v<=0;result<=0;err<=0;resp_tag<=0;end
  else if(req_ready)begin
   v<=req_valid;if(req_valid)begin result<=rounded;err<=bad;resp_tag<=req_tag;end
  end
 end
endmodule
