// Select the direct source ahead of a simultaneous scalar DATA transaction.
// Non-DATA MMIO is independent. LAST remains the existing MMIO one-shot flag.
module kwt_stream_ingress (
    input wire clk, rst_n, blocked, aborting, loader_error,
    input wire direct_valid,
    output wire direct_ready, direct_error,
    input wire [31:0] direct_data,
    input wire scalar_valid,
    output wire scalar_ready,
    input wire [31:0] scalar_data,
    input wire cfg_ready,
    output wire cfg_valid,
    output wire [31:0] cfg_data,
    output wire direct_fire,
    input wire [31:0] scalar_words,
    output wire [31:0] total_words
);
    reg [31:0] direct_words;
    wire selected = direct_valid && !blocked && !aborting && !loader_error;
    assign cfg_valid = selected || scalar_valid;
    assign cfg_data = selected ? direct_data : scalar_data;
    assign scalar_ready = cfg_ready && !selected;
    assign direct_ready = cfg_ready && !blocked && !aborting && !loader_error;
    assign direct_error = loader_error;
    assign direct_fire = direct_valid && direct_ready;
    assign total_words = scalar_words + direct_words;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) direct_words <= 0;
        else if (direct_fire) direct_words <= direct_words + 1'b1;
    end
endmodule
