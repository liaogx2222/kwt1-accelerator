// Single outstanding reference ICB adapter. Bus faults are returned through a
// sideband status CSR read by firmware callbacks; not a claim about final SoC.
module icb_kwt_bridge(input wire clk,rst_n,abort_hw,input wire [15:0] timeout_cycles,input wire drop_response,
 input wire cv,output wire cr,input wire [31:0] ca,cw,input wire cread,input wire [3:0] cm,
 output wire rv,input wire rr,output wire [31:0] rd,
 output wire hv,input wire hr,output wire [31:0] ha,hw,output wire hread,output wire [3:0] hm,
 input wire hrv,output wire hrr,input wire [31:0] hrd,
 output wire av,input wire ar,output wire awrite,output wire [31:0] aa,ad,output wire [3:0] am,
 input wire arv,output wire arr,input wire [31:0] ard,input wire ae,
 output reg signed [31:0] last_error,output reg [31:0] param_words);
 localparam IDLE=0,ASEND=1,ARESP=2,HSEND=3,HRESP=4,REPLY=5;
 reg [2:0] state;reg [31:0] addr,data,result;reg read;reg [3:0] mask;reg [15:0] wait_count;
 assign cr=state==IDLE;assign rv=state==REPLY;assign rd=result;
 assign av=state==ASEND;assign aa=addr[15:0];assign ad=data;assign am=mask;assign awrite=!read;
 assign arr=state==ARESP&&!drop_response;
 assign hv=state==HSEND;assign ha=addr;assign hw=data;assign hm=mask;assign hread=read;assign hrr=state==HRESP;
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin state<=IDLE;last_error<=0;addr<=0;data<=0;result<=0;read<=0;mask<=0;wait_count<=0;param_words<=0;end
  else begin
   if(abort_hw)last_error<=0;
   case(state)
    IDLE:if(cv)begin addr<=ca;data<=cw;read<=cread;mask<=cm;wait_count<=0;state<=(ca[31:16]==16'h1000) ? ASEND : HSEND;end
    ASEND:begin
     wait_count<=wait_count+1;
     if(ar)begin state<=ARESP;wait_count<=0;if(addr[15:0]==16&&!read)param_words<=param_words+1;end
     else if(wait_count>=timeout_cycles)begin last_error<=-2;result<=0;state<=REPLY;end
    end
    ARESP:begin
     wait_count<=wait_count+1;
     if(arv&&arr)begin last_error<=ae?-1:0;result<=ard;state<=REPLY;end
     else if(wait_count>=timeout_cycles)begin last_error<=-2;result<=0;state<=REPLY;end
    end
    HSEND:if(hr)state<=HRESP;
    HRESP:if(hrv)begin result<=hrd;state<=REPLY;end
    REPLY:if(rr)state<=IDLE;
    default:state<=IDLE;
   endcase
  end
 end
endmodule
