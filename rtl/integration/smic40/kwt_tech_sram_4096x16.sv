// SMIC40 RAMSP4096X16 binding: RET1N contains the digit ONE.
// The 2026-11-11 mapped netlist/VCS binding confirmed this actual port name.
// Normal operation is RET1N=1. The old RETIN/nine-pin assumption was incorrect.
// Keep all ten named ports identical between library binding and simulation.
// Contract: synchronous read, hold when disabled, write preserves read output.
module kwt_tech_sram_4096x16 (
    input wire clk, en, we,
    input wire [11:0] addr,
    input wire [15:0] wdata,
    output wire [15:0] rdata
);
    wire wr = en & we;
    RAMSP4096X16 u_ramsp4096x16 (
        .Q(rdata), .CLK(clk), .CEN(~en),
        .WEN(wr ? 16'h0000 : 16'hFFFF),
        .A(addr), .D(wdata), .EMA(3'b010), .EMAW(2'b00),
        .GWEN(~wr), .RET1N(1'b1)
    );
endmodule
