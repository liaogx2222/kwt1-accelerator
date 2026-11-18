// Fixed-profile packet -> actual SRAM writes. One holding beat, no packet RAM.
module kwt_packet_loader(input wire clk,rst_n,enable,
 input wire begin_valid,output wire begin_ready,input wire common_flag,input wire [3:0] layer,
 input wire valid,output wire ready,input wire [31:0] data,input wire last,
 output reg loaded,output reg error,output wire active,
 output reg [19:0] mem_en,mem_we,output reg [239:0] mem_addr,output reg [319:0] mem_wdata);
 `include "kwt_profile.svh"
 localparam IDLE=0,RECV=1,WRITE0=2,WRITE1=3,FINISH=4,FAILED=5;
 reg [2:0] state;reg is_common,seen_last,bad_header;reg [3:0] lid;
 reg [13:0] position;reg [31:0] crc,held;reg [17:0] location0,location1;
 wire [13:0] final_word=is_common?14'd4143:14'd15431;
 function automatic [31:0] crc_word(input [31:0] previous,input [31:0] value);
  reg [31:0] c;integer j;begin c=previous^value;for(j=0;j<32;j=j+1)c=c[0]?(c>>1)^32'hedb88320:c>>1;crc_word=c;end
 endfunction
 assign begin_ready=rst_n&&state==IDLE&&!error;assign ready=rst_n&&enable&&state==RECV&&!seen_last;
 assign active=state!=IDLE;
 always @* begin
  mem_en=0;mem_we=0;mem_addr=0;mem_wdata=0;
  if(enable&&state==WRITE0)begin
   if(location0[17])begin mem_en[location0[16:12]]=1;mem_we[location0[16:12]]=1;mem_addr[location0[16:12]*12+:12]=location0[11:0];mem_wdata[location0[16:12]*16+:16]=held[15:0];end
   if(location1[17]&&(!location0[17]||location1[16:12]!=location0[16:12]))begin
    mem_en[location1[16:12]]=1;mem_we[location1[16:12]]=1;mem_addr[location1[16:12]*12+:12]=location1[11:0];mem_wdata[location1[16:12]*16+:16]=held[31:16];
   end
  end
  if(enable&&state==WRITE1&&location1[17])begin mem_en[location1[16:12]]=1;mem_we[location1[16:12]]=1;mem_addr[location1[16:12]*12+:12]=location1[11:0];mem_wdata[location1[16:12]*16+:16]=held[31:16];end
 end
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin state<=IDLE;is_common<=0;seen_last<=0;bad_header<=0;lid<=0;position<=0;crc<=32'hffffffff;held<=0;location0<=0;location1<=0;loaded<=0;error<=0;end
  else begin
   loaded<=0;
   if(begin_valid&&begin_ready)begin state<=RECV;is_common<=common_flag;lid<=layer;position<=0;crc<=32'hffffffff;seen_last<=0;bad_header<=0;end
   if(enable)case(state)
    RECV:if(valid&&ready)begin
     held<=data;location0<=packet_location(is_common,position*4,0);location1<=packet_location(is_common,position*4,1);
     if(position<16&&data!=profile_header(is_common,lid,position))bad_header<=1;
     if(position>=16)crc<=crc_word(crc,data);
     if(last!=(position==final_word))begin if(last||position==final_word)begin error<=1;state<=FAILED;end end
     if(last==(position==final_word)||(!last&&position<final_word))state<=WRITE0;
     seen_last<=last;position<=position+1;
    end
    WRITE0:begin
     if(location0[17]&&location1[17]&&location0[16:12]==location1[16:12])state<=WRITE1;
     else state<=seen_last?FINISH:RECV;
    end
    WRITE1:state<=seen_last?FINISH:RECV;
    FINISH:begin
     if(bad_header||(crc^32'hffffffff)!=profile_header(is_common,lid,14))begin error<=1;state<=FAILED;end
     else begin loaded<=1;state<=IDLE;end
    end
   endcase
  end
 end
endmodule
