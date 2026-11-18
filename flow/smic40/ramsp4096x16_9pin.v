// =============================================================================
// RAMSP4096X16 -- NINE-PIN behavioural model, gate-level simulation only.
// -----------------------------------------------------------------------------
// WHY NOT THE VENDOR MODEL:
//   .../SRAM_Lib_2025/RAMSP4096X16/verilog/RAMSP4096X16.v declares TEN ports
//   (..., GWEN, RETIN).  The DC netlist instantiates NINE pins by name and has
//   no RETIN, because synthesis binds the .lib/.db, which has nine pins.
//   Using the vendor model would leave RETIN floating inside the macro.
//   See [E4]/[E6] in rtl/integration/smic40/kwt_tech_sram_4096x16.sv.
//
// CONTRACT EQUIVALENCE:
//   This implements exactly what flow/smic40/tb_sram_contract.sv proved on the
//   vendor model (PASS 5/5, 2026-11-07): read latency 1, read output holds,
//   write preserves the read output, active-low CEN/GWEN/WEN.
//
// SCOPE: function only. No timing (comes from SDF after P&R) and no power
//   (macro internal power is not in the standard-cell .lib either way).
//
//   read  : CEN=0, GWEN=1, WEN=16'hFFFF  -> Q <= mem[A] on the next posedge
//   write : CEN=0, GWEN=0                -> mem[A] takes D where WEN is 0
//
// INITIALISATION -- REQUIRED, DO NOT REMOVE
//   rtl/v2/kwt_sram_sp.sv, the model the RTL regression runs against, does
//       `ifdef KWT_SIM  initial begin rdata=16'ha5a5; for(...) mem[i]=16'ha5a5; end
//   The accelerator reads a few locations before writing them and only avoids
//   X because that model starts from a concrete 0xA5A5.  With an uninitialised
//   array those reads return X, the layer FSM goes X and the run deadlocks
//   (observed 2026-11-09: status became 0000xxxx, debug_state=x).  Gate-level
//   must use the SAME poison value as RTL, otherwise the two runs are not
//   comparable.
// =============================================================================
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
    input  wire        GWEN
);
    reg [15:0] mem [0:4095];
    reg [15:0] nw;
    integer i;
    initial begin
        Q = 16'hA5A5;
        for (i = 0; i < 4096; i = i + 1) mem[i] = 16'hA5A5;
    end
    always @(posedge CLK) begin
        if (!CEN) begin
            if (!GWEN) begin
                nw = mem[A];
                for (i = 0; i < 16; i = i + 1)
                    if (!WEN[i]) nw[i] = D[i];
                mem[A] <= nw;          // write never touches Q
            end else if (WEN == 16'hFFFF) begin
                Q <= mem[A];           // read latency 1, holds until next read
            end
        end
    end
endmodule
