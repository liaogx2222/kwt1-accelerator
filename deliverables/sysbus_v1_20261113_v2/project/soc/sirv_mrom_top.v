// Fixed CPU control firmware ROM. Generated from task.S, not model data.
// Same combinational ICB latency/response/error behavior as sirv_mrom_top.
// All 1024 words are defined: driver instructions, then addi x0,x0,0.
// There is no time-zero file loading or simulator runtime configuration.
module sirv_mrom_top #(parameter AW=12,DW=32,DP=1024)(
 input wire rom_icb_cmd_valid,output wire rom_icb_cmd_ready,
 input wire [AW-1:0] rom_icb_cmd_addr,input wire rom_icb_cmd_read,
 output wire rom_icb_rsp_valid,input wire rom_icb_rsp_ready,
 output wire rom_icb_rsp_err,output wire [DW-1:0] rom_icb_rsp_rdata,
 input wire clk,rst_n
);
 function [DW-1:0] boot_word;
  input [AW-3:0] word_address;
  begin
   // Retain the array model's X propagation for unknown/out-of-DP address.
   // For every binary in-range address this is a fully specified constant
   // function, which synthesis implements as combinational decode logic.
   boot_word={DW{1'bx}};
   case (^word_address)
    1'b0,1'b1:if(word_address<DP)begin
     case(word_address)
      0:boot_word=32'h110002b7;
      1:boot_word=32'ha0000fb7;
      2:boot_word=32'h00000493;
      3:boot_word=32'h000fa023;
      4:boot_word=32'ha0022eb7;
      5:boot_word=32'h0482ae03;
      6:boot_word=32'h00200e13;
      7:boot_word=32'h01c2a023;
      8:boot_word=32'h00148f13;
      9:boot_word=32'h00100437;
      10:boot_word=32'h000fae03;
      11:boot_word=32'hfff40413;
      12:boot_word=32'h1a040a63;
      13:boot_word=32'hffee1ae3;
      14:boot_word=32'ha0001337;
      15:boot_word=32'h000013b7;
      16:boot_word=32'h03038393;
      17:boot_word=32'h10000e13;
      18:boot_word=32'h180000ef;
      19:boot_word=32'h00100437;
      20:boot_word=32'h0042ae03;
      21:boot_word=32'hfff40413;
      22:boot_word=32'h18040663;
      23:boot_word=32'h004e7993;
      24:boot_word=32'h18099263;
      25:boot_word=32'h008e7e13;
      26:boot_word=32'hfe0e04e3;
      27:boot_word=32'ha0024337;
      28:boot_word=32'h000043b7;
      29:boot_word=32'hc4838393;
      30:boot_word=32'h00000e13;
      31:boot_word=32'h14c000ef;
      32:boot_word=32'h00100437;
      33:boot_word=32'h0042ae03;
      34:boot_word=32'hfff40413;
      35:boot_word=32'h14040c63;
      36:boot_word=32'h004e7993;
      37:boot_word=32'h14099863;
      38:boot_word=32'h020e7e13;
      39:boot_word=32'hfe0e04e3;
      40:boot_word=32'h01efa223;
      41:boot_word=32'ha0040337;
      42:boot_word=32'h000013b7;
      43:boot_word=32'hc6038393;
      44:boot_word=32'h128000ef;
      45:boot_word=32'h00100437;
      46:boot_word=32'h0042ae03;
      47:boot_word=32'hfff40413;
      48:boot_word=32'h12040263;
      49:boot_word=32'h004e7993;
      50:boot_word=32'h10099e63;
      51:boot_word=32'h100e7e13;
      52:boot_word=32'hfe0e04e3;
      53:boot_word=32'h00100e13;
      54:boot_word=32'h01c2a023;
      55:boot_word=32'h00100f13;
      56:boot_word=32'h00100437;
      57:boot_word=32'h0042ae03;
      58:boot_word=32'hfff40413;
      59:boot_word=32'h0e040c63;
      60:boot_word=32'h004e7993;
      61:boot_word=32'h0e099863;
      62:boot_word=32'h040e7e13;
      63:boot_word=32'hfe0e04e3;
      64:boot_word=32'h00148913;
      65:boot_word=32'h01e90933;
      66:boot_word=32'h00100437;
      67:boot_word=32'h000fae03;
      68:boot_word=32'hfff40413;
      69:boot_word=32'h0c040863;
      70:boot_word=32'hff2e1ae3;
      71:boot_word=32'ha0024337;
      72:boot_word=32'h000043b7;
      73:boot_word=32'hc4838393;
      74:boot_word=32'h000f0e13;
      75:boot_word=32'h09c000ef;
      76:boot_word=32'h00100437;
      77:boot_word=32'h0042ae03;
      78:boot_word=32'hfff40413;
      79:boot_word=32'h0a040463;
      80:boot_word=32'h004e7993;
      81:boot_word=32'h0a099063;
      82:boot_word=32'h020e7e13;
      83:boot_word=32'hfe0e04e3;
      84:boot_word=32'h012fa223;
      85:boot_word=32'h001f0f13;
      86:boot_word=32'h00c00e13;
      87:boot_word=32'hf9cf14e3;
      88:boot_word=32'h63000f13;
      89:boot_word=32'h00100437;
      90:boot_word=32'h0042ae03;
      91:boot_word=32'hfff40413;
      92:boot_word=32'h06040a63;
      93:boot_word=32'h004e7993;
      94:boot_word=32'h06099663;
      95:boot_word=32'h00ce5e13;
      96:boot_word=32'h001e7e13;
      97:boot_word=32'hfe0e02e3;
      98:boot_word=32'ha0022337;
      99:boot_word=32'h63000393;
      100:boot_word=32'h54737e7b;
      101:boot_word=32'h040e1863;
      102:boot_word=32'h00100437;
      103:boot_word=32'h0042ae03;
      104:boot_word=32'hfff40413;
      105:boot_word=32'h04040063;
      106:boot_word=32'h004e7993;
      107:boot_word=32'h02099c63;
      108:boot_word=32'h002e7e13;
      109:boot_word=32'hfe0e04e3;
      110:boot_word=32'h5a500e13;
      111:boot_word=32'h01cfa423;
      112:boot_word=32'h01048493;
      113:boot_word=32'he4dff06f;
      114:boot_word=32'h01c2a423;
      115:boot_word=32'h50737e7b;
      116:boot_word=32'h000e1a63;
      117:boot_word=32'h00008067;
      118:boot_word=32'h52737e7b;
      119:boot_word=32'h000e1463;
      120:boot_word=32'h00008067;
      121:boot_word=32'h00200e13;
      122:boot_word=32'h01c2a023;
      123:boot_word=32'hbad00e37;
      124:boot_word=32'h01cfa423;
      125:boot_word=32'h0000006f;
      default:boot_word=32'h00000013;
     endcase
    end
    default:boot_word={DW{1'bx}};
   endcase
  end
 endfunction
 assign rom_icb_rsp_valid=rom_icb_cmd_valid;
 assign rom_icb_cmd_ready=rom_icb_rsp_ready;
 assign rom_icb_rsp_err=~rom_icb_cmd_read;
 assign rom_icb_rsp_rdata=boot_word(rom_icb_cmd_addr[AW-1:2]);
endmodule
