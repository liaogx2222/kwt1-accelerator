"""Write a static-PE coding variant of OUR arithmetic partition, unchanged IO."""
from pathlib import Path
from local_tools import ROOT

PREFIX=r'''// Structural variant: each PE owns two non-reset data registers.
module kwt_tile16_mac(
 input wire clk,rst_n,
 input wire init_valid,output wire init_ready,input wire init_bank,input wire [511:0] init_bias,
 input wire mac_valid,output wire mac_ready,input wire mac_bank,mac_unsigned_a,mac_shift8,mac_last,
 input wire [127:0] mac_a,mac_b,
 input wire read_valid,output wire read_ready,input wire read_bank,input wire [3:0] read_row,read_col,input wire [15:0] read_tag,
 output reg raw_valid,input wire raw_ready,output reg [127:0] raw_data,output reg [15:0] raw_tag,
 input wire release_valid,output wire release_ready,input wire release_bank,
 output wire [1:0] empty,done
);
 localparam EMPTY=2'd0,ACTIVE=2'd1,DONE=2'd2;
 reg [1:0] state[0:1];reg raw_bank;
 wire init_fire=init_valid&&init_ready,mac_fire=mac_valid&&mac_ready,read_fire=read_valid&&read_ready;
 wire [8191:0] matrix0,matrix1;
 assign empty={state[1]==EMPTY,state[0]==EMPTY};assign done={state[1]==DONE,state[0]==DONE};
 assign init_ready=rst_n&&(state[init_bank]==EMPTY);assign mac_ready=rst_n&&(state[mac_bank]==ACTIVE);
 assign read_ready=rst_n&&(state[read_bank]==DONE)&&(!raw_valid||raw_ready)&&(read_row[1:0]==0);
 assign release_ready=rst_n&&(state[release_bank]==DONE)&&!(raw_valid&&!raw_ready&&raw_bank==release_bank)&&!(read_fire&&read_bank==release_bank);
 genvar row,col;
 generate for(row=0;row<16;row=row+1)begin: rows
  for(col=0;col<16;col=col+1)begin: cols
   wire signed [8:0] av=mac_unsigned_a?$signed({1'b0,mac_a[row*8+:8]}):$signed({mac_a[row*8+7],mac_a[row*8+:8]});
   wire signed [8:0] bv=$signed({mac_b[col*8+7],mac_b[col*8+:8]});wire signed [17:0] product=av*bv;
   wire signed [31:0] extended={{14{product[17]}},product};wire signed [31:0] term=mac_shift8?(extended<<<8):extended;
   reg signed [31:0] acc0,acc1;
   always @(posedge clk)begin
    if(init_fire&&!init_bank)acc0<=init_bias[col*32+:32];else if(mac_fire&&!mac_bank)acc0<=acc0+term;
    if(init_fire&&init_bank)acc1<=init_bias[col*32+:32];else if(mac_fire&&mac_bank)acc1<=acc1+term;
   end
   assign matrix0[(row*16+col)*32+:32]=acc0;assign matrix1[(row*16+col)*32+:32]=acc1;
  end
 end endgenerate
 integer lane;
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin state[0]<=EMPTY;state[1]<=EMPTY;raw_valid<=0;raw_data<=0;raw_tag<=0;raw_bank<=0;end
  else begin
   if(!raw_valid||raw_ready)begin
    raw_valid<=read_fire;
    if(read_fire)begin
     raw_tag<=read_tag;raw_bank<=read_bank;
     for(lane=0;lane<4;lane=lane+1)raw_data[lane*32+:32]<=read_bank?
      matrix1[((read_row[3:2]*4+lane)*16+read_col)*32+:32]:matrix0[((read_row[3:2]*4+lane)*16+read_col)*32+:32];
    end
   end
   if(release_valid&&release_ready)state[release_bank]<=EMPTY;
   if(init_fire)state[init_bank]<=ACTIVE;
   if(mac_fire&&mac_last)state[mac_bank]<=DONE;
  end
 end
endmodule

'''

def main():
    source=ROOT/'rtl/experimental/kwt_arithmetic16.sv';dest=ROOT/'rtl/experimental/kwt_arithmetic16_structural.sv'
    assert not dest.exists();tail=source.read_text().split('module kwt_rq4(',1)[1]
    dest.write_text(PREFIX+'module kwt_rq4('+tail)

if __name__=='__main__':main()
