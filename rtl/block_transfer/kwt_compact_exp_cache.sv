// Exact fixed-profile exp cache in the reserved upper 314 words of A0..A7.
// The caller grants these bank ports for the indicated cycle. It must exclude
// competing access to a requested bank and reserve addresses 710..1023.
module kwt_compact_exp_cache (
    input wire clk, rst_n, abort,
    input wire load_start, output wire load_start_ready,
    input wire load_valid, output wire load_ready,
    input wire [31:0] load_data, input wire load_last,
    output reg cache_valid, load_error,
    input wire query_valid, output wire query_ready, input wire [12:0] query_index,
    output reg response_valid, input wire response_ready,
    output reg [20:0] response_data, output reg response_error,
    output reg [7:0] bank_en, bank_we,
    output reg [79:0] bank_addr,
    output reg [127:0] bank_wdata,
    input wire [127:0] bank_rdata
);
    reg loading, input_done, read_pending;
    reg [11:0] entry_index, packed_word;
    reg [5:0] bit_count;
    reg [35:0] bits;
    reg [2:0] read_bank;
    reg [3:0] read_shift;
    reg [4:0] read_width;

    function automatic [4:0] block_width(input [3:0] block);
        case(block)
            0:block_width=20; 1:block_width=19; 2:block_width=18; 3:block_width=16;
            4:block_width=15; 5:block_width=13; 6:block_width=12; 7:block_width=10;
            8:block_width=9;  9:block_width=8; 10:block_width=6; 11:block_width=5;
            12:block_width=3; 13:block_width=2; 14:block_width=1; default:block_width=0;
        endcase
    endfunction

    function automatic [7:0] preceding_widths(input [3:0] block);
        case(block)
            0:preceding_widths=0; 1:preceding_widths=20; 2:preceding_widths=39; 3:preceding_widths=57;
            4:preceding_widths=73; 5:preceding_widths=88; 6:preceding_widths=101; 7:preceding_widths=113;
            8:preceding_widths=123; 9:preceding_widths=132; 10:preceding_widths=140; 11:preceding_widths=146;
            12:preceding_widths=151; 13:preceding_widths=154; 14:preceding_widths=156; default:preceding_widths=157;
        endcase
    endfunction

    wire [4:0] input_width = block_width(entry_index[11:8]);
    wire input_error = (entry_index==0 ? load_data!=32'h100000 : (load_data>>input_width)!=0) ||
                       load_last!=(entry_index==4095);
    wire [31:0] normalized = entry_index==0 ? 0 : load_data;
    wire drain = rst_n && !abort && loading && bit_count>=16;
    assign load_start_ready = rst_n && !abort && !loading && !read_pending && !response_valid;
    assign load_ready = rst_n && !abort && loading && !input_done && !drain;
    assign query_ready = rst_n && !abort && cache_valid && !read_pending &&
                         (!response_valid || response_ready) && !load_start;
    wire query_fire = query_valid && query_ready;
    wire [4:0] width = block_width(query_index[11:8]);
    wire [15:0] position = {preceding_widths(query_index[11:8]),8'b0}
                           + 16'(query_index[7:0]*width);
    wire [11:0] word0 = position[15:4];
    wire [5:0] span = {2'b0,position[3:0]}+{1'b0,width};
    wire fetch = query_fire && query_index!=0 && query_index<4096 && width!=0;
    wire [2:0] read_bank1 = read_bank+3'd1;
    wire [2:0] read_bank2 = read_bank+3'd2;
    wire [47:0] window = {bank_rdata[read_bank2*16+:16],bank_rdata[read_bank1*16+:16],bank_rdata[read_bank*16+:16]};
    wire [20:0] mask = (21'd1 << read_width)-1'b1;

    integer j;
    reg [11:0] word_j;
    reg [2:0] bank_j;
    always @* begin
        bank_en=0; bank_we=0; bank_addr=0; bank_wdata=0;
        word_j=0; bank_j=0;
        if (drain) begin
            bank_j=packed_word[2:0];
            bank_en[bank_j]=1; bank_we[bank_j]=1;
            bank_addr[bank_j*10+:10]=10'd710+10'(packed_word[11:3]);
            bank_wdata[bank_j*16+:16]=bits[15:0];
        end else if (fetch) begin
            for(j=0;j<3;j=j+1) begin
                if(span>16*j) begin
                    word_j=word0+12'(j);
                    bank_j=word_j[2:0];
                    bank_en[bank_j]=1;
                    bank_addr[bank_j*10+:10]=10'd710+10'(word_j[11:3]);
                end
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            loading<=0; input_done<=0; read_pending<=0; cache_valid<=0; load_error<=0;
            entry_index<=0; packed_word<=0; bit_count<=0; bits<=0;
            read_bank<=0; read_shift<=0; read_width<=0;
            response_valid<=0; response_data<=0; response_error<=0;
        end else if(abort) begin
            loading<=0; cache_valid<=0; read_pending<=0; response_valid<=0;
        end else begin
            if(response_valid&&response_ready) response_valid<=0;
            if(load_start&&load_start_ready) begin
                loading<=1; cache_valid<=0; input_done<=0; load_error<=0;
                entry_index<=0; packed_word<=0; bit_count<=0; bits<=0;
            end else if(drain) begin
                bits<=bits>>16; bit_count<=bit_count-16; packed_word<=packed_word+1'b1;
            end else if(load_valid&&load_ready) begin
                if(input_error) begin
                    loading<=0; load_error<=1;
                end else begin
                    bits<=bits|({4'b0,normalized}<<bit_count);
                    bit_count<=bit_count+{1'b0,input_width};
                    entry_index<=entry_index+1'b1;
                    input_done<=load_last;
                end
            end else if(loading&&input_done) begin
                loading<=0;
                cache_valid<=packed_word==2512 && bit_count==0;
                load_error<=packed_word!=2512 || bit_count!=0;
            end
            if(query_fire) begin
                if(fetch) begin
                    read_pending<=1; read_bank<=word0[2:0]; read_shift<=position[3:0]; read_width<=width;
                end else begin
                    response_valid<=1; response_data<=query_index==0 ? 21'h100000 : 0;
                    response_error<=query_index>4096;
                end
            end
            if(read_pending) begin
                read_pending<=0; response_valid<=1; response_error<=0;
                response_data<=21'(window>>read_shift)&mask;
            end
        end
    end
endmodule
