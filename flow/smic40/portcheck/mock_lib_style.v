// Mock of the DC/.lib view: 10 ports, RETIN present, no PG pins.
// Used only to prove the wrapper's DEFAULT build elaborates against a cell
// that has RETIN. This is not the vendor model.
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
    input  wire        RETIN
);
    always @(posedge CLK) if (!CEN && !GWEN && RETIN) Q <= D;
endmodule
