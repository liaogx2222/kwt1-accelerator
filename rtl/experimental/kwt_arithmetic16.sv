// Original KWT experimental arithmetic partition. No SRAM/SoC controller.
// Two ownership-tracked 16x16 INT32 accumulators + independent 4-lane RQ.
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
 reg [1:0] state[0:1];reg signed [31:0] acc[0:1][0:255];reg raw_bank;
 wire init_fire=init_valid&&init_ready,mac_fire=mac_valid&&mac_ready;
 wire read_fire=read_valid&&read_ready;
 assign empty={state[1]==EMPTY,state[0]==EMPTY};assign done={state[1]==DONE,state[0]==DONE};
 assign init_ready=rst_n&&(state[init_bank]==EMPTY);
 assign mac_ready=rst_n&&(state[mac_bank]==ACTIVE);
 assign read_ready=rst_n&&(state[read_bank]==DONE)&&(!raw_valid||raw_ready)&&(read_row[1:0]==0);
 assign release_ready=rst_n&&(state[release_bank]==DONE)&&!(raw_valid&&!raw_ready&&raw_bank==release_bank)&&!(read_fire&&read_bank==release_bank);
 integer r,c;
 reg signed [8:0] av,bv;reg signed [17:0] product;reg signed [31:0] term;
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin state[0]<=EMPTY;state[1]<=EMPTY;raw_valid<=0;raw_data<=0;raw_tag<=0;raw_bank<=0;end
  else begin
   if(!raw_valid||raw_ready)begin
    raw_valid<=read_fire;
    if(read_fire)begin
     raw_tag<=read_tag;raw_bank<=read_bank;
     for(r=0;r<4;r=r+1)raw_data[r*32+:32]<=acc[read_bank][(read_row+r)*16+read_col];
    end
   end
   if(release_valid&&release_ready)state[release_bank]<=EMPTY;
   if(init_fire)begin
    state[init_bank]<=ACTIVE;
    for(r=0;r<16;r=r+1)for(c=0;c<16;c=c+1)acc[init_bank][r*16+c]<=init_bias[c*32+:32];
   end
   if(mac_fire)begin
    for(r=0;r<16;r=r+1)for(c=0;c<16;c=c+1)begin
     av=mac_unsigned_a?$signed({1'b0,mac_a[r*8+:8]}):$signed({mac_a[r*8+7],mac_a[r*8+:8]});
     bv=$signed({mac_b[c*8+7],mac_b[c*8+:8]});product=av*bv;
     term={{14{product[17]}},product};if(mac_shift8)term=term<<<8;
     acc[mac_bank][r*16+c]<=acc[mac_bank][r*16+c]+term;
    end
    if(mac_last)state[mac_bank]<=DONE;
   end
  end
 end
endmodule

module kwt_rq4(
 input wire clk,rst_n,req_valid,output wire req_ready,
 input wire [127:0] req_a,req_m,input wire [31:0] req_shift,input wire [15:0] req_tag,
 output wire resp_valid,input wire resp_ready,output wire [31:0] resp_data,output wire resp_error,output wire [15:0] resp_tag
);
 wire [3:0] mr,mv,nr,nv,me,ne;wire [255:0] product,rounded;wire [95:0] mt;wire [63:0] nt;
 assign req_ready=rst_n&&(&mr);assign resp_valid=rst_n&&(&nv);assign resp_error=|ne;assign resp_tag=nt[15:0];
 genvar lane;
 generate for(lane=0;lane<4;lane=lane+1)begin: lanes
  mul_pipe #(.TAG_W(24)) mul(clk,rst_n,req_valid&&(&mr),mr[lane],1'b1,
   {{32{req_a[lane*32+31]}},req_a[lane*32+:32]},{{32{req_m[lane*32+31]}},req_m[lane*32+:32]},
   {req_tag,req_shift[lane*8+:8]},mv[lane],(&nr)&&(&mv),product[lane*64+:64],me[lane],mt[lane*24+:24]);
  rne_pipe #(.TAG_W(16)) rne(clk,rst_n,(&mv),nr[lane],product[lane*64+:64],$signed(mt[lane*24+:8]),6'd8,me[lane],mt[lane*24+8+:16],
   nv[lane],resp_ready&&(&nv),rounded[lane*64+:64],ne[lane],nt[lane*16+:16]);
  assign resp_data[lane*8+:8]=rounded[lane*64+:8];
 end endgenerate
endmodule

// Independent interfaces deliberately expose the arithmetic boundary. External
// scheduling connects accumulator reads to RQ; that controller is not included.
module kwt_arithmetic16(
 input wire clk,rst_n,
 input wire init_valid,output wire init_ready,input wire init_bank,input wire [511:0] init_bias,
 input wire mac_valid,output wire mac_ready,input wire mac_bank,mac_unsigned_a,mac_shift8,mac_last,input wire [127:0] mac_a,mac_b,
 input wire read_valid,output wire read_ready,input wire read_bank,input wire [3:0] read_row,read_col,input wire [15:0] read_tag,
 output wire raw_valid,input wire raw_ready,output wire [127:0] raw_data,output wire [15:0] raw_tag,
 input wire release_valid,output wire release_ready,input wire release_bank,output wire [1:0] empty,done,
 input wire rq_valid,output wire rq_ready,input wire [127:0] rq_a,rq_m,input wire [31:0] rq_shift,input wire [15:0] rq_tag,
 output wire rq_resp_valid,input wire rq_resp_ready,output wire [31:0] rq_data,output wire rq_error,output wire [15:0] rq_resp_tag
);
 kwt_tile16_mac tile(clk,rst_n,init_valid,init_ready,init_bank,init_bias,mac_valid,mac_ready,mac_bank,mac_unsigned_a,mac_shift8,mac_last,
  mac_a,mac_b,read_valid,read_ready,read_bank,read_row,read_col,read_tag,raw_valid,raw_ready,raw_data,raw_tag,release_valid,release_ready,release_bank,empty,done);
 kwt_rq4 rq(clk,rst_n,rq_valid,rq_ready,rq_a,rq_m,rq_shift,rq_tag,rq_resp_valid,rq_resp_ready,rq_data,rq_error,rq_resp_tag);
endmodule
