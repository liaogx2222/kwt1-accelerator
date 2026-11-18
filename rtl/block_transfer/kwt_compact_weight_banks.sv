// Canonical packet replay to compact A/B/S storage. Only B carries replayed
// weights here; A and S are independent compute ports. Consumers release each
// complete matrix before the next one can overwrite any B address.
module kwt_compact_weight_banks (
    input wire clk, rst_n,
    input wire bank_request, packet_common, bank_available,
    output wire bank_grant,
    input wire sink_valid, sink_last, sink_abort, quarantine,
    input wire [31:0] sink_data,
    output wire sink_ready, consumer_aborted,
    output reg consumer_done,
    output reg tile_valid,
    output reg [2:0] tile_id,
    output reg tile_deep,
    input wire tile_done,
    input wire tile_read,
    input wire [9:0] tile_addr,
    output wire tile_ready, tile_response,
    output wire [127:0] tile_data,
    input wire [11:0] compute_en, compute_we,
    input wire [143:0] compute_addr,
    input wire [191:0] compute_wdata,
    output wire [191:0] compute_rdata
);
    reg active, common, second_half, last_in_matrix, last_in_packet, response_pending;
    reg [14:0] packet_word;
    reg [15:0] high_half;
    reg [2:0] write_bank;
    reg [9:0] write_addr;
    reg [14:0] first_word, end_word;
    reg [2:0] matrix_id;
    reg deep;
    always @* begin
        // Word ranges of canonical FC1, FC2, K, O, Q, V. Bound against all
        // twelve frozen directories by verify_compact_weight_banks.py.
        first_word=0; end_word=0; matrix_id=0; deep=0;
        if (!common) begin
            if (packet_word < 6104) begin first_word=2008; end_word=6104; matrix_id=0; deep=1; end
            else if (packet_word < 10392) begin first_word=6296; end_word=10392; matrix_id=1; deep=1; end
            else if (packet_word < 11608) begin first_word=10584; end_word=11608; matrix_id=2; end
            else if (packet_word < 13104) begin first_word=12080; end_word=13104; matrix_id=3; end
            else if (packet_word < 14256) begin first_word=13232; end_word=14256; matrix_id=4; end
            else begin first_word=14408; end_word=15432; matrix_id=5; end
        end
    end
    wire in_matrix = packet_word >= first_word && packet_word < end_word;
    wire [11:0] matrix_word = 12'(packet_word-first_word);
    // The packet stores four pairs of output columns, with K even. Two
    // consecutive halfwords therefore target one bank at consecutive addresses.
    wire [2:0] mapped_bank = deep
        ? {matrix_word[matrix_id==0 ? 5 : 7],matrix_word[11:10]}
        : {matrix_word[5],matrix_word[9:8]};
    wire [9:0] mapped_addr = deep
        ? matrix_id==0 ? {matrix_word[9:6],matrix_word[4:0],1'b0}
                       : {matrix_word[9:8],matrix_word[6:0],1'b0}
        : {2'b00,matrix_word[7:6],matrix_word[4:0],1'b0};
    wire allowed = rst_n && !sink_abort && !quarantine;
    wire take = sink_valid && sink_ready;
    wire write_first = take && in_matrix;
    wire write_second = allowed && second_half;
    wire read_b = tile_read && tile_ready;
    assign bank_grant = allowed && !active && bank_available;
    assign sink_ready = allowed && active && !last_in_packet && !second_half && !tile_valid;
    assign consumer_aborted = rst_n && sink_abort;
    assign tile_ready = allowed && tile_valid && !tile_done && (tile_deep || tile_addr < 256);
    assign tile_response = allowed && response_pending;

    genvar bank;
    generate for (bank=0; bank<8; bank=bank+1) begin: operand_pair
        wire operand_address_ok = compute_addr[12*bank+10+:2]==0;
        kwt_small_sp operand(clk,rst_n&&compute_en[bank]&&operand_address_ok,compute_we[bank],compute_addr[12*bank+:10],
                             compute_wdata[16*bank+:16],compute_rdata[16*bank+:16]);
        wire wb0 = write_first && mapped_bank==bank;
        wire wb1 = write_second && write_bank==bank;
        kwt_small_sp weight(clk,wb0||wb1||read_b,wb0||wb1,
                            wb0 ? mapped_addr : wb1 ? write_addr : tile_addr,
                            wb0 ? sink_data[15:0] : high_half,tile_data[16*bank+:16]);
    end
    for (bank=8; bank<12; bank=bank+1) begin: scratch_bank
        kwt_sram_sp scratch(clk,rst_n&&compute_en[bank],compute_we[bank],compute_addr[12*bank+:12],
                            compute_wdata[16*bank+:16],compute_rdata[16*bank+:16]);
    end endgenerate

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active<=0; common<=0; second_half<=0; last_in_matrix<=0; last_in_packet<=0;
            response_pending<=0; packet_word<=0; high_half<=0; write_bank<=0; write_addr<=0;
            tile_valid<=0; tile_id<=0; tile_deep<=0; consumer_done<=0;
        end else begin
            consumer_done<=0;
            response_pending<=read_b;
            if (sink_abort || quarantine) begin
                if (sink_abort) active<=0;
                second_half<=0;
                tile_valid<=0;
            end else begin
                if (bank_request && bank_grant) begin
                    active<=1; common<=packet_common; packet_word<=0; last_in_packet<=0;
                end
                if (take) begin
                    packet_word<=packet_word+1'b1;
                    last_in_packet<=sink_last;
                    if (write_first) begin
                        high_half<=sink_data[31:16]; write_bank<=mapped_bank;
                        write_addr<=mapped_addr+1'b1; second_half<=1;
                        last_in_matrix<=packet_word==end_word-1'b1;
                        tile_id<=matrix_id; tile_deep<=deep;
                    end
                end
                if (write_second) begin
                    second_half<=0;
                    if (last_in_matrix) tile_valid<=1;
                end
                if (tile_valid && tile_done) tile_valid<=0;
                if (active && last_in_packet && !second_half && !tile_valid) begin
                    active<=0;
                    consumer_done<=1;
                end
            end
        end
    end
endmodule
