module rne_dense_miter(
    input wire clk,rst_n,req_valid,resp_ready,req_error,
    input wire [63:0] value,input wire signed [7:0] shift,input wire [15:0] tag,
    output wire legal,same
);
    wire r0,r1,v0,v1,e0,e1;
    wire [63:0] d0,d1;
    wire [15:0] t0,t1;
    kwt_rne_dense_right specialized(clk,rst_n,req_valid,r0,value,shift,6'd8,req_error,tag,v0,resp_ready,d0,e0,t0);
    rne_pipe generic(clk,rst_n,req_valid,r1,value,shift,6'd8,req_error,tag,v1,resp_ready,d1,e1,t1);
    assign legal=shift>=38&&shift<=48;
    assign same=(r0==r1)&&(v0==v1)&&(!v0||({d0,e0,t0}=={d1,e1,t1}));
endmodule
