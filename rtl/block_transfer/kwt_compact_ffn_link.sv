// Canonical GELU LUT plus the FC1-to-FC2 packed S-bank handoff.
// The S-bank owner grants both write lanes on a result handshake.
module kwt_compact_ffn_link (
    input wire clk,rst_n,clear,
    input wire lut_accept,
    input wire [5:0] lut_index,
    input wire [31:0] lut_word,
    input wire fc1_start,fc1_done,fc2_done,
    input wire result_accept,
    input wire [12:0] result_tag,
    input wire [3:0] result_mask,
    input wire [31:0] result_data,
    output wire lut_ready,fc2_ready,
    output reg owns_s,error,
    output wire [3:0] s_write,
    output wire [11:0] s_addr,
    output wire [63:0] s_data
);
    reg [31:0] lut[0:63];
    reg [6:0] loaded_words;
    reg [12:0] written_groups;
    reg writing,committed;
    assign lut_ready=loaded_words==64&&!error;
    assign fc2_ready=committed&&!error;
    wire write_fire=rst_n&&!clear&&writing&&result_accept;
    wire [3:0] expected_mask=result_tag[12:10]==6?4'b0111:4'b1111;
    wire [1:0] pair_en={|result_mask[3:2],|result_mask[1:0]};
    assign s_write=write_fire&&result_mask==expected_mask&&result_tag[12:10]<7&&written_groups<6400?
                   (result_tag[4]?{pair_en,2'b0}:{2'b0,pair_en}):4'b0;
    assign s_addr={result_tag[12:10],result_tag[9:6],result_tag[3:0],result_tag[5]};
    wire [31:0] mapped;
    genvar lane;
    generate for(lane=0;lane<4;lane=lane+1)begin: lookup
        wire [7:0] index=result_data[lane*8+:8]^8'h80;
        assign mapped[lane*8+:8]=result_mask[lane]?lut[index[7:2]][index[1:0]*8+:8]:8'b0;
    end endgenerate
    assign s_data={mapped,mapped};

    always @(posedge clk) begin
        if(rst_n&&!clear&&lut_accept&&!owns_s&&loaded_words<64&&lut_index==loaded_words[5:0])
            lut[lut_index]<=lut_word;
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin loaded_words<=0; written_groups<=0; writing<=0; committed<=0; owns_s<=0; error<=0; end
        else if(clear) begin loaded_words<=0; written_groups<=0; writing<=0; committed<=0; owns_s<=0; error<=0; end
        else begin
            if(lut_accept) begin
                if(owns_s||loaded_words==64||lut_index!=loaded_words[5:0]) error<=1;
                else loaded_words<=loaded_words+1'b1;
            end
            if(fc1_start) begin
                if(!lut_ready||owns_s) error<=1;
                else begin owns_s<=1; writing<=1; written_groups<=0; end
            end
            if(write_fire) begin
                if(result_mask!=expected_mask||result_tag[12:10]>6||written_groups==6400) error<=1;
                else written_groups<=written_groups+1'b1;
            end
            if(fc1_done) begin
                if(!writing||written_groups!=6400) error<=1;
                else begin writing<=0; committed<=1; end
            end
            if(fc2_done) begin
                if(!fc2_ready) error<=1;
                committed<=0; owns_s<=0;
            end
        end
    end
endmodule
