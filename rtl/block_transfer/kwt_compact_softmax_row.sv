// Exact 99-key integer Softmax. The exp interface is the in-order port of
// kwt_compact_exp_cache. The probabilities use the canonical U16 contract.
module kwt_compact_softmax_row (
    input wire clk,rst_n,clear,
    input wire start,output wire start_ready,
    input wire [31:0] score_m,input wire [5:0] score_shift,
    input wire score_valid,output wire score_ready,input wire signed [31:0] score,
    output wire exp_valid,input wire exp_ready,output wire [12:0] exp_index,
    input wire exp_resp_valid,output wire exp_resp_ready,input wire [20:0] exp_value,input wire exp_error,
    output wire prob_valid,input wire prob_ready,output wire [6:0] prob_index,output wire [15:0] prob,
    output wire error
);
    localparam [2:0] IDLE=0,SCORES=1,EXP=2,DIV_REQ=3,DIV_WAIT=4,OUTPUTS=5,FAILED=6;
    reg [2:0] state;
    reg [6:0] input_count,issued,received;
    reg [31:0] multiplier;
    reg [5:0] shift;
    reg signed [31:0] maximum,scores[0:98];
    reg [20:0] exponentials[0:98];
    reg [26:0] denominator;
    reg [27:0] reciprocal;
    wire live=rst_n&&!clear;
    wire signed [32:0] difference={maximum[31],maximum}-{scores[issued][31],scores[issued]};
    wire [63:0] product=difference[31:0]*multiplier;
    wire [63:0] shifted=product>>shift;
    wire [63:0] half=64'd1<<(shift-1'b1);
    wire [63:0] remainder=product&((64'd1<<shift)-1'b1);
    wire [63:0] rounded=shifted+{63'd0,shift!=0&&(remainder>half||(remainder==half&&shifted[0]))};
    assign start_ready=live&&state==IDLE;
    assign score_ready=live&&state==SCORES;
    assign exp_valid=live&&state==EXP&&issued<99;
    assign exp_index=rounded>=4096?13'd4096:rounded[12:0];
    assign exp_resp_ready=live&&state==EXP&&received<issued;
    assign error=live&&state==FAILED;

    wire div_ready,div_valid,div_error;
    wire [63:0] quotient;
    wire [63:0] div_numerator=64'h800000000000+{37'd0,denominator}-1'b1;
    kwt_iterative divider(clk,live,state==DIV_REQ,div_ready,1'b0,div_numerator,{37'd0,denominator},
                         div_valid,state==DIV_WAIT,quotient,,div_error);

    reg [2:0] valid_pipe;
    reg [6:0] tag0,tag1,tag2;
    reg [48:0] exp_recip;
    reg [36:0] numerator0,numerator1;
    reg [15:0] estimate,probability;
    wire [63:0] exp_recip_extended={15'd0,exp_recip};
    wire [63:0] scaled=(exp_recip_extended<<16)-exp_recip_extended;
    wire [42:0] estimated_product=estimate*denominator;
    wire correction=estimated_product>{6'd0,numerator1};
    wire [15:0] corrected=estimate-{15'd0,correction};
    wire [42:0] corrected_product=correction?estimated_product-{16'd0,denominator}:estimated_product;
    wire [26:0] rem=27'({6'd0,numerator1}-corrected_product);
    wire [26:0] other=denominator-rem;
    wire increment=rem>other||(rem==other&&corrected[0]);
    wire advance=state==OUTPUTS&&(!valid_pipe[2]||prob_ready);
    assign prob_valid=live&&state==OUTPUTS&&valid_pipe[2];
    assign prob_index=tag2;
    assign prob=probability;

    always @(posedge clk) begin
        if(score_valid&&score_ready)scores[input_count]<=score;
        if(exp_resp_valid&&exp_resp_ready)exponentials[received]<=exp_value;
    end

    always @(posedge clk or negedge live) begin
        if(!live) begin
            state<=IDLE;input_count<=0;issued<=0;received<=0;multiplier<=0;shift<=0;
            maximum<=0;denominator<=0;reciprocal<=0;valid_pipe<=0;tag0<=0;tag1<=0;tag2<=0;
            exp_recip<=0;numerator0<=0;numerator1<=0;estimate<=0;probability<=0;
        end else case(state)
            IDLE: if(start)begin
                state<=SCORES;input_count<=0;issued<=0;received<=0;denominator<=0;
                maximum<=32'sh80000000;multiplier<=score_m;shift<=score_shift;
            end
            SCORES: if(score_valid&&score_ready)begin
                if(score>maximum)maximum<=score;
                if(input_count==98)state<=EXP;
                else input_count<=input_count+1'b1;
            end
            EXP: begin
                if(exp_valid&&exp_ready)issued<=issued+1'b1;
                if(exp_resp_valid&&exp_resp_ready)begin
                    denominator<=denominator+{6'd0,exp_value};
                    received<=received+1'b1;
                    if(exp_error||exp_value>21'h100000)state<=FAILED;
                    else if(received==98)state<=DIV_REQ;
                end
            end
            DIV_REQ: if(div_ready)state<=DIV_WAIT;
            DIV_WAIT: if(div_valid)begin
                reciprocal<=quotient[27:0];issued<=0;valid_pipe<=0;
                state<=div_error||denominator<27'h100000||quotient[63:28]!=0?FAILED:OUTPUTS;
            end
            OUTPUTS: if(advance)begin
                valid_pipe<={valid_pipe[1:0],issued<99};
                if(issued<99)begin
                    exp_recip<=exponentials[issued]*reciprocal;
                    numerator0<={exponentials[issued],16'd0}-{16'd0,exponentials[issued]};
                    tag0<=issued;issued<=issued+1'b1;
                end
                if(valid_pipe[0])begin estimate<=scaled[62:47];numerator1<=numerator0;tag1<=tag0;end
                if(valid_pipe[1])begin probability<=corrected+{15'd0,increment};tag2<=tag1;end
                if(prob_valid&&tag2==98)state<=IDLE;
            end
            FAILED: begin end
            default:state<=FAILED;
        endcase
    end
endmodule
