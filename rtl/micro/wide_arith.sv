// Functional microprototype: one outstanding request, held response.
// Not a pipelined II=1 implementation or a PPA claim.
module wide_arith (
    input logic clk, rst_n,
    input logic req_valid, output logic req_ready,
    input logic [2:0] req_op,
    input logic [63:0] req_a, req_b,
    input logic signed [7:0] req_shift,
    output logic resp_valid, input logic resp_ready,
    output logic [63:0] resp_result, resp_remainder,
    output logic resp_error
);
    localparam IDLE=0, WAIT_RESULT=1, DIVIDE=2, SQRT=3;
    logic [1:0] state;
    logic [6:0] count;
    logic [63:0] pending, dividend, divisor, quotient;
    logic [64:0] remainder_d, trial_d;
    logic [65:0] remainder_s, trial_s, shifted_s;
    logic [63:0] radicand, root;
    logic [63:0] magnitude, qround, remround, maskround, halfround;
    logic [127:0] wide_shift;
    integer shift_abs;
    assign req_ready=rst_n && state==IDLE && (!resp_valid || resp_ready);
    always @* begin
        trial_d={remainder_d[63:0],dividend[63]};
        shifted_s=(remainder_s<<2)|{64'b0,radicand[63:62]};
        trial_s=({2'b0,root}<<2)|66'd1;
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE;count<=0;resp_valid<=0;resp_result<=0;
            resp_remainder<=0;resp_error<=0;pending<=0;
            dividend<=0;divisor<=0;quotient<=0;remainder_d<=0;
            remainder_s<=0;radicand<=0;root<=0;
        end else begin
            if (resp_valid && resp_ready) resp_valid<=0;
            if (req_valid && req_ready) begin
                resp_error<=0;resp_remainder<=0;count<=1;state<=WAIT_RESULT;
                case (req_op)
                    0: begin // signed 32 x signed 32 -> signed 64
                        pending<=$signed(req_a[31:0])*$signed(req_b[31:0]);count<=3;
                        if (req_a[63:32]!={32{req_a[31]}} || req_b[63:32]!={32{req_b[31]}}) begin
                            pending<=0;resp_error<=1;
                        end
                    end
                    1: begin // unsigned 32 x unsigned 32 -> unsigned 64
                        pending<=req_a[31:0]*req_b[31:0];count<=3;
                        if (|req_a[63:32] || |req_b[63:32]) begin pending<=0;resp_error<=1;end
                    end
                    2: begin // signed RNE shift, no asymmetric INT64_MIN domain
                        magnitude=req_a[63] ? (~req_a+64'd1) : req_a;
                        qround=0;remround=0;maskround=0;halfround=0;wide_shift=0;
                        shift_abs=-$signed(req_shift);
                        if (req_a==64'h8000000000000000) begin pending<=0;resp_error<=1;end
                        else if (req_shift>=0) begin
                            if (req_shift>63) qround=0;
                            else if (req_shift==0) qround=magnitude;
                            else begin
                                maskround=(64'd1<<req_shift)-1;
                                halfround=64'd1<<(req_shift-1);
                                remround=magnitude&maskround;qround=magnitude>>req_shift;
                                if (remround>halfround || (remround==halfround && qround[0])) qround=qround+1;
                            end
                            pending<=req_a[63] ? (~qround+64'd1) : qround;
                        end else begin
                            wide_shift={64'b0,magnitude}<<shift_abs;
                            if (magnitude==0) pending<=0;
                            else if (shift_abs>127 || |wide_shift[127:63]) begin pending<=0;resp_error<=1;end
                            else pending<=req_a[63] ? (~wide_shift[63:0]+64'd1) : wide_shift[63:0];
                        end
                    end
                    3: begin // unsigned restoring divide, 64 steps
                        if (req_b==0) begin pending<=0;resp_error<=1;end
                        else begin
                            // First restoring step on acceptance: L=64 edges.
                            state<=DIVIDE;count<=63;dividend<=req_a<<1;divisor<=req_b;
                            quotient<=({63'd0,req_a[63]}>=req_b);
                            remainder_d<=({63'd0,req_a[63]}>=req_b) ? ({1'b0,63'd0,req_a[63]}-{1'b0,req_b}) : {64'd0,req_a[63]};
                        end
                    end
                    4: begin // unsigned integer sqrt, 32 radix-four steps
                        // First radix-four step on acceptance: L=32 edges.
                        state<=SQRT;count<=31;radicand<=req_a<<2;
                        root<=req_a[63:62]>=1;
                        remainder_s<=req_a[63:62]>=1 ? {64'd0,req_a[63:62]}-66'd1 : {64'd0,req_a[63:62]};
                    end
                    default:begin pending<=0;resp_error<=1;end
                endcase
            end else if (state==WAIT_RESULT) begin
                if (count==1) begin
                    resp_result<=pending;resp_valid<=1;state<=IDLE;
                end else count<=count-1;
            end else if (state==DIVIDE) begin
                dividend<=dividend<<1;
                if (trial_d>={1'b0,divisor}) begin
                    remainder_d<=trial_d-{1'b0,divisor};quotient<=(quotient<<1)|64'd1;
                end else begin remainder_d<=trial_d;quotient<=quotient<<1;end
                if (count==1) begin
                    resp_result<=(quotient<<1)|(trial_d>={1'b0,divisor});
                    resp_remainder<=trial_d>={1'b0,divisor} ? trial_d-{1'b0,divisor} : trial_d;
                    resp_valid<=1;state<=IDLE;
                end else count<=count-1;
            end else if (state==SQRT) begin
                radicand<=radicand<<2;
                if (shifted_s>=trial_s) begin remainder_s<=shifted_s-trial_s;root<=(root<<1)|64'd1;end
                else begin remainder_s<=shifted_s;root<=root<<1;end
                if (count==1) begin
                    resp_result<=(root<<1)|(shifted_s>=trial_s);
                    resp_remainder<=shifted_s>=trial_s ? shifted_s-trial_s : shifted_s;
                    resp_valid<=1;state<=IDLE;
                end else count<=count-1;
            end
        end
    end
endmodule
