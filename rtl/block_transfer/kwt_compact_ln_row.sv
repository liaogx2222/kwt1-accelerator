// One exact residual/LN row. Two residual products, a shared iterative
// sqrt/divider, and an elastic one-code-per-cycle affine pipeline.
module kwt_compact_ln_row (
    input wire clk,rst_n,
    input wire start, output wire start_ready,
    input wire in_valid, output wire in_ready,
    input wire signed [7:0] skip_code,fc2_code,
    input wire signed [31:0] residual_m0,residual_m1,output_m,
    input wire [5:0] residual_shift,output_shift,
    input wire [63:0] epsilon,
    output wire [5:0] gamma_index,beta_index,
    input wire signed [31:0] gamma,beta,
    output wire residual_valid,
    output wire [5:0] residual_index,
    output wire signed [15:0] residual_data,
    output wire stats_valid,
    output wire signed [21:0] stats_sum,
    output wire [35:0] stats_squares,
    output wire [63:0] stats_root,
    output wire [31:0] stats_inverse,
    output wire out_valid,input wire out_ready,
    output wire [5:0] out_index,
    output wire signed [7:0] out_data,
    output wire error
);
    function automatic signed [63:0] rne(input signed [63:0] x,input [5:0] s);
        reg [63:0] mag,q,low,half;
        begin
            mag=x[63]?-x:x;
            q=mag>>s;
            half=64'd1<<(s-1'b1);
            low=mag&((64'd1<<s)-1'b1);
            if(s!=0&&(low>half||(low==half&&q[0]))) q=q+1'b1;
            rne=x[63]?-$signed(q):$signed(q);
        end
    endfunction
    function automatic signed [15:0] sat16(input signed [63:0] x);
        sat16=x>32767?16'sd32767:x< -32767?-16'sd32767:x[15:0];
    endfunction
    function automatic signed [7:0] sat8(input signed [63:0] x);
        sat8=x>127?8'sd127:x< -127?-8'sd127:x[7:0];
    endfunction
    localparam [3:0] IDLE=0,INPUTS=1,STATS=2,ROOT_REQ=3,ROOT_WAIT=4,
                     DIV_REQ=5,DIV_WAIT=6,AFFINE=7,FAILED=8;
    reg [3:0] state;
    reg [6:0] issued;
    reg [2:0] rv;
    reg [5:0] rt0,rt1,rt2;
    reg signed [39:0] p0,p1;
    reg signed [15:0] rounded_res,stat_res;
    reg [31:0] square;
    reg signed [15:0] row[0:63];
    reg signed [21:0] sum;
    reg [35:0] squares;
    reg [63:0] h,root;
    reg [31:0] inverse;
    reg stat_pulse;
    wire signed [40:0] residual_product_sum={p0[39],p0}+{p1[39],p1};
    wire signed [43:0] sum_squared=sum*sum;
    wire [63:0] variance_h=(({28'b0,squares}<<6)-{20'b0,sum_squared})<<16;
    wire iter_ready,iter_valid,iter_error;
    wire [63:0] iter_result,iter_remainder;
    wire [63:0] rounded_inverse=iter_result+
        {63'b0,(iter_remainder>root-iter_remainder ||
                 (iter_remainder==root-iter_remainder && iter_result[0]))};
    wire iter_sqrt=state==ROOT_REQ;
    kwt_iterative iterative(clk,rst_n,state==ROOT_REQ||state==DIV_REQ,iter_ready,
        iter_sqrt,iter_sqrt?h:64'h10000000000,root,iter_valid,
        state==ROOT_WAIT||state==DIV_WAIT,iter_result,iter_remainder,iter_error);
    assign start_ready=rst_n&&state==IDLE;
    assign in_ready=rst_n&&state==INPUTS&&issued<64;
    assign residual_valid=rst_n&&state==INPUTS&&rv[2];
    assign residual_index=rt2;
    assign residual_data=stat_res;
    assign stats_valid=rst_n&&stat_pulse;
    assign stats_sum=sum;
    assign stats_squares=squares;
    assign stats_root=root;
    assign stats_inverse=inverse;
    assign error=rst_n&&state==FAILED;

    reg [5:0] av;
    reg [5:0] at0,at1,at2,at3,at4,at5;
    reg signed [63:0] normalized_product,affine_product,output_product;
    reg signed [31:0] normalized,affine;
    reg signed [7:0] code;
    wire advance=state==AFFINE&&(!av[5]||out_ready);
    wire signed [22:0] center=$signed({row[issued[5:0]],6'b0})-
                              $signed({sum[21],sum});
    wire signed [63:0] normalized_next=rne(normalized_product,6'd18);
    wire signed [63:0] affine_next=rne(affine_product,6'd14)+{{32{beta[31]}},beta};
    assign gamma_index=at1;
    assign beta_index=at2;
    assign out_valid=rst_n&&state==AFFINE&&av[5];
    assign out_index=at5;
    assign out_data=code;

    always @(posedge clk) if(rst_n&&state==INPUTS&&rv[2]) row[rt2]<=stat_res;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE; issued<=0; rv<=0; rt0<=0; rt1<=0; rt2<=0; p0<=0;p1<=0;
            rounded_res<=0; stat_res<=0; square<=0; sum<=0; squares<=0;
            h<=0; root<=0; inverse<=0; stat_pulse<=0; av<=0;
            at0<=0;at1<=0;at2<=0;at3<=0;at4<=0;at5<=0;
            normalized_product<=0;affine_product<=0;output_product<=0;normalized<=0;affine<=0;code<=0;
        end else begin
            stat_pulse<=0;
            case(state)
                IDLE: if(start) begin issued<=0;rv<=0;sum<=0;squares<=0;state<=INPUTS; end
                INPUTS: begin
                    rv<={rv[1:0],in_valid&&in_ready};
                    if(in_valid&&in_ready) begin
                        p0<=skip_code*residual_m0; p1<=fc2_code*residual_m1;
                        rt0<=issued[5:0]; issued<=issued+1'b1;
                    end
                    if(rv[0]) begin
                        rounded_res<=sat16(rne({{23{residual_product_sum[40]}},residual_product_sum},residual_shift));
                        rt1<=rt0;
                    end
                    if(rv[1]) begin
                        stat_res<=rounded_res;square<=rounded_res*rounded_res;rt2<=rt1;
                    end
                    if(rv[2]) begin
                        sum<=sum+{{6{stat_res[15]}},stat_res};
                        squares<=squares+{4'b0,square};
                        if(rt2==63)state<=STATS;
                    end
                end
                STATS: begin h<=variance_h+epsilon; state<=ROOT_REQ; end
                ROOT_REQ: if(iter_ready)state<=ROOT_WAIT;
                ROOT_WAIT: if(iter_valid) begin
                    root<=iter_result;state<=iter_error||iter_result==0?FAILED:DIV_REQ;
                end
                DIV_REQ: if(iter_ready)state<=DIV_WAIT;
                DIV_WAIT: if(iter_valid) begin
                    inverse<=rounded_inverse[31:0]; issued<=0; av<=0;
                    stat_pulse<=!iter_error&&rounded_inverse[63:32]==0;
                    state<=iter_error||rounded_inverse[63:32]!=0?FAILED:AFFINE;
                end
                AFFINE: if(advance) begin
                    av<={av[4:0],issued<64};
                    if(issued<64)begin
                        normalized_product<=center*$signed({1'b0,inverse});
                        at0<=issued[5:0];issued<=issued+1'b1;
                    end
                    if(av[0])begin normalized<=normalized_next[31:0];at1<=at0;end
                    if(av[1])begin affine_product<=normalized*gamma;at2<=at1;end
                    if(av[2])begin affine<=affine_next[31:0];at3<=at2;end
                    if(av[3])begin output_product<=affine*output_m;at4<=at3;end
                    if(av[4])begin code<=sat8(rne(output_product,output_shift));at5<=at4;end
                    if((av[0]&&normalized_next!={{32{normalized_next[31]}},normalized_next[31:0]})||
                       (av[2]&&affine_next!={{32{affine_next[31]}},affine_next[31:0]})) state<=FAILED;
                    else if(out_valid&&at5==63)state<=IDLE;
                end
                FAILED:begin end
                default:state<=FAILED;
            endcase
        end
    end
endmodule
