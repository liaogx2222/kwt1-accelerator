// Schedule a query group's real QK outputs through physical B and Softmax.
module kwt_compact_qk_softmax (
    input wire clk,rst_n,clear,start,tail,
    output wire qk_open,
    input wire qk_end,qk_valid,
    output wire qk_ready,
    input wire [1:0] qk_quad,
    input wire [6:0] qk_key,
    input wire [3:0] qk_mask,
    input wire [127:0] qk_scores,
    input wire [31:0] score_m,
    input wire [5:0] score_shift,
    output wire exp_valid,input wire exp_ready,output wire [12:0] exp_index,
    input wire exp_resp_valid,output wire exp_resp_ready,input wire [20:0] exp_value,input wire exp_error,
    output wire [7:0] b_en,b_we,output wire [9:0] b_addr,
    output wire [127:0] b_wdata,input wire [127:0] b_rdata,
    output wire score_fire,output wire signed [31:0] score_data,
    output wire prob_valid,input wire prob_ready,
    output reg [3:0] prob_row,output wire [6:0] prob_index,output wire [15:0] prob,
    output wire done,error
);
    localparam [2:0] IDLE=0,WRITE=1,START_ROW=2,ROW=3,FINISH=4;
    reg [2:0] state;
    reg [6:0] requested;
    reg tail_group;
    wire live=rst_n&&!clear;
    wire store_ready,store_error,b_read_ready,b_score_valid,sm_ready,sm_score_ready,sm_error;
    wire start_store=live&&start&&state==IDLE&&store_ready;
    wire b_read=live&&state==ROW&&requested<99;
    assign qk_open=live&&state==WRITE;
    assign done=live&&state==FINISH;
    assign error=store_error||sm_error;
    assign score_fire=b_score_valid&&sm_score_ready;

    kwt_compact_qk_score_store storage (
        .clk(clk),.rst_n(rst_n),.clear(clear),.start(start_store),.tail(tail),.start_ready(store_ready),
        .score_valid(qk_valid),.score_ready(qk_ready),.score_quad(qk_quad),.score_key(qk_key),
        .score_mask(qk_mask),.scores(qk_scores),.close_group(qk_open&&qk_end),.release_group(done),
        .available(),.error(store_error),.read_valid(b_read),.read_ready(b_read_ready),.read_row(prob_row),
        .read_key(requested),.response_valid(b_score_valid),.response_ready(sm_score_ready),.response_score(score_data),
        .bank_en(b_en),.bank_we(b_we),.bank_addr(b_addr),.bank_wdata(b_wdata),.bank_rdata(b_rdata));

    kwt_compact_softmax_row row_kernel (
        .clk(clk),.rst_n(rst_n),.clear(clear),.start(state==START_ROW),.start_ready(sm_ready),
        .score_m(score_m),.score_shift(score_shift),.score_valid(b_score_valid),.score_ready(sm_score_ready),.score(score_data),
        .exp_valid(exp_valid),.exp_ready(exp_ready),.exp_index(exp_index),.exp_resp_valid(exp_resp_valid),
        .exp_resp_ready(exp_resp_ready),.exp_value(exp_value),.exp_error(exp_error),
        .prob_valid(prob_valid),.prob_ready(prob_ready),.prob_index(prob_index),.prob(prob),.error(sm_error));

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin state<=IDLE;requested<=0;prob_row<=0;tail_group<=0;end
        else if(clear)state<=IDLE;
        else case(state)
            IDLE:if(start_store)begin state<=WRITE;prob_row<=0;tail_group<=tail;end
            WRITE:if(qk_end)state<=START_ROW;
            START_ROW:if(sm_ready)begin requested<=0;state<=ROW;end
            ROW:begin
                if(b_read&&b_read_ready)requested<=requested+1'b1;
                if(prob_valid&&prob_ready&&prob_index==98)begin
                    if(prob_row==(tail_group?4'd2:4'd15))state<=FINISH;
                    else begin prob_row<=prob_row+1'b1;state<=START_ROW;end
                end
            end
            FINISH:state<=IDLE;
            default:state<=IDLE;
        endcase
    end
endmodule
