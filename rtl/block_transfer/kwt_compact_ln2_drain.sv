// Read the row-major LN2 result through the synchronous S-bank read ports.
// The SRAM output registers are the payload slot. Keep the ports exclusively
// owned until the last response handshakes, including while that slot stalls.
module kwt_compact_ln2_drain (
    input wire clk,rst_n,clear,start,
    output wire owned,
    output wire read_s,
    output wire [9:0] read_index,
    input wire [63:0] s_data,
    output wire out_valid,
    input wire out_ready,
    output reg [9:0] out_index,
    output wire out_last,
    output wire [63:0] out_data
);
    localparam [9:0] WORDS=792;
    reg active,pending;
    reg [9:0] next_index;
    wire live=rst_n&&!clear;
    assign owned=live&&(active||start);
    assign read_s=live&&active&&next_index<WORDS&&(!pending||out_ready);
    assign read_index=next_index;
    assign out_valid=live&&pending;
    assign out_last=out_valid&&out_index==WORDS-10'd1;
    assign out_data=s_data;

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            active<=0; pending<=0; next_index<=0; out_index<=0;
        end else if(clear) begin
            active<=0; pending<=0; next_index<=0; out_index<=0;
        end else if(start&&!active) begin
            active<=1; pending<=0; next_index<=0;
        end else begin
            if(out_valid&&out_ready) begin
                pending<=0;
                if(out_last)active<=0;
            end
            if(read_s) begin
                pending<=1;
                out_index<=next_index;
                next_index<=next_index+1'b1;
            end
        end
    end
endmodule
