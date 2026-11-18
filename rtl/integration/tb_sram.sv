module tb_sram;
 reg clk=0;always #5 clk=~clk;reg en=0,we=0;reg [11:0] addr=0;reg [15:0] wdata=0;wire [15:0] rdata;
 kwt_sram_sp dut(clk,en,we,addr,wdata,rdata);
 integer i;reg [15:0] held;
 task write_word(input [11:0] a,input [15:0] v);
  begin @(negedge clk);en=1;we=1;addr=a;wdata=v;@(negedge clk);en=0;we=0;end
 endtask
 task read_word(input [11:0] a,input [15:0] v);
  begin @(negedge clk);held=rdata;en=1;we=0;addr=a;#1;if(rdata!==held)$fatal(1,"asynchronous read");
   @(negedge clk);en=0;if(rdata!==v)$fatal(1,"synchronous read mismatch addr=%d",a);
  end
 endtask
 initial begin
  write_word(0,16'h1234);write_word(4095,16'hcafe);read_word(0,16'h1234);
  held=rdata;write_word(4095,16'h5678);if(rdata!==held)$fatal(1,"write changed read output");
  for(i=0;i<32;i=i+1)begin @(negedge clk);addr=i;wdata=i;we=1;if(rdata!==held)$fatal(1,"disabled output changed");end
  we=0;read_word(4095,16'h5678);read_word(0,16'h1234);
  // Macro has no reset input: a controller reset must leave its storage intact.
  en=0;repeat(7)@(negedge clk);read_word(4095,16'h5678);
  $display("PASS SRAM synchronous/hold/write/no-reset boundary=0,4095");$finish;
 end
 initial begin #10000;$fatal(1,"SRAM watchdog");end
endmodule
