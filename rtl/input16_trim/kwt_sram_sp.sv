// 2048 legal words implemented by two allowed 1024x16 1RW macros.
// addr[11] must be zero whenever enabled. Selection follows accepted reads;
// writes and idle cycles leave the last read data unchanged.
module kwt_small_sp(input wire clk,en,we,input wire [9:0] addr,
 input wire [15:0] wdata,output reg [15:0] rdata);
`ifdef KWT_TECH_SRAM
 kwt_tech_sram_1024x16 macro_cell(clk,en,we,addr,wdata,rdata);
`else
 reg [15:0] mem[0:1023];
`ifdef KWT_SIM
 integer i;initial begin rdata=16'ha5a5;for(i=0;i<1024;i=i+1)mem[i]=16'ha5a5;end
`endif
 always @(posedge clk)if(en)begin
  if(we)mem[addr]<=wdata;else rdata<=mem[addr];
 end
`endif
endmodule

`ifdef KWT_TECH_SRAM
(* blackbox *) module kwt_tech_sram_1024x16(input wire clk,en,we,
 input wire [9:0] addr,input wire [15:0] wdata,output wire [15:0] rdata);
endmodule
`endif

module kwt_weight_2048x16(input wire clk,en,we,input wire [11:0] addr,
 input wire [15:0] wdata,output wire [15:0] rdata);
 wire [15:0] q0,q1;reg selected;
 kwt_small_sp low(clk,en&&!addr[10],we,addr[9:0],wdata,q0);
 kwt_small_sp high(clk,en&&addr[10],we,addr[9:0],wdata,q1);
 always @(posedge clk)if(en&&!we)selected<=addr[10];
 assign rdata=selected?q1:q0;
`ifdef KWT_SIM
 initial selected=0;
 always @(posedge clk)if(en&&addr[11])$fatal(1,"weight tail address beyond legal 2048 words");
`endif
endmodule

// Experimental S16-first-input complete 8x8 baseline. Not the 16x16 model.
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
  if(g<8&&g%2==1)begin:small
   kwt_weight_2048x16 ram(clk,en[g],we[g],addr[g*12+:12],wdata[g*16+:16],rdata[g*16+:16]);
  end else begin:large
   kwt_sram_sp ram(clk,en[g],we[g],addr[g*12+:12],wdata[g*16+:16],rdata[g*16+:16]);
  end
 end endgenerate
endmodule
