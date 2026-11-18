// Functional contract only, not the vendor timing/retention model.
// RET1N (digit 1) must be driven HIGH for the supported normal-access mode.
// Never silently ignore a missing/floating retention pin.
`timescale 1ns/1ps
module RAMSP4096X16 (
    output reg [15:0] Q,
    input wire CLK, CEN,
    input wire [15:0] WEN,
    input wire [11:0] A,
    input wire [15:0] D,
    input wire [2:0] EMA,
    input wire [1:0] EMAW,
    input wire GWEN, RET1N
);
    reg [15:0] mem [0:4095];
    reg [15:0] nw;
    integer i;
    initial begin
        if ($test$plusargs("KWT_SRAM_INIT_X")) begin
            Q = 16'hxxxx;
            for (i=0; i<4096; i=i+1) mem[i] = 16'hxxxx;
        end else if ($test$plusargs("KWT_SRAM_INIT_ZERO")) begin
            Q = 16'h0000;
            for (i=0; i<4096; i=i+1) mem[i] = 16'h0000;
        end else begin
            Q = 16'hA5A5;
            for (i=0; i<4096; i=i+1) mem[i] = 16'hA5A5;
        end
    end
    always @(posedge CLK) begin
        if (CEN === 1'b0) begin
            if (RET1N !== 1'b1)
                $fatal(1, "KWT_SRAM_RET1N_NORMAL_MODE_REQUIRED value=%b", RET1N);
            if (!GWEN) begin
                nw = mem[A];
                for (i=0; i<16; i=i+1) if (!WEN[i]) nw[i] = D[i];
                mem[A] <= nw;
            end else if (WEN == 16'hFFFF) Q <= mem[A];
        end
    end
endmodule
