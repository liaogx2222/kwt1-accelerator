// Q/K are column-major vectors across 16 tokens. V is transposed on write
// into row-major vectors of 16 channels for the PV operand port.
module kwt_compact_qkv_resident (
    input wire clk,rst_n,clear,
    input wire result_valid,
    output wire result_ready,
    input wire [2:0] matrix,
    input wire [12:0] tag,
    input wire [31:0] result,
    input wire matrix_done,
    output wire available,
    input wire release_result,
    input wire read_valid,
    output wire read_ready,
    input wire [1:0] read_matrix,
    input wire [8:0] read_index,
    output wire response_valid,
    input wire response_ready,
    output wire [127:0] response_data,
    output wire [15:0] response_mask,
    output wire response_error,
    output reg [3:0] s_en,s_we,
    output reg [11:0] s_addr,
    output reg [63:0] s_wdata,
    input wire [63:0] s_rdata
);
    localparam [1:0] IDLE=0,HIGH=1,RESPONSE=2;
    wire live=rst_n&&!clear;
    reg [2:0] complete;
    reg [1:0] state;
    reg [63:0] low_data;
    reg [11:0] high_addr;
    reg tail_response,upper_response,bad_response;
    reg v_store,v_tail;
    reg [1:0] v_lane;
    reg [6:0] v_row;
    reg [2:0] v_block;
    reg [63:0] v_tile[0:3];

    wire [2:0] group_index=tag[12:10];
    wire [5:0] col={tag[7:6],tag[3:0]};
    wire v_matrix=matrix==5;
    wire k_matrix=matrix==2;
    wire tail=group_index==6;
    wire qk_write=result_valid&&result_ready&&!v_matrix;
    wire v_write=live&&v_store;
    wire [6:0] stored_row=v_row+{5'd0,v_lane};
    wire [4:0] v_tail_offset={stored_row[1:0],v_block};
    wire [11:0] qk_base=k_matrix?12'd2560:12'd1792;
    wire [11:0] qk_tail_base=k_matrix?12'd1601:12'd1537;
    wire [31:0] qk_payload=tail?{8'd0,result[23:0]}:result;
    wire write_upper=tail?col[0]:tag[4];
    assign result_ready=live&&!v_store;
    assign available=live&&(&complete);

    wire read_v=read_matrix==2;
    wire read_k=read_matrix==1;
    wire read_legal=read_matrix<3&&(read_v?read_index<396:read_index<448);
    wire read_tail=read_v?read_index>=384:read_index[8:6]==6;
    wire read_half=read_tail&&!read_v;
    wire [11:0] vector_offset={2'd0,read_index,1'b0};
    wire [11:0] read_base=read_v?12'd3328:read_k?12'd2560:12'd1792;
    wire [11:0] read_tail_base=read_k?12'd1601:12'd1537;
    wire [11:0] read_addr=read_v?(read_tail?12'd1665+{6'd0,read_index[3:0],2'b0}:read_base+vector_offset):
                                  (read_tail?read_tail_base+{6'd0,read_index[5:1],1'b0}:read_base+vector_offset);
    assign read_ready=available&&!v_store&&!release_result&&(state==IDLE||(state==RESPONSE&&response_ready));
    wire take=read_valid&&read_ready;
    wire high_read=live&&state==HIGH;
    assign response_valid=available&&state==RESPONSE;
    assign response_mask=bad_response?16'd0:tail_response?16'h0007:16'hffff;
    assign response_error=response_valid&&bad_response;
    assign response_data=bad_response?128'd0:tail_response?
                         {104'd0,(upper_response?s_rdata[55:32]:s_rdata[23:0])}:{s_rdata,low_data};

    always @* begin
        s_en=0;s_we=0;s_addr=0;s_wdata=0;
        if(qk_write) begin
            s_en=write_upper?4'b1100:4'b0011;s_we=s_en;
            s_addr=tail?qk_tail_base+{6'd0,col[5:1],1'b0}:
                         qk_base+{2'd0,group_index,col,tag[5]};
            s_wdata={2{qk_payload}};
        end else if(v_write) begin
            s_en=4'hf;s_we=4'hf;s_wdata=v_tile[v_lane];
            s_addr=v_tail?12'd1665+{6'd0,v_tail_offset,1'b0}:
                          12'd3328+{2'd0,stored_row,v_block};
        end else if(high_read) begin
            s_en=4'hf;s_addr=high_addr;
        end else if(take&&read_legal) begin
            s_en=read_half?(read_index[0]?4'b1100:4'b0011):4'hf;
            s_addr=read_addr;
        end
    end

    always @(posedge clk) if(result_valid&&result_ready&&v_matrix) begin
        for(integer lane=0;lane<4;lane=lane+1)
            v_tile[lane][8*col[2:0]+:8]<=result[8*lane+:8];
    end

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            complete<=0;state<=IDLE;low_data<=0;high_addr<=0;
            tail_response<=0;upper_response<=0;bad_response<=0;
            v_store<=0;v_tail<=0;v_lane<=0;v_row<=0;v_block<=0;
        end else if(clear) begin
            complete<=0;state<=IDLE;v_store<=0;
        end else begin
            if(matrix_done) begin
                case(matrix)
                    4:complete[0]<=1;
                    2:complete[1]<=1;
                    5:complete[2]<=1;
                    default:begin end
                endcase
            end
            if(release_result&&available&&!v_store&&(state==IDLE||(state==RESPONSE&&response_ready))) begin
                complete<=0;state<=IDLE;
            end else if(take) begin
                tail_response<=read_half;upper_response<=read_index[0];bad_response<=!read_legal;
                high_addr<=read_addr+(read_v&&read_tail?12'd2:12'd1);
                state<=!read_legal||read_half?RESPONSE:HIGH;
            end else if(high_read) begin
                low_data<=s_rdata;state<=RESPONSE;
            end else if(response_valid&&response_ready)state<=IDLE;

            if(result_valid&&result_ready&&v_matrix&&col[2:0]==7) begin
                v_store<=1;v_tail<=tail;v_lane<=0;
                v_row<={group_index,tag[5:4],2'd0};v_block<=col[5:3];
            end else if(v_write) begin
                if(v_lane==(v_tail?2'd2:2'd3))v_store<=0;
                else v_lane<=v_lane+1'b1;
            end
        end
    end
endmodule
