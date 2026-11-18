// Three existing 32b masters enter the ORIGINAL e203_subsys_mems interface.
// Its existing two-entry command FIFO plus active split transaction accept
// three ordered commands. Keep only their response owners here; no data FIFO,
// new port, decoder parameter, bus width or SRAM interface is introduced.
module kwt_sysbus_arbiter3(
 input wire clk,rst_n,
 input wire [2:0] cmd_valid,output wire [2:0] cmd_ready,
 input wire [95:0] cmd_addr,cmd_wdata,input wire [2:0] cmd_read,
 input wire [11:0] cmd_wmask,
 output wire [2:0] rsp_valid,input wire [2:0] rsp_ready,
 output wire [95:0] rsp_rdata,output wire [2:0] rsp_error,
 output wire bus_valid,input wire bus_ready,output wire [31:0] bus_addr,bus_wdata,
 output wire bus_read,output wire [3:0] bus_wmask,
 input wire bus_rsp_valid,output wire bus_rsp_ready,
 input wire [31:0] bus_rsp_rdata,input wire bus_rsp_error
);
 reg locked;reg[1:0]grant,turn;
 reg[1:0]owners[0:2];reg[1:0]head,tail,count;
 reg[1:0]selected;integer offset,index;
 always @*begin
  selected=turn;
  for(offset=2;offset>=0;offset=offset-1)begin
   index=turn+offset;if(index>=3)index=index-3;
   if(cmd_valid[index])selected=index[1:0];
  end
  if(locked)selected=grant;
 end
 wire empty=count==0,full=count==3;
 wire[1:0] response_owner=empty?selected:owners[head];
 assign bus_valid=rst_n&&!full&&cmd_valid[selected];
 assign bus_addr=cmd_addr[32*selected+:32];assign bus_wdata=cmd_wdata[32*selected+:32];
 assign bus_read=cmd_read[selected];assign bus_wmask=cmd_wmask[4*selected+:4];
 // Preserve the legal combinational ROM case when the queue is empty.
 assign bus_rsp_ready=rst_n&&(!empty?rsp_ready[response_owner]:(bus_valid&&rsp_ready[selected]));
 wire push=bus_valid&&bus_ready;
 wire pop=bus_rsp_valid&&bus_rsp_ready&&(!empty||push);
 function automatic[1:0]next_slot(input[1:0]slot);begin next_slot=slot==2?0:slot+1'b1;end endfunction
 genvar i;
 generate for(i=0;i<3;i=i+1)begin:master
  assign cmd_ready[i]=rst_n&&!full&&selected==i&&bus_ready;
  assign rsp_valid[i]=rst_n&&bus_rsp_valid&&(!empty||bus_valid)&&response_owner==i;
  assign rsp_rdata[32*i+:32]=bus_rsp_rdata;assign rsp_error[i]=bus_rsp_error;
 end endgenerate
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin locked<=0;grant<=0;turn<=0;head<=0;tail<=0;count<=0;end
  else begin
   if(bus_valid&&!bus_ready&&!locked)begin locked<=1;grant<=selected;end
   if(push)begin
    owners[tail]<=selected;tail<=next_slot(tail);locked<=0;
    turn<=selected==2?0:selected+1'b1;
   end
   if(pop)head<=next_slot(head);
   case({push,pop})
    2'b10:count<=count+1'b1;
    2'b01:count<=count-1'b1;
    default:count<=count;
   endcase
  end
 end
endmodule
