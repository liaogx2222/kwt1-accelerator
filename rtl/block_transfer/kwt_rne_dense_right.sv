// Dense profile RNE. Shift 38..48 and symmetric signed int8 saturation.
// One elastic stage with the same response/tag contract as rne_pipe.
module kwt_rne_dense_right #(parameter TAG_W=16)(
    input wire clk,rst_n,req_valid,output wire req_ready,
    input wire [63:0] req_a,input wire signed [7:0] req_shift,
    input wire [5:0] req_sat_bits,input wire req_error,input wire [TAG_W-1:0] req_tag,
    output reg resp_valid,input wire resp_ready,output reg [63:0] resp_result,
    output reg resp_error,output reg [TAG_W-1:0] resp_tag
);
    wire [63:0] magnitude = req_a[63] ? -req_a : req_a;
    wire [3:0] shift_delta = req_shift[3:0]-4'd6;
    wire [26:0] scaled = magnitude[63:37] >> shift_delta;
    wire [9:0] sticky_mask = (10'd1 << shift_delta)-1'b1;
    wire sticky = (|magnitude[36:0]) || (|(magnitude[46:37]&sticky_mask));
    wire increment = scaled[0] && (sticky || scaled[1]);
    wire [26:0] rounded = {1'b0,scaled[26:1]} + {26'b0,increment};
    wire [6:0] magnitude8 = rounded>127 ? 7'd127 : rounded[6:0];
    wire [63:0] signed_result = req_a[63] ? -{57'b0,magnitude8} : {57'b0,magnitude8};
    wire bad = req_error || req_sat_bits!=8 || req_shift<38 || req_shift>48 ||
               req_a==64'h8000000000000000;
    assign req_ready=rst_n&&(!resp_valid||resp_ready);
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin resp_valid<=0; resp_result<=0; resp_error<=0; resp_tag<=0; end
        else if(req_ready) begin
            resp_valid<=req_valid;
            if(req_valid) begin
                resp_result<=bad?0:signed_result;
                resp_error<=bad;
                resp_tag<=req_tag;
            end
        end
    end
endmodule
