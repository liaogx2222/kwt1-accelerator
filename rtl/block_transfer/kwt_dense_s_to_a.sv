// Copy packed 16-row vectors from four 16-bit S banks to eight A banks.
// The two S reads overlap the preceding A write where possible.
module kwt_dense_s_to_a (
    input wire clk,rst_n,
    input wire start,
    output wire idle,done,
    input wire [11:0] start_addr,
    input wire [8:0] vectors,
    output wire s_read,
    output wire [11:0] s_addr,
    input wire [63:0] s_data,
    output wire a_write,
    output wire [8:0] a_addr,
    output wire [127:0] a_data
);
    localparam [1:0] IDLE=0, LOW=1, HIGH=2, WRITE=3;
    reg [1:0] state;
    reg [11:0] address;
    reg [8:0] index,limit;
    reg [63:0] low_data;
    wire last=index==limit;
    assign idle=state==IDLE;
    assign done=rst_n&&state==WRITE&&last;
    assign s_read=rst_n&&(state==LOW || state==HIGH || (state==WRITE&&!last));
    assign s_addr=address;
    assign a_write=rst_n&&state==WRITE;
    assign a_addr=index;
    assign a_data={s_data,low_data};
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin state<=IDLE; address<=0; index<=0; limit<=0; low_data<=0; end
        else begin
            if(s_read) address<=address+1'b1;
            case(state)
                IDLE: if(start&&vectors!=0) begin
                    address<=start_addr; index<=0; limit<=vectors-1'b1; state<=LOW;
                end
                LOW: state<=HIGH;
                HIGH: begin low_data<=s_data; state<=WRITE; end
                WRITE: begin index<=index+1'b1; state<=last?IDLE:HIGH; end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
