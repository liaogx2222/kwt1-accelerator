// LN2 uses the original FC1 operand from A and the real FC2 writeback.
// The skip occupies S's upper space and unused words in the GELU tail.
module kwt_compact_ln2 (
    input wire clk,rst_n,clear,
    input wire aux_accept,
    input wire [14:0] aux_index,
    input wire [31:0] aux_data,
    input wire fc1_done,fc2_available,
    output reg skip_saved,
    output wire error,capture_phase,ln_phase,
    output wire a_read,
    output wire [9:0] a_addr,
    input wire [127:0] a_data,
    output wire [3:0] s_en,s_we,
    output wire [11:0] s_addr,
    output wire [63:0] s_wdata,
    input wire [63:0] s_rdata,
    output wire fc2_read,
    output wire [8:0] fc2_addr,
    input wire fc2_read_ready,fc2_valid,
    output wire fc2_ready,fc2_release,
    input wire [127:0] fc2_data,
    input wire [15:0] fc2_mask,
    output wire [6:0] row_index,
    output wire residual_valid,
    output wire [5:0] residual_index,
    output wire signed [15:0] residual_data,
    output wire stats_valid,
    output wire signed [21:0] stats_sum,
    output wire [35:0] stats_squares,
    output wire [63:0] stats_root,
    output wire [31:0] stats_inverse,
    output wire out_valid,
    input wire out_ready,
    output wire [5:0] out_index,
    output wire signed [7:0] out_data,
    output wire out_write
);
    localparam [3:0] IDLE=0,CAP_READ=1,CAP_LOW=2,CAP_HIGH=3,WAIT_FC2=4,
                     ROW_BEGIN=5,ROW_RUN=6,FINISH=7,FAILED=8;
    reg [3:0] state;
    reg [8:0] capture;
    reg [63:0] capture_high;
    reg [6:0] row,column;
    reg [55:0] write_pack;
    reg [7:0] ln_words;
    reg [2:0] r_words;
    reg bad_coeff,bad_mask;
    reg signed [31:0] gamma[0:63],beta[0:63];
    reg signed [31:0] residual_m0,residual_m1,output_m;
    reg [5:0] residual_shift,output_shift;
    reg [63:0] epsilon;
    wire live_rst_n=rst_n&&!clear;
    wire ln_coeff=aux_accept&&aux_index>=11748&&aux_index<11885;
    wire r_coeff=aux_accept&&aux_index>=14264&&aux_index<14270;
    wire [6:0] beta_offset=7'(aux_index-15'd11748);
    wire [6:0] gamma_offset=7'(aux_index-15'd11816);

    function automatic [11:0] skip_addr(input [9:0] word_index);
        skip_addr=word_index<512?12'd3584+{2'b0,word_index}:
                                 12'd3073+({3'b0,word_index[8:0]}<<1);
    endfunction
    wire tail_capture=capture>=384;
    wire capture_write=live_rst_n&&(state==CAP_LOW||state==CAP_HIGH);
    wire row_read=fc2_read&&fc2_read_ready;
    wire [9:0] row_skip_word={row[6:4],column[5:0],row[3]};
    wire [11:0] read_skip_addr=row>=96?12'd3072+{5'b0,column[5:0],1'b0}:skip_addr(row_skip_word);
    wire [2:0] skip_lane=row>=96?{1'b1,row[1:0]}:row[2:0];
    wire signed [7:0] x_skip=s_rdata[skip_lane*8+:8];
    wire signed [7:0] x_fc2=fc2_data[row[3:0]*8+:8];
    wire row_ready,inputs_ready,row_error;
    wire [5:0] gamma_index,beta_index;
    wire [9:0] out_addr={row,out_index[5:3]};
    assign a_read=live_rst_n&&state==CAP_READ;
    assign a_addr={1'b0,capture};
    assign fc2_read=live_rst_n&&state==ROW_RUN&&column<64;
    assign fc2_addr={row[6:4],column[5:0]};
    assign fc2_ready=state==ROW_RUN&&inputs_ready;
    assign fc2_release=live_rst_n&&state==FINISH;
    assign row_index=row;
    assign out_write=out_valid&&out_ready&&out_index[2:0]==7;
    assign capture_phase=state==CAP_READ||state==CAP_LOW||state==CAP_HIGH;
    assign ln_phase=state==ROW_BEGIN||state==ROW_RUN||state==FINISH;
    assign error=live_rst_n&&(bad_coeff||bad_mask||row_error||state==FAILED);
    assign s_we=capture_write?(tail_capture?4'b1100:4'b1111):out_write?4'b1111:4'b0;
    assign s_en=row_read?4'b1111:s_we;
    assign s_addr=capture_write?(tail_capture?12'd3072+{5'b0,capture[5:0],1'b0}:
                                 skip_addr({capture,state==CAP_HIGH})):
                  row_read?read_skip_addr:{2'b0,out_addr};
    assign s_wdata=capture_write?(tail_capture?{8'b0,a_data[23:0],32'b0}:
                                  state==CAP_HIGH?capture_high:a_data[63:0]):
                   {out_data,write_pack};

    kwt_compact_ln_row row_core (
        .clk(clk),.rst_n(live_rst_n),.start(state==ROW_BEGIN),.start_ready(row_ready),
        .in_valid(state==ROW_RUN&&fc2_valid),.in_ready(inputs_ready),.skip_code(x_skip),.fc2_code(x_fc2),
        .residual_m0(residual_m0),.residual_m1(residual_m1),.residual_shift(residual_shift),
        .output_m(output_m),.output_shift(output_shift),.epsilon(epsilon),
        .gamma_index(gamma_index),.beta_index(beta_index),.gamma(gamma[gamma_index]),.beta(beta[beta_index]),
        .residual_valid(residual_valid),.residual_index(residual_index),.residual_data(residual_data),
        .stats_valid(stats_valid),.stats_sum(stats_sum),.stats_squares(stats_squares),
        .stats_root(stats_root),.stats_inverse(stats_inverse),
        .out_valid(out_valid),.out_ready(out_ready),.out_index(out_index),.out_data(out_data),.error(row_error));

    always @(posedge clk) if(live_rst_n&&ln_coeff) begin
        if(aux_index<11812) beta[beta_offset[5:0]]<=aux_data;
        if(aux_index>=11816&&aux_index<11880) gamma[gamma_offset[5:0]]<=aux_data;
    end
    always @(posedge clk or negedge live_rst_n) begin
        if(!live_rst_n) begin
            state<=IDLE;capture<=0;capture_high<=0;row<=0;column<=0;write_pack<=0;skip_saved<=0;
            ln_words<=0;r_words<=0;bad_coeff<=0;bad_mask<=0;
            residual_m0<=0;residual_m1<=0;residual_shift<=0;output_m<=0;output_shift<=0;epsilon<=0;
        end else begin
            if(ln_coeff) begin
                if(aux_index!=15'd11748+{7'b0,ln_words}||ln_words>=137)bad_coeff<=1;
                else ln_words<=ln_words+1'b1;
                case(aux_index)
                    11812:epsilon[31:0]<=aux_data;
                    11813:epsilon[63:32]<=aux_data;
                    11880:output_m<=aux_data;
                    11884:begin output_shift<=aux_data[5:0]; if(aux_data>63)bad_coeff<=1; end
                    default:begin end
                endcase
            end
            if(r_coeff) begin
                if(aux_index!=15'd14264+{12'b0,r_words}||r_words>=6)bad_coeff<=1;
                else r_words<=r_words+1'b1;
                case(r_words)
                    0:residual_m0<=aux_data;
                    1:if(aux_data!={32{residual_m0[31]}})bad_coeff<=1;
                    2:residual_m1<=aux_data;
                    3:if(aux_data!={32{residual_m1[31]}})bad_coeff<=1;
                    4:begin residual_shift<=aux_data[5:0]; if(aux_data>63)bad_coeff<=1; end
                    5:if(aux_data!=0)bad_coeff<=1;
                    default:begin end
                endcase
            end
            if(fc2_valid&&fc2_ready&&!fc2_mask[row[3:0]])bad_mask<=1;
            if(out_valid&&out_ready&&out_index[2:0]!=7)write_pack[out_index[2:0]*8+:8]<=out_data;
            case(state)
                IDLE: if(fc1_done)begin
                    capture<=0;skip_saved<=0;
                    state<=ln_words==137&&r_words==6&&epsilon!=0?CAP_READ:FAILED;
                end
                CAP_READ:state<=CAP_LOW;
                CAP_LOW:if(tail_capture)begin
                    if(capture==447)begin skip_saved<=1;state<=WAIT_FC2;end
                    else begin capture<=capture+1'b1;state<=CAP_READ;end
                end else begin capture_high<=a_data[127:64];state<=CAP_HIGH;end
                CAP_HIGH:begin capture<=capture+1'b1;state<=CAP_READ;end
                WAIT_FC2:if(fc2_available)begin row<=0;state<=ROW_BEGIN;end
                ROW_BEGIN:if(row_ready)begin column<=0;state<=ROW_RUN;end
                ROW_RUN:begin
                    if(row_read)column<=column+1'b1;
                    if(out_valid&&out_ready&&out_index==63)begin
                        if(row==98)state<=FINISH;
                        else begin row<=row+1'b1;state<=ROW_BEGIN;end
                    end
                end
                FINISH:state<=IDLE;
                FAILED:begin end
                default:state<=FAILED;
            endcase
        end
    end
endmodule
