`ifdef ARM_UD_MODEL
`ifdef ARM_UD_SO
`define ARM_UD_SEQ %0.01
`else
`define ARM_UD_SEQ %0.01
`endif

`celldefine
// If POWER PINS is defined at Simulator Command Line, it selects the module definition with Power Ports
`ifdef POWER_PINS
module RAMSP4096X16 (VDDCE, VDDPE, VSSE, Q, CLK, CEN, WEN, A, D, EMA, EMAW, GWEN, RETIN);
`else
module RAMSP4096X16 (Q, CLK, CEN, WEN, A, D, EMA, EMAW, GWEN, RETIN);
`endif

parameter ASSERT_PREFIX = "";
parameter BITS = 16;
parameter WORDS = 4096;

output [15:0] Q;
input CLK;
input CEN;
input [15:0] WEN;
input [11:0] A;
input [15:0] D;
input [2:0] EMA;
input [1:0] EMAW;
input GWEN;
input RETIN;
`ifdef POWER_PINS
inout VDDCE;
inout VDDPE;
inout VSSE;
`endif
endmodule
`endcelldefine
`else
`celldefine
`ifdef POWER_PINS
module RAMSP4096X16 (VDDCE, VDDPE, VSSE, Q, CLK, CEN, WEN, A, D, EMA, EMAW, GWEN);
`else
module RAMSP4096X16 (Q, CLK, CEN, WEN, A, D, EMA, EMAW, GWEN);
`endif
output [15:0] Q;
input CLK;
input CEN;
endmodule
`endcelldefine
`endif

module RAMSP4096X16_error_injection (Q_out, Q_in, CLK, A, CEN, WEN, GWEN);
endmodule
