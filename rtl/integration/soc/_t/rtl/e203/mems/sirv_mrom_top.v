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
