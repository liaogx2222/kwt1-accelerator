// Keep FC2's result resident in A[256:703]. A[0:255] continues to stage
// FC2 operand groups and A[710:1023] remains reserved for exp.
module kwt_compact_ffn_writeback (
    input wire clk,rst_n,clear,
    input wire fc2_start,fc2_done,
    input wire result_accept,
    input wire [12:0] result_tag,
    input wire [3:0] result_mask,
    input wire [31:0] result_data,
    output wire [7:0] bank_en,bank_we,
    output wire [9:0] bank_addr,
    output wire [127:0] bank_wdata,
    input wire [127:0] bank_rdata,
    output reg available,error,
    input wire release_result,
    input wire read_valid,
    output wire read_ready,
    input wire [8:0] read_addr,
    output reg response_valid,
    input wire response_ready,
    output wire [127:0] response_data,
    output reg [15:0] response_mask
);
    reg writing;
    reg [10:0] writes;
    wire write_fire=rst_n&&!clear&&writing&&result_accept;
    wire [3:0] expected_mask=result_tag[12:10]==6?4'b0111:4'b1111;
    wire valid_tag=result_tag[12:10]<7&&result_tag[9:8]==0&&
                   (result_tag[12:10]!=6||result_tag[5:4]==0)&&result_mask==expected_mask;
    wire [1:0] pair_en={|result_mask[3:2],|result_mask[1:0]};
    wire [2:0] pair_shift={result_tag[5:4],1'b0};
    assign bank_we=write_fire&&valid_tag&&writes<1600?({6'b0,pair_en}<<pair_shift):8'b0;
    assign read_ready=rst_n&&!clear&&available&&read_addr<448&&
                      (!response_valid||response_ready)&&!release_result;
    wire read_fire=read_valid&&read_ready;
    assign bank_en=read_fire?(read_addr>=384?8'h03:8'hff):bank_we;
    assign bank_addr=10'd256+(read_fire ? {1'b0,read_addr} :
                                     {1'b0,result_tag[12:10],result_tag[7:6],result_tag[3:0]});
    wire [31:0] masked_data=result_data&
                            {{8{result_mask[3]}},{8{result_mask[2]}},{8{result_mask[1]}},{8{result_mask[0]}}};
    assign bank_wdata={4{masked_data}};
    assign response_data=bank_rdata;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin writing<=0; available<=0; error<=0; writes<=0; response_valid<=0; response_mask<=0; end
        else if(clear) begin writing<=0; available<=0; error<=0; writes<=0; response_valid<=0; response_mask<=0; end
        else begin
            if(response_valid&&response_ready) response_valid<=0;
            if(read_fire) begin
                response_valid<=1;
                response_mask<=read_addr>=384?16'h0007:16'hffff;
            end
            if(fc2_start) begin
                if(writing||available) error<=1;
                else begin writing<=1; writes<=0; end
            end
            if(write_fire) begin
                if(!valid_tag||writes==1600) error<=1;
                else writes<=writes+1'b1;
            end
            if(fc2_done) begin
                if(!writing||writes!=1600) error<=1;
                else begin writing<=0; available<=1; end
            end
            if(release_result&&available&&(!response_valid||response_ready)) available<=0;
        end
    end
endmodule
