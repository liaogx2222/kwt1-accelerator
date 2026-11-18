// Mock of the 10-PORT variant (the one at lines 87 and 483 of the authorized
// model): Q, CLK, CEN, WEN, A, D, EMA, EMAW, GWEN, RETIN -- no PG in the port
// list. Semantics are contract-correct, so this is the PASS path for the
// DEFAULT build (no defines), which is also the build dc_shell uses.
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
    reg [15:0] mem [0:4095];
    integer i;
    initial for (i = 0; i < 4096; i = i + 1) mem[i] = 16'h0000;

    always @(posedge CLK) begin
        // GWEN is ACTIVE LOW: GWEN=1 -> not writing -> read; GWEN=0 -> write.
        if (!CEN && GWEN)       Q <= mem[A];   // read: Q follows
        else if (!CEN && !GWEN) mem[A] <= D;   // write: Q untouched
    end
endmodule
