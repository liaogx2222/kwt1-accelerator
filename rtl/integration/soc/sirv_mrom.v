// not instantiated in this build; see sirv_mrom_top.v
`timescale 1ns/1ps
module sirv_mrom #(parameter AW = 12, parameter DW = 32, parameter DP = 1024)(
  input [AW-1:2] rom_addr, output [DW-1:0] rom_dout);
  assign rom_dout = 32'h0000_0013;
endmodule
