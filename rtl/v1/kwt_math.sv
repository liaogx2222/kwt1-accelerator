// One physical mul_pipe + one physical rne_pipe. Controller uses homogeneous
// request groups and drains responses before changing mode (raw / RQ / RNE).
// op0 signed mul,1 unsigned mul,2 direct signed RNE,3 signed RQ.
module kwt_math(input wire clk,rst_n,input wire req_valid,output wire req_ready,
 input wire [1:0] op,input wire [63:0] a,b,input wire signed [7:0] shift,
 input wire [5:0] sat,input wire [7:0] tag,
 output wire resp_valid,input wire resp_ready,output wire [63:0] result,
 output wire error,output wire [7:0] result_tag);
 wire mv,mr,me,nv,nr,ne;wire [63:0] mp,np;wire [22:0] mt;wire [7:0] nt;
 wire use_rne=mt[22];
 wire direct_rne=req_valid&&op==2&&!mv;
 assign req_ready=op==2?(nr&&!mv):mr;
 mul_pipe #(.TAG_W(23)) mul(clk,rst_n,req_valid&&op!=2,mr,op!=1,a,b,{op==3,tag,sat,shift},mv,
  use_rne?(nr&&!direct_rne):(resp_ready&&!nv),mp,me,mt);
 rne_pipe #(.TAG_W(8)) rne(clk,rst_n,direct_rne||(mv&&use_rne),nr,
  direct_rne?a:mp,direct_rne?shift:$signed(mt[7:0]),direct_rne?sat:mt[13:8],
  direct_rne?1'b0:me,direct_rne?tag:mt[21:14],nv,resp_ready,np,ne,nt);
 assign resp_valid=nv||(mv&&!use_rne);
 assign result=nv?np:mp;assign error=nv?ne:me;assign result_tag=nv?nt:mt[21:14];
endmodule
