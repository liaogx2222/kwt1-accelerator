// RAMSP4096X16 gate-level behavioural model -- SINGLE DEFINITION.
// Ten ports (RETIN included, functionally ignored: retention must be inactive).
// Behaviour equals flow/smic40/tb_sram_contract.sv PASS 5/5 (2026-11-07):
//   read latency 1, Q holds, write does not touch Q, active-low CEN/GWEN/WEN.
// INITIALISATION 0xA5A5 IS REQUIRED: rtl/v2/kwt_sram_sp.sv starts from the same
// poison value; without it the layer FSM goes X and the run deadlocks.
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
    reg [15:0] nw;
    integer i;
    initial begin
        Q = 16'hA5A5;
        for (i = 0; i < 4096; i = i + 1) mem[i] = 16'hA5A5;
    end
    always @(posedge CLK) begin
        if (CEN === 1'b0) begin
            if (GWEN === 1'b0) begin
                nw = mem[A];
                for (i = 0; i < 16; i = i + 1)
                    if (WEN[i] === 1'b0) nw[i] = D[i];
                mem[A] <= nw;
            end else if (WEN == 16'hFFFF) begin
                Q <= mem[A];
            end
        end
    end
endmodule
