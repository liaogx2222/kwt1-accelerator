echo '// sirv_mrom_top.v -- KWT-1 boot ROM + ICB wrapper (self contained)' > _t/rtl/e203/mems/sirv_mrom_top.v
echo '// Replaces the vendor sirv_mrom_top + ROMI32X32 pair. Module name and port' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '// list are the vendor ones, so e203_subsys_mems.v needs no edit.' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '// Boot program: read accel ID @0x48 and STATUS @0x04 through sysper, store' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '// them to DTCM[0..2] @0x90000000, then spin. Word i lives at 0x1000 + 4*i.' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '`timescale 1ns/1ps' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo 'module sirv_mrom_top #(' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '    parameter AW = 12,' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '    parameter DW = 32,' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '    parameter DP = 1024' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo ')(' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  input  rom_icb_cmd_valid,' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  output rom_icb_cmd_ready,' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  input  [AW-1:0] rom_icb_cmd_addr,' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  input  rom_icb_cmd_read,' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  output rom_icb_rsp_valid,' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  input  rom_icb_rsp_ready,' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  output rom_icb_rsp_err,' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  output [DW-1:0] rom_icb_rsp_rdata,' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  input  clk,' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  input  rst_n' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  );' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  wire [AW-3:0] idx = rom_icb_cmd_addr[AW-1:2];' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  reg  [DW-1:0] dout_r;' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  always @(*) begin' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '    case (idx)' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      0 : dout_r = 32'h400002B7;  // lui  t0,0x40000' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      1 : dout_r = 32'h0482A303;  // lw   t1,0x48(t0)' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      2 : dout_r = 32'h900003B7;  // lui  t2,0x90000' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      3 : dout_r = 32'h0063A023;  // sw   t1,0(t2)' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      4 : dout_r = 32'h0042AE03;  // lw   t3,4(t0)' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      5 : dout_r = 32'h01C3A223;  // sw   t3,4(t2)' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      6 : dout_r = 32'h5A500E93;  // addi t4,x0,0x5A5' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      7 : dout_r = 32'h01D3A423;  // sw   t4,8(t2)' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      8 : dout_r = 32'h0000006F;  // jal  x0,0' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      default : dout_r = 32'h00000013;  // nop' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '    endcase' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  end' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  assign rom_icb_rsp_valid = rom_icb_cmd_valid;' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  assign rom_icb_cmd_ready = rom_icb_rsp_ready;' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  assign rom_icb_rsp_err   = ~rom_icb_cmd_read;' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  assign rom_icb_rsp_rdata = dout_r;' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '`ifdef KWT_SIM' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  integer n = 0;' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  always @(posedge clk) begin' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '    if (rom_icb_cmd_valid && rom_icb_cmd_ready && (n < 8)) begin' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      $display("[ROM %0t] idx=%0d rdata=%08h", $time, idx, dout_r);' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '      n = n + 1;' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '    end' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '  end' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo '`endif' >> _t/rtl/e203/mems/sirv_mrom_top.v
echo 'endmodule' >> _t/rtl/e203/mems/sirv_mrom_top.v
