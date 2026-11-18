// Experimental S16-first-input complete 8x8 baseline. Not the 16x16 model.
// Abstract technology boundary for generic synthesis only; no functional model.
(* blackbox *) module kwt_tech_sram_4096x16(input wire clk,en,we,input wire [11:0] addr,input wire [15:0] wdata,output wire [15:0] rdata);
endmodule
