// sirv_mrom_top.v -- KWT-1 boot ROM + ICB wrapper (self contained)
// Replaces the vendor sirv_mrom_top + ROMI32X32 pair. Module name and port
// list are the vendor ones, so e203_subsys_mems.v needs no edit.
// Boot program: read accel ID @0x48 and STATUS @0x04 through sysper, store
// them to DTCM[0..2] @0x90000000, then spin. Word i lives at 0x1000 + 4*i.
`timescale 1ns/1ps
module sirv_mrom_top #(
    parameter AW = 12,
    parameter DW = 32,
    parameter DP = 1024
)(
  input  rom_icb_cmd_valid,
  output rom_icb_cmd_ready,
  input  [AW-1:0] rom_icb_cmd_addr,
  input  rom_icb_cmd_read,
  output rom_icb_rsp_valid,
  input  rom_icb_rsp_ready,
  output rom_icb_rsp_err,
  output [DW-1:0] rom_icb_rsp_rdata,
  input  clk,
  input  rst_n
  );
  wire [AW-3:0] idx = rom_icb_cmd_addr[AW-1:2];
  reg  [DW-1:0] dout_r;
  always @(*) begin
    case (idx)
      0 : dout_r = 32'h400002B7;  // lui  t0,0x40000
      1 : dout_r = 32'h0482A303;  // lw   t1,0x48(t0)
      2 : dout_r = 32'h900003B7;  // lui  t2,0x90000
      3 : dout_r = 32'h0063A023;  // sw   t1,0(t2)
      4 : dout_r = 32'h0042AE03;  // lw   t3,4(t0)
      5 : dout_r = 32'h01C3A223;  // sw   t3,4(t2)
      6 : dout_r = 32'h5A500E93;  // addi t4,x0,0x5A5
      7 : dout_r = 32'h01D3A423;  // sw   t4,8(t2)
      8 : dout_r = 32'h0000006F;  // jal  x0,0
      default : dout_r = 32'h00000013;  // nop
    endcase
  end
  assign rom_icb_rsp_valid = rom_icb_cmd_valid;
  assign rom_icb_cmd_ready = rom_icb_rsp_ready;
  assign rom_icb_rsp_err   = ~rom_icb_cmd_read;
  assign rom_icb_rsp_rdata = dout_r;
`ifdef KWT_SIM
  integer n = 0;
  always @(posedge clk) begin
    if (rom_icb_cmd_valid && rom_icb_cmd_ready && (n < 8)) begin
      $display("[ROM %0t] idx=%0d rdata=%08h", $time, idx, dout_r);
      n = n + 1;
    end
  end
`endif
endmodule
