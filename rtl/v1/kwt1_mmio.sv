// Platform independent, single outstanding, 32-bit request/response bus.
// A request commits only at valid&&ready. Responses remain stable until taken.
// Last output read is acknowledged to the accelerator ONLY when its bus
// response is consumed, so task_cycles includes the final CPU-visible writeback.
module kwt1_mmio(input wire clk,rst_n,abort_hw,core_enable,mem_enable,
 input wire req_valid,output reg req_ready,input wire req_write,input wire [31:0] req_addr,req_wdata,input wire [3:0] req_wstrb,
 output reg resp_valid,input wire resp_ready,output reg [31:0] resp_rdata,output reg resp_error,
 output wire irq);
 reg sw_abort,last_flag,response_last;
 wire task_abort=abort_hw||sw_abort;
 wire frame_ready,cfg_ready,input_ready,start_ready,out_valid,out_last,need_parameters,awaiting_ack,busy,done,error;
 wire common_valid,input_loaded,layer_valid;wire [3:0] layer;wire [7:0] error_code,debug_state;wire [31:0] out_data;
 wire [63:0] cycles,compute,reads,writes,stalls;
 wire access=req_valid&&req_ready;
 wire issue=req_valid&&rst_n&&!task_abort&&(!resp_valid||resp_ready);
 wire aligned=req_addr[1:0]==0;
 wire write_ok=aligned&&req_write&&req_wstrb==4'hf;
 wire valid_frame=issue&&write_ok&&req_addr==8&&!error;
 wire valid_cfg=issue&&write_ok&&req_addr==16&&!error;
 wire valid_input=issue&&write_ok&&req_addr==20&&!error;
 wire valid_start=issue&&write_ok&&req_addr==0&&req_wdata==1;
 wire take_output=issue&&aligned&&!req_write&&req_addr==24&&!error;
 wire ack_output=resp_valid&&resp_ready&&response_last&&!task_abort;
 kwt1_accel accel(clk,rst_n,task_abort,core_enable,mem_enable,
  valid_frame,frame_ready,req_wdata[8],req_wdata[3:0],valid_cfg,cfg_ready,req_wdata,last_flag,
  valid_input,input_ready,req_wdata,last_flag,valid_start,start_ready,
  out_valid,take_output,out_data,out_last,ack_output,need_parameters,awaiting_ack,layer,busy,done,error,error_code,
  common_valid,input_loaded,layer_valid,debug_state,cycles,compute,reads,writes,stalls);
 assign irq=done||error;
 reg [31:0] read_value;reg access_error;
 always @* begin
  req_ready=rst_n&&!task_abort&&(!resp_valid||resp_ready);
  read_value=0;access_error=!aligned;
  if(req_write)begin
   if(req_wstrb!=15)access_error=1;
   case(req_addr)
    0:if(req_wdata[1])begin end else if(req_wdata!=1||!start_ready)access_error=1;
    8:if(!error&&write_ok)req_ready=req_ready&&frame_ready;else access_error=1;
    12:if(req_wdata>1)access_error=1;
    16:if(!error&&write_ok)req_ready=req_ready&&cfg_ready;else access_error=1;
    20:if(!error&&write_ok)req_ready=req_ready&&input_ready;else access_error=1;
    default:access_error=1;
   endcase
  end else case(req_addr)
   4:begin
    read_value[0]=busy;read_value[1]=done;read_value[2]=error;read_value[3]=common_valid;
    read_value[4]=input_loaded;read_value[5]=layer_valid;read_value[6]=need_parameters;read_value[7]=awaiting_ack;
    read_value[8]=start_ready;read_value[9]=frame_ready;read_value[10]=cfg_ready;read_value[11]=input_ready;
    read_value[12]=out_valid;read_value[19:16]=layer;
   end
   24:begin if(!error)req_ready=req_ready&&out_valid;else access_error=1;read_value=out_data;end
   28:read_value={16'd0,debug_state,error_code};
   32:read_value=cycles[31:0];36:read_value=cycles[63:32];
   40:read_value=compute[31:0];44:read_value=compute[63:32];
   48:read_value=reads[31:0];52:read_value=reads[63:32];
   56:read_value=writes[31:0];60:read_value=writes[63:32];
   64:read_value=stalls[31:0];68:read_value=stalls[63:32];
   72:read_value=32'h4b575431;
   default:access_error=1;
  endcase
 end
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin resp_valid<=0;resp_rdata<=0;resp_error<=0;response_last<=0;sw_abort<=0;last_flag<=0;end
  else if(abort_hw)begin resp_valid<=0;resp_rdata<=0;resp_error<=0;response_last<=0;sw_abort<=0;last_flag<=0;end
  else begin
   sw_abort<=0;
   if(resp_valid&&resp_ready)begin resp_valid<=0;response_last<=0;end
   if(access)begin
    resp_valid<=1;resp_rdata<=read_value;resp_error<=access_error;response_last<=take_output&&out_last&&!access_error;
    if(write_ok&&!access_error)case(req_addr)
     0:if(req_wdata[1])begin sw_abort<=1;last_flag<=0;end
     12:last_flag<=req_wdata[0];
     16,20:last_flag<=0;
    endcase
   end
  end
 end
endmodule
