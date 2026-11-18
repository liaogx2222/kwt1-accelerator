// Reorder the physical S reads in 16-row x 8-channel tiles. After each
// tile, write eight A vectors in the layout used by the next S8 Q/K/V.
module kwt_compact_ln2_forward (
    input wire clk,rst_n,abort,
    input wire [15:0] epoch,
    input wire [9:0] read_index,
    output wire [9:0] s_index,
    input wire valid,
    output wire ready,
    input wire [63:0] data,
    output wire write_a,
    output wire [9:0] a_index,
    output wire [127:0] a_data,
    output wire available
);
    reg [2:0] group_index,block_index,channel;
    reg [3:0] lane;
    reg writing,complete;
    reg [15:0] next_epoch;
    reg [127:0] tile [0:7];
    wire live=rst_n&&!abort;
    wire tail=group_index==6;
    wire last_lane=tail?lane==2:lane==15;
    wire [4:0] tail_read=read_index[4:0];
    wire [2:0] tail_block=3'(tail_read/5'd3);
    wire [1:0] tail_lane=2'(tail_read%5'd3);
    assign s_index=read_index<768?{read_index[9:7],read_index[3:0],read_index[6:4]}:
                                  {3'd6,2'b0,tail_lane,tail_block};
    assign ready=live&&!writing;
    assign write_a=live&&writing;
    assign a_index={1'b0,group_index,block_index,channel};
    assign a_data=tail?{104'b0,tile[channel][23:0]}:tile[channel];
    assign available=live&&complete&&next_epoch==epoch;

    always @(posedge clk) if(valid&&ready) begin
        for(integer i=0;i<8;i=i+1)tile[i][lane*8+:8]<=data[i*8+:8];
    end

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            group_index<=0;block_index<=0;channel<=0;lane<=0;
            writing<=0;complete<=0;next_epoch<=0;
        end else if(abort) begin
            group_index<=0;block_index<=0;channel<=0;lane<=0;
            writing<=0;complete<=0;
        end else if(valid&&ready) begin
            complete<=0;
            if(last_lane)begin lane<=0;writing<=1;channel<=0;end
            else lane<=lane+1'b1;
        end else if(write_a) begin
            if(channel==7)begin
                writing<=0;
                block_index<=block_index+1'b1;
                if(block_index==7)begin
                    if(tail)begin group_index<=0;complete<=1;next_epoch<=epoch+16'd1;end
                    else group_index<=group_index+1'b1;
                end
            end else channel<=channel+1'b1;
        end
    end
endmodule
