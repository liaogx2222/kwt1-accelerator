// One query group's S32 scores in B[0..395]. A four-row MAC response
// writes eight 16-bit banks; one Softmax row reads its own bank pair.
module kwt_compact_qk_score_store (
    input wire clk,rst_n,clear,
    input wire start,tail,
    output wire start_ready,
    input wire score_valid,
    output wire score_ready,
    input wire [1:0] score_quad,
    input wire [6:0] score_key,
    input wire [3:0] score_mask,
    input wire [127:0] scores,
    input wire close_group,release_group,
    output wire available,error,
    input wire read_valid,
    output wire read_ready,
    input wire [3:0] read_row,
    input wire [6:0] read_key,
    output wire response_valid,
    input wire response_ready,
    output wire signed [31:0] response_score,
    output wire [7:0] bank_en,bank_we,
    output wire [9:0] bank_addr,
    output wire [127:0] bank_wdata,
    input wire [127:0] bank_rdata
);
    localparam [1:0] IDLE=0,WRITING=1,READING=2,FAILED=3;
    reg [1:0] state,response_pair;
    reg tail_group,pending;
    reg [8:0] beats;
    wire live=rst_n&&!clear;
    wire write_legal=score_key<99&&score_mask==(tail_group?4'b0111:4'b1111)&&(!tail_group||score_quad==0);
    wire read_legal=read_key<99&&(!tail_group||read_row<3);
    wire [8:0] limit=tail_group?9'd99:9'd396;
    assign start_ready=live&&state==IDLE;
    assign score_ready=live&&state==WRITING&&!close_group&&beats<limit;
    assign available=live&&state==READING;
    assign error=live&&state==FAILED;
    assign read_ready=available&&!release_group&&(!pending||response_ready);
    assign response_valid=available&&pending;
    wire write_fire=score_valid&&score_ready;
    wire read_fire=read_valid&&read_ready;
    wire [1:0] address_quad=write_fire?score_quad:read_row[3:2];
    wire [6:0] address_key=write_fire?score_key:read_key;
    assign bank_addr=10'(address_quad*10'd99)+{3'd0,address_key};
    assign bank_we=write_fire&&write_legal?{{2{score_mask[3]}},{2{score_mask[2]}},
                                          {2{score_mask[1]}},{2{score_mask[0]}}}:8'd0;
    assign bank_en=read_fire&&read_legal?(8'd3<<{read_row[1:0],1'b0}):bank_we;
    assign bank_wdata=scores;
    assign response_score=bank_rdata[32*response_pair+:32];

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin state<=IDLE;response_pair<=0;tail_group<=0;pending<=0;beats<=0;end
        else if(clear)begin state<=IDLE;pending<=0;end
        else case(state)
            IDLE:if(start)begin state<=WRITING;tail_group<=tail;beats<=0;pending<=0;end
            WRITING:if(close_group)state<=beats==limit?READING:FAILED;
                    else if(write_fire)begin
                        if(!write_legal)state<=FAILED;
                        else beats<=beats+1'b1;
                    end
            READING:if(release_group&&(!pending||response_ready))begin state<=IDLE;pending<=0;end
                    else if(read_fire)begin
                        if(!read_legal)begin state<=FAILED;pending<=0;end
                        else begin pending<=1;response_pair<=read_row[1:0];end
                    end else if(response_valid&&response_ready)pending<=0;
            FAILED:begin end
            default:state<=FAILED;
        endcase
    end
endmodule
