// =============================================================================
// tb_sram_contract -- proves the SMIC40 RAMSP4096X16 adapter honours the three
// frozen SRAM contract booleans that check_technology.py hard-codes:
//   read_latency_cycles        = 1
//   read_output_holds          = true
//   write_preserves_read_output= true
// -----------------------------------------------------------------------------
// This is NOT a synthesis or signoff run. It is the gate that says the wrapper
// in rtl/integration/smic40/ may stand in for the RTL register array.
// Run with the AUTHORIZED vendor model, never with rtl/integration/tech_sram_model.sv.
//
// Expected tail of the log:  PASS KWT_SRAM_CONTRACT checks=5
// =============================================================================
`timescale 1ns/1ps

module tb_sram_contract;

    reg         clk   = 1'b0;
    reg         en    = 1'b0;
    reg         we    = 1'b0;
    reg  [11:0] addr  = 12'd0;
    reg  [15:0] wdata = 16'd0;
    wire [15:0] rdata;

    integer errors = 0;
    integer checks = 0;

    kwt_tech_sram_4096x16 dut (
        .clk   (clk),
        .en    (en),
        .we    (we),
        .addr  (addr),
        .wdata (wdata),
        .rdata (rdata)
    );

    // 150 MHz target: 6.666667 ns period
    always #3.333333 clk = ~clk;

    task chk(input [255:0] tag, input [15:0] got, input [15:0] exp);
        begin
            checks = checks + 1;
            if (got !== exp) begin
                $display("FAIL %0s got=%04h exp=%04h at %0t", tag, got, exp, $time);
                errors = errors + 1;
            end else begin
                $display("ok   %0s = %04h", tag, got);
            end
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);

        // ---- T1: write then read back (also proves latency <= 1 cycle) ----
        @(negedge clk);
        en = 1'b1; we = 1'b1; addr = 12'd5; wdata = 16'hA5A5;
        @(posedge clk);              // write captured
        @(negedge clk);
        en = 1'b1; we = 1'b0; addr = 12'd5;
        @(posedge clk);              // read captured
        @(negedge clk);              // CLK->Q settled
        chk("T1 read-back", rdata, 16'hA5A5);

        // ---- T2: second address, proves address decoding ----
        @(negedge clk);
        en = 1'b1; we = 1'b1; addr = 12'd7; wdata = 16'h1234;
        @(posedge clk);
        @(negedge clk);
        en = 1'b1; we = 1'b0; addr = 12'd7;
        @(posedge clk);
        @(negedge clk);
        chk("T2 second address", rdata, 16'h1234);

        // ---- T3: read_output_holds -- Q must not move while en=0 ----
        @(negedge clk);
        en = 1'b0; we = 1'b0; addr = 12'd0;
        repeat (3) @(posedge clk);
        @(negedge clk);
        chk("T3 hold with en=0", rdata, 16'h1234);

        // ---- T4: write_preserves_read_output -- Q must not move on a write ----
        @(negedge clk);
        en = 1'b1; we = 1'b1; addr = 12'd9; wdata = 16'h3C3C;
        @(posedge clk);
        @(negedge clk);
        chk("T4 write preserves Q", rdata, 16'h1234);

        // ---- T5: the T4 write really landed ----
        @(negedge clk);
        en = 1'b1; we = 1'b0; addr = 12'd9;
        @(posedge clk);
        @(negedge clk);
        chk("T5 written value", rdata, 16'h3C3C);

        if (errors == 0)
            $display("PASS KWT_SRAM_CONTRACT checks=%0d", checks);
        else
            $display("FAIL KWT_SRAM_CONTRACT errors=%0d of %0d", errors, checks);

        $finish;
    end

    // Fail closed if the simulation dies without reaching the summary.
    initial begin
        #20000;
        $display("FAIL KWT_SRAM_CONTRACT timeout");
        $finish;
    end

endmodule
