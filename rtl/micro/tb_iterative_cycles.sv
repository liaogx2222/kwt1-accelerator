module tb_iterative_cycles;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,valid=0,ready=1;
 reg [2:0] op=0;reg [63:0] a=0,b=0;wire req_ready,resp_valid,error;wire [63:0] result,remainder;
 wide_arith dut(clk,rst_n,valid,req_ready,op,a,b,8'sd0,resp_valid,ready,result,remainder,error);
 integer ops[0:2047],lat[0:2047],err[0:2047],accepted_at[0:2047];
 reg [63:0] aa[0:2047],bb[0:2047],qq[0:2047],remn[0:2047];
 reg [4095:0] filename;integer fd,n,total=0,send=0,receive=0,cycle=0,i,seen=0,holds=0;
 initial begin
  if(!$value$plusargs("vectors=%s",filename))$fatal(1,"vectors");fd=$fopen(filename,"r");
  while(!$feof(fd))begin
   n=$fscanf(fd,"%d %h %h %h %h %d %d\n",ops[total],aa[total],bb[total],qq[total],remn[total],err[total],lat[total]);
   if(n==7)total=total+1;
  end
  repeat(2)@(negedge clk);rst_n=1;
  while(receive<total)begin
   @(negedge clk);cycle=cycle+1;
   valid=send<total;op=ops[send];a=aa[send];b=bb[send];
   // First 16 responses no stall: exercise minimum initiation interval.
   ready=receive<16?1:(cycle%11!=0&&cycle%11!=1&&cycle%11!=2);
   @(posedge clk);
   if(valid&&req_ready)begin accepted_at[send]=cycle;send=send+1;end
   if(resp_valid)begin
    if(!seen)begin
     if(cycle-accepted_at[receive]!=lat[receive])$fatal(1,"latency op=%0d got=%0d expected=%0d",ops[receive],cycle-accepted_at[receive],lat[receive]);
     seen=1;
    end
    if(result!==qq[receive]||remainder!==remn[receive]||error!==err[receive][0])$fatal(1,"iterative value");
    if(ready)begin receive=receive+1;seen=0;end else holds=holds+1;
   end
   if(cycle>150000)$fatal(1,"watchdog");
  end
  $display("PASS iterative vectors=%0d cycles=%0d holds=%0d div_L64_II64 sqrt_L32_II32",total,cycle,holds);$finish;
 end
endmodule
