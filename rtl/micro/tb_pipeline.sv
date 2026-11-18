module tb_pipeline;
 reg clk=0;always #5 clk=~clk;
 reg rst_n,valid,sgn,sink;reg [63:0] a,b;reg signed [7:0] shift;
 reg [5:0] sat;reg [15:0] tag;wire [2:0] rr,vv,ee;
 wire [63:0] q[0:2];wire [15:0] ot[0:2];integer mode;
 mul_pipe mul(clk,rst_n,valid,rr[0],sgn,a,b,tag,vv[0],sink,q[0],ee[0],ot[0]);
 rne_pipe rne(clk,rst_n,valid,rr[1],a,shift,sat,1'b0,tag,vv[1],sink,q[1],ee[1],ot[1]);
 rq_pipe rq(clk,rst_n,valid,rr[2],sgn,a,b,shift,sat,tag,vv[2],sink,q[2],ee[2],ot[2]);
 integer fd,n,row,er,ev,error_exp,tag_exp,rst_i,vi,si,ri,sh_i,sat_i,tag_i;
 reg [63:0] expected;reg [2047:0] filename;
 initial begin
  rst_n=0;valid=0;sink=0;sgn=0;a=0;b=0;shift=0;sat=0;tag=0;row=0;
  if(!$value$plusargs("vectors=%s",filename))$fatal(1,"missing vectors");
  if(!$value$plusargs("mode=%d",mode))$fatal(1,"missing mode");
  fd=$fopen(filename,"r");if(fd==0)$fatal(1,"cannot open vectors");
  while(!$feof(fd))begin
   @(negedge clk);
   n=$fscanf(fd,"%d %d %d %h %h %d %d %d %d %d %d %h %d %d\n",rst_i,vi,si,a,b,sh_i,sat_i,tag_i,ri,er,ev,expected,error_exp,tag_exp);
   if(n==14)begin
    rst_n=rst_i;valid=vi;sgn=si;shift=sh_i;sat=sat_i;tag=tag_i;sink=ri;
    #1;
    if(rr[mode]!==er[0]||vv[mode]!==ev[0])$fatal(1,"handshake mode=%0d cycle=%0d ready=%b/%b valid=%b/%b",mode,row,rr[mode],er[0],vv[mode],ev[0]);
    if(ev && (q[mode]!==expected||ee[mode]!==error_exp[0]||ot[mode]!==tag_exp[15:0]))
     $fatal(1,"result mode=%0d cycle=%0d result=%h/%h err=%b/%b tag=%d/%d",mode,row,q[mode],expected,ee[mode],error_exp[0],ot[mode],tag_exp);
    row=row+1;
   end
  end
  $display("PASS mode=%0d cycles=%0d",mode,row);$finish;
 end
 initial begin #2000000;$fatal(1,"watchdog");end
endmodule
