// Verification model of the EXTERNAL macro. No reset or answer initialization.
module kwt_tech_sram_4096x16(input wire clk,en,we,input wire [11:0] addr,input wire [15:0] wdata,output reg [15:0] rdata);
 reg [15:0] mem[0:4095];
 integer i;
 initial begin rdata=16'h6d39;for(i=0;i<4096;i=i+1)mem[i]=16'h6d39^i;end
 always @(posedge clk)if(en)begin
  if(we)mem[addr]<=wdata;else rdata<=mem[addr];
 end
endmodule
