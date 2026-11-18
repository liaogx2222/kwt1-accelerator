// Mock of the vendor behavioural model: 12 ports, NO RETIN, three PG pins.
// Reproduces exactly the VCS failure signature seen on RServer06:
//   Error-[MPOMTC] port (RETIN) was not found
//   Error-[UPIMC]  3 ports not connected
// Used only to prove the wrapper's +define+VCS_VENDOR_MODEL build elaborates.
`timescale 1ns/1ps
module RAMSP4096X16 (
    output reg  [15:0] Q,
    input  wire        CLK,
    input  wire        CEN,
    input  wire [15:0] WEN,
    input  wire [11:0] A,
    input  wire [15:0] D,
    input  wire [2:0]  EMA,
    input  wire [1:0]  EMAW,
    input  wire        GWEN,
    input  wire        VDDCE,
    input  wire        VDDPE,
    input  wire        VSSE
);
    always @(posedge CLK) if (!CEN && !GWEN) Q <= D;
endmodule
