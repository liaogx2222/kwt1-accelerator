// Technology-independent 4096x16 single-port SRAM boundary.
// Read sampled on enabled edge; output holds until the next read. No RAM reset.
module kwt_sram_sp(input wire clk,input wire en,input wire we,
 input wire [11:0] addr,input wire [15:0] wdata,output reg [15:0] rdata);
`ifdef KWT_TECH_SRAM
 // Supply this cell wrapper for the designated technology (same contract).
 kwt_tech_sram_4096x16 macro_cell(clk,en,we,addr,wdata,rdata);
`else
 reg [15:0] mem[0:4095];
`ifdef KWT_SIM
 integer i;initial begin rdata=16'ha5a5;for(i=0;i<4096;i=i+1)mem[i]=16'ha5a5;end
`endif
 always @(posedge clk)if(en)begin
  if(we)mem[addr]<=wdata;else rdata<=mem[addr];
 end
`endif
endmodule

module kwt_banks(input wire clk,input wire [19:0] en,we,
 input wire [239:0] addr,input wire [319:0] wdata,output wire [319:0] rdata);
 genvar g;generate for(g=0;g<20;g=g+1)begin:bank
  kwt_sram_sp ram(clk,en[g],we[g],addr[g*12+:12],wdata[g*16+:16],rdata[g*16+:16]);
 end endgenerate
endmodule
