// ceil(2^47 / d), for 2^20 <= d < 2^27. The leading 20 numerator
// bits are below the divisor, so start with that known remainder and
// resolve the remaining 28 quotient bits two at a time.
module kwt_compact_softmax_recip (
    input wire clk,rst_n,
    input wire request,output wire ready,
    input wire [26:0] denominator,
    output reg valid,input wire accept,
    output reg [27:0] quotient,output reg error
);
    reg [3:0] remaining;
    reg [26:0] divisor,remainder;
    reg [27:0] bits,partial;
    wire [28:0] trial={remainder,bits[27:26]};
    wire [28:0] once={2'd0,divisor};
    wire [28:0] twice=once<<1;
    wire [28:0] thrice=once+twice;
    wire [1:0] digit=trial>=thrice?2'd3:trial>=twice?2'd2:trial>=once?2'd1:2'd0;
    wire [28:0] reduce_by=digit==3?thrice:digit==2?twice:digit==1?once:29'd0;
    wire [28:0] reduced=trial-reduce_by;
    assign ready=rst_n&&remaining==0&&(!valid||accept);

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin remaining<=0;divisor<=0;remainder<=0;bits<=0;partial<=0;valid<=0;quotient<=0;error<=0;end
        else begin
            if(valid&&accept)valid<=0;
            if(request&&ready)begin
                if(denominator<27'h100000)begin valid<=1;error<=1;quotient<=0;end
                else begin
                    remaining<=14;divisor<=denominator;remainder<=27'h80000;
                    bits<={1'b0,denominator}-1'b1;partial<=0;error<=0;
                end
            end else if(remaining!=0)begin
                remaining<=remaining-1'b1;
                remainder<=reduced[26:0];bits<=bits<<2;partial<={partial[25:0],digit};
                if(remaining==1)begin valid<=1;quotient<={partial[25:0],digit};end
            end
        end
    end
endmodule
