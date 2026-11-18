// Feed a shared 16x16 MAC from resident S Q/K vectors. The Q tile is cached
// in A[448..511]; each accepted K read launches its matching A read.
module kwt_compact_qk_feed (
    input wire clk,rst_n,clear,
    input wire start,output wire start_ready,
    input wire [2:0] query_group,key_group,
    output wire qkv_read,input wire qkv_ready,
    output wire [1:0] qkv_matrix,output wire [8:0] qkv_index,
    input wire qkv_valid,output wire qkv_response_ready,
    input wire [127:0] qkv_data,input wire [15:0] qkv_mask,input wire qkv_error,
    output wire a_enable,a_write,output wire [9:0] a_addr,
    output wire [127:0] a_wdata,input wire [127:0] a_rdata,
    output wire mac_init,input wire mac_init_ready,
    output wire mac_valid,input wire mac_ready,output wire mac_last,
    output wire [127:0] mac_a,mac_b,
    output wire mac_read,input wire mac_read_ready,
    output wire [3:0] mac_row,mac_col,
    output wire [15:0] mac_tag,
    input wire mac_raw,input wire [127:0] mac_raw_data,input wire [15:0] mac_raw_tag,
    output wire mac_raw_ready,
    output wire mac_release,input wire mac_release_ready,
    output wire score_valid,input wire score_ready,output wire [127:0] scores,
    output wire [3:0] score_row,score_col,score_mask,
    output wire done,error
);
    localparam [3:0] IDLE=0,LOAD_Q=1,INIT=2,FEED_K=3,READ=4,DRAIN=5,RELEASE=6,FINISH=7,FAILED=8;
    reg [3:0] state;
    reg [2:0] q_group,k_group;
    reg [6:0] issued,received;
    reg [1:0] quad;
    reg [3:0] col;
    wire live=rst_n&&!clear;
    wire q_phase=state==LOAD_Q;
    wire k_phase=state==FEED_K;
    wire q_tail=q_group==6,k_tail=k_group==6;
    wire [1:0] last_quad=q_tail?2'd0:2'd3;
    wire [3:0] last_col=k_tail?4'd2:4'd15;
    wire response_ok=!qkv_error&&qkv_mask==((q_phase?q_tail:k_tail)?16'h0007:16'hffff);
    assign start_ready=live&&state==IDLE;
    assign qkv_read=live&&(q_phase||k_phase)&&issued<64;
    assign qkv_matrix=k_phase?2'd1:2'd0;
    assign qkv_index={q_phase?q_group:k_group,issued[5:0]};
    assign qkv_response_ready=live&&received<issued&&(q_phase||(k_phase&&(!response_ok||mac_ready)));
    wire issue=qkv_read&&qkv_ready;
    wire accept=qkv_valid&&qkv_response_ready;
    assign a_write=q_phase&&accept&&response_ok;
    assign a_enable=a_write||(k_phase&&issue);
    assign a_addr=10'd448+{4'd0,a_write?received[5:0]:issued[5:0]};
    assign a_wdata=qkv_data;
    assign mac_init=live&&state==INIT;
    assign mac_valid=live&&k_phase&&received<issued&&qkv_valid&&response_ok;
    assign mac_last=received==63;
    assign mac_a=a_rdata;
    assign mac_b=qkv_data;
    assign mac_read=live&&state==READ;
    assign mac_row={quad,2'd0};
    assign mac_col=col;
    assign mac_tag={10'd0,quad,col};
    assign score_valid=live&&(state==READ||state==DRAIN)&&mac_raw;
    assign mac_raw_ready=score_valid&&score_ready;
    assign scores=mac_raw_data;
    assign score_row={mac_raw_tag[5:4],2'd0};
    assign score_col=mac_raw_tag[3:0];
    assign score_mask=q_tail?4'b0111:4'b1111;
    assign mac_release=live&&state==RELEASE;
    assign done=live&&state==FINISH;
    assign error=live&&state==FAILED;

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin state<=IDLE;q_group<=0;k_group<=0;issued<=0;received<=0;quad<=0;col<=0;end
        else if(clear)state<=IDLE;
        else case(state)
            IDLE:if(start)begin
                q_group<=query_group;k_group<=key_group;issued<=0;received<=0;
                state<=query_group<7&&key_group<7?LOAD_Q:FAILED;
            end
            LOAD_Q,FEED_K:begin
                if(issue)issued<=issued+1'b1;
                if(accept)begin
                    received<=received+1'b1;
                    if(!response_ok)state<=FAILED;
                    else if(received==63)begin
                        state<=q_phase?INIT:READ;
                        quad<=0;col<=0;
                    end
                end
            end
            INIT:if(mac_init_ready)begin issued<=0;received<=0;state<=FEED_K;end
            READ:if(mac_read_ready)begin
                if(col==last_col)begin
                    col<=0;quad<=quad+1'b1;
                    if(quad==last_quad)state<=DRAIN;
                end else col<=col+1'b1;
            end
            DRAIN:if(mac_raw_ready)state<=RELEASE;
            RELEASE:if(mac_release_ready)state<=FINISH;
            FINISH:state<=IDLE;
            FAILED:begin end
            default:state<=FAILED;
        endcase
    end
endmodule
