// Three 32-bit masters enter the ORIGINAL e203_subsys_mems System Bus.
// No master has a connection to the SRAM controller or its bank ports.
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
 reg busy,locked;reg [1:0] owner,grant,turn;
 reg [1:0] selected;integer offset,index;
 always @*begin
  selected=turn;
  // Reverse scan so the first request in round-robin order wins.
  for(offset=2;offset>=0;offset=offset-1)begin
   index=turn+offset;if(index>=3)index=index-3;
   if(cmd_valid[index])selected=index[1:0];
  end
  if(locked)selected=grant;
 end
 assign bus_valid=rst_n&&!busy&&cmd_valid[selected];
 assign bus_addr=cmd_addr[32*selected+:32];
 assign bus_wdata=cmd_wdata[32*selected+:32];
 assign bus_read=cmd_read[selected];assign bus_wmask=cmd_wmask[4*selected+:4];
 // The original ROM may return a combinational response and couples command
 // ready to response ready. Support that legal zero-latency ICB transfer.
 assign bus_rsp_ready=rst_n&&(busy?rsp_ready[owner]:(bus_valid&&rsp_ready[selected]));
 genvar i;
 generate for(i=0;i<3;i=i+1)begin:master
  assign cmd_ready[i]=rst_n&&!busy&&selected==i&&bus_ready;
  assign rsp_valid[i]=rst_n&&bus_rsp_valid&&(busy?owner==i:(bus_valid&&selected==i));
  assign rsp_rdata[32*i+:32]=bus_rsp_rdata;
  assign rsp_error[i]=bus_rsp_error;
 end endgenerate
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin busy<=0;locked<=0;owner<=0;grant<=0;turn<=0;end
  else begin
   if(bus_valid&&!bus_ready&&!locked)begin locked<=1;grant<=selected;end
   if(bus_valid&&bus_ready)begin
    busy<=!(bus_rsp_valid&&bus_rsp_ready);owner<=selected;locked<=0;turn<=selected==2?0:selected+1'b1;
   end
   if(bus_rsp_valid&&bus_rsp_ready)busy<=0;
  end
 end
endmodule
