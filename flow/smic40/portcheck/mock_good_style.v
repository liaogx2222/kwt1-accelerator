// Mock of the POWER_PINS branch (line 481 of the authorized model): 12 ports,
// VDDCE/VDDPE/VSSE FIRST, and RETIN last -- i.e. PG pins AND retention enable.
// This is the branch that produced "3 ports not connected" against a 10-port
// instance. Semantics are contract-correct, so it is the PASS path for
// +define+KWT_SIM_POWER_PINS.
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
    input  wire        VSSE,
    input  wire        RETIN
);
    reg [15:0] mem [0:4095];
    integer i;
    initial for (i = 0; i < 4096; i = i + 1) mem[i] = 16'h0000;

    always @(posedge CLK) begin
        // GWEN is ACTIVE LOW: GWEN=1 -> not writing -> read; GWEN=0 -> write.
        if (!CEN && GWEN)       Q <= mem[A];   // read: Q follows
        else if (!CEN && !GWEN) mem[A] <= D;   // write: Q untouched
    end
endmodule
