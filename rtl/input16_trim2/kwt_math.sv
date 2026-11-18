// Experimental S16-first-input complete 8x8 baseline. Not the 16x16 model.
// One shared wide multiplier and RNE. Drained homogeneous groups.
// op4: paired signed products (tag bit0 A/B), S64 add, then ONE RNE.
module kwt_math(input wire clk,rst_n,input wire req_valid,output wire req_ready,
 input wire [2:0] op,input wire [63:0] a,b,input wire signed [7:0] shift,
 input wire [5:0] sat,input wire [7:0] tag,
 output wire resp_valid,input wire resp_ready,output wire [63:0] result,
 output wire error,output wire [7:0] result_tag);
 wire mv,mr,me,nv,nr,ne;wire [63:0] mp,np;wire [24:0] mt;wire [7:0] nt;
 wire [2:0] mode=mt[24:22];wire [7:0] out_tag=mt[21:14];
 wire paired=mode==4,first=paired&&!out_tag[0];
 wire use_rne=mode==3||(paired&&out_tag[0]);
 reg [63:0] partial;reg partial_error;
 wire direct_rne=req_valid&&op==2&&!mv;
 assign req_ready=op==2?(nr&&!mv):mr;
 wire mul_take=mv&&(first?1'b1:use_rne?(nr&&!direct_rne):(resp_ready&&!nv));
 mul_pipe #(.TAG_W(25)) mul(clk,rst_n,req_valid&&op!=2,mr,op!=1,a,b,{op,tag,sat,shift},mv,
  first?1'b1:use_rne?(nr&&!direct_rne):(resp_ready&&!nv),mp,me,mt);
 rne_pipe #(.TAG_W(8)) rne(clk,rst_n,direct_rne||(mv&&use_rne),nr,
  direct_rne?a:paired?(mp+partial):mp,direct_rne?shift:$signed(mt[7:0]),direct_rne?sat:mt[13:8],
  direct_rne?1'b0:(me||(paired&&partial_error)),direct_rne?tag:paired?{1'b0,out_tag[7:1]}:out_tag,nv,resp_ready,np,ne,nt);
 assign resp_valid=nv||(mv&&!use_rne&&!first);
 assign result=nv?np:mp;assign error=nv?ne:me;assign result_tag=nv?nt:out_tag;
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin partial<=0;partial_error<=0;end
  else if(mul_take&&first)begin partial<=mp;partial_error<=me;end
 end
endmodule
