// CPU-owned bounded NICE instruction. Original 32b interfaces and ABI.
// Only input/parameter reads use two ordered credits. Output writes retain
// the single-request physical-ACK path; no work survives CPU completion.
module e203_subsys_nice_core #(parameter TIMEOUT=131072)(
 input wire nice_clk,nice_rst_n,output wire nice_active,nice_mem_holdup,
 input wire nice_req_valid,output wire nice_req_ready,input wire [31:0] nice_req_inst,nice_req_rs1,nice_req_rs2,
 output wire nice_rsp_valid,input wire nice_rsp_ready,output reg [31:0] nice_rsp_rdat,output wire nice_rsp_err,
 output wire nice_icb_cmd_valid,input wire nice_icb_cmd_ready,output wire [31:0] nice_icb_cmd_addr,
 output wire nice_icb_cmd_read,output wire [31:0] nice_icb_cmd_wdata,output wire [1:0] nice_icb_cmd_size,
 input wire nice_icb_rsp_valid,output wire nice_icb_rsp_ready,input wire [31:0] nice_icb_rsp_rdata,input wire nice_icb_rsp_err,
 output wire blk_mem_valid,input wire blk_mem_ready,output wire [31:0] blk_mem_addr,
 output wire blk_mem_read,output wire [31:0] blk_mem_wdata,
 input wire blk_rsp_valid,output wire blk_rsp_ready,input wire [31:0] blk_rsp_data,input wire blk_rsp_error,
 output wire blk_sink_valid,input wire blk_sink_ready,output wire [31:0] blk_sink_data,
 output wire blk_sink_last,blk_sink_input,input wire blk_error,blk_cancel,
 output wire blk_output_active,input wire blk_source_valid,output wire blk_source_ready,
 input wire [31:0] blk_source_data,input wire blk_source_last,output reg blk_source_ack
);
 localparam IDLE=0,MEM_REQ=1,MEM_RSP=2,HOLD=3,OUTPUT_WAIT=4,REPLY=5,READ_STREAM=6;
 localparam OK=0,MEM_ERROR=1,WAIT_TIMEOUT=2,CANCELLED=3,ARGUMENT=4,SINK_ERROR=5,LENGTH_ERROR=6;
 localparam EMPTY=0,CMD_WAIT=1,RSP_WAIT=2,DATA_WAIT=3;
 localparam TW=$clog2(TIMEOUT+1);
 reg[2:0]state,first_error;reg[1:0]kind;
 reg[31:0]address,payload;reg[14:0]remaining,completed,first_bad;
 reg[TW-1:0]timer;
 // Slot0 aliases the old payload/timer. Data and age of slot1 are initialized
 // on allocation/response, before the reset-qualified phase makes them live.
 reg[31:0]prefetch_payload;reg[TW-1:0]prefetch_timer;
 reg[1:0]phase[0:1],slot_fault[0:1];reg head,tail,response_slot;
 wire[TW-1:0]age[0:1];assign age[0]=timer;assign age[1]=prefetch_timer;
 wire[6:0]function_id=nice_req_inst[31:25];
 wire[32:0]end_address={1'b0,nice_req_rs1}+({1'b0,nice_req_rs2}<<2);
 wire instruction_ok=nice_req_inst[6:0]==7'h7b&&nice_req_inst[14:12]==7&&function_id>=7'h28&&function_id<=7'h2a;
 wire range_ok=function_id==7'h2a ? nice_req_rs1>=32'ha0022000&&end_address<=33'ha00238c0 :
               function_id==7'h29 ? nice_req_rs1>=32'ha0040000&&end_address<=33'ha0043180 :
               ((nice_req_rs1>=32'ha0001000&&end_address<=33'ha00050c0)||
                (nice_req_rs1>=32'ha0024000&&end_address<=33'ha0033120));
 wire legal=instruction_ok&&nice_req_rs1[1:0]==0&&nice_req_rs2>=1&&nice_req_rs2<=16384&&range_ok;
 wire[2:0]stop=first_error!=OK?first_error:blk_cancel?CANCELLED:blk_error?SINK_ERROR:OK;
 wire memory_response=state==MEM_RSP&&blk_rsp_valid;
 wire offer=phase[0]==CMD_WAIT||phase[1]==CMD_WAIT;
 wire command_slot=phase[0]==CMD_WAIT?1'b0:1'b1;
 wire read_command=state==READ_STREAM&&blk_mem_valid&&blk_mem_ready;
 wire read_response=state==READ_STREAM&&blk_rsp_valid&&blk_rsp_ready;
 wire[1:0]credits={1'b0,phase[0]!=EMPTY}+{1'b0,phase[1]!=EMPTY};
 wire head_available=slot_fault[head]==OK&&
       (phase[head]==DATA_WAIT||(read_response&&response_slot==head&&!blk_rsp_error));
 wire potential_take=head_available&&blk_sink_ready;
 reg[1:0]expired;integer probe;
 always @*begin
  expired=0;
  for(probe=0;probe<2;probe=probe+1)begin
   if(slot_fault[probe]==OK&&age[probe]==TIMEOUT-1)case(phase[probe])
    CMD_WAIT:expired[probe]=!(read_command&&command_slot==probe);
    RSP_WAIT:expired[probe]=!(read_response&&response_slot==probe);
    DATA_WAIT:expired[probe]=head==probe&&!potential_take;
    default:expired[probe]=0;
   endcase
  end
 end
 // Retire memory errors in order. A prefetched error stops new allocation,
 // but never withdraws an older valid word under ordinary backpressure.
 wire[2:0]read_fault=stop!=OK?stop:
       slot_fault[head]!=OK?{1'b0,slot_fault[head]}:
       (read_response&&response_slot==head&&blk_rsp_error)?MEM_ERROR:
       expired[head]?WAIT_TIMEOUT:OK;
 wire read_take=nice_rst_n&&state==READ_STREAM&&read_fault==OK&&potential_take;
 wire pending_problem=(slot_fault[0]!=OK)||(slot_fault[1]!=OK)||(|expired)||(read_response&&blk_rsp_error);
 wire allocate=state==READ_STREAM&&read_fault==OK&&!pending_problem&&!offer&&
       (credits<2||read_take)&&remaining>credits;
 wire draining_memory=offer||phase[0]==RSP_WAIT||phase[1]==RSP_WAIT;
 assign nice_req_ready=nice_rst_n&&state==IDLE;
 assign nice_active=nice_req_valid||state!=IDLE;assign nice_mem_holdup=state!=IDLE;
 assign nice_rsp_valid=nice_rst_n&&state==REPLY;assign nice_rsp_err=0;
 assign nice_icb_cmd_valid=0;assign nice_icb_cmd_addr=0;assign nice_icb_cmd_read=1;
 assign nice_icb_cmd_wdata=0;assign nice_icb_cmd_size=2;assign nice_icb_rsp_ready=0;
 assign blk_mem_valid=nice_rst_n&&(state==MEM_REQ||(state==READ_STREAM&&offer));
 assign blk_mem_addr=address;assign blk_mem_read=kind!=2;
 // Read commands must remain stable while an older response changes slot0.
 assign blk_mem_wdata=state==READ_STREAM?32'd0:payload;
 assign blk_rsp_ready=nice_rst_n&&(state==MEM_RSP||(state==READ_STREAM&&phase[response_slot]==RSP_WAIT));
 // A head timeout retires on the edge, as in the old HOLD state. Keep a
 // backpressured valid word visible up to that edge; readiness at the
 // deadline still makes progress and wins over timeout.
 assign blk_sink_valid=nice_rst_n&&state==READ_STREAM&&stop==OK&&slot_fault[head]==OK&&
       !(read_response&&response_slot==head&&blk_rsp_error)&&head_available;
 assign blk_sink_data=phase[head]==DATA_WAIT?(head?prefetch_payload:payload):blk_rsp_data;
 assign blk_sink_last=remaining==1;assign blk_sink_input=kind==1;
 assign blk_output_active=nice_rst_n&&kind==2&&state!=IDLE;
 assign blk_source_ready=nice_rst_n&&state==OUTPUT_WAIT&&stop==OK;
 task automatic fail(input[2:0]cause,input committed_after_fault);
  begin nice_rsp_rdat<={1'b1,committed_after_fault,7'd0,(first_error==OK?completed:first_bad),5'd0,cause};state<=REPLY;end
 endtask
 task automatic advance;
  begin
   timer<=0;completed<=completed+1;
   if(remaining==1)begin nice_rsp_rdat<=0;state<=REPLY;end
   else begin address<=address+4;remaining<=remaining-1;state<=kind==2?OUTPUT_WAIT:MEM_REQ;end
  end
 endtask
 task automatic set_age(input integer slot,input[TW-1:0]value);
  begin if(slot==0)timer<=value;else prefetch_timer<=value;end
 endtask
 integer i;
 always @(posedge nice_clk or negedge nice_rst_n)begin
  if(!nice_rst_n)begin
   state<=IDLE;first_error<=OK;kind<=0;address<=0;payload<=0;remaining<=0;completed<=0;first_bad<=0;
   timer<=0;nice_rsp_rdat<=0;blk_source_ack<=0;head<=0;tail<=0;response_slot<=0;
   phase[0]<=EMPTY;phase[1]<=EMPTY;slot_fault[0]<=OK;slot_fault[1]<=OK;
  end else begin
   blk_source_ack<=0;
   case(state)
    IDLE:if(nice_req_valid)begin
     first_error<=OK;completed<=0;first_bad<=0;timer<=0;nice_rsp_rdat<=0;
     head<=0;tail<=0;response_slot<=0;phase[0]<=EMPTY;phase[1]<=EMPTY;slot_fault[0]<=OK;slot_fault[1]<=OK;
     if(!legal)begin nice_rsp_rdat<=32'h80000004;state<=REPLY;end
     else begin kind<=function_id-7'h28;address<=nice_req_rs1;remaining<=nice_req_rs2[14:0];state<=function_id==7'h2a ? OUTPUT_WAIT:READ_STREAM;end
    end
    READ_STREAM:begin
     if(first_error==OK&&read_fault!=OK)begin first_error<=read_fault;first_bad<=completed;end
     for(i=0;i<2;i=i+1)begin
      if(first_error==OK&&slot_fault[i]==OK)begin
       if(phase[i]==CMD_WAIT||phase[i]==RSP_WAIT||(phase[i]==DATA_WAIT&&head==i))set_age(i,age[i]+1'b1);
       if(expired[i])slot_fault[i]<=WAIT_TIMEOUT;
      end
      if(read_command&&command_slot==i)begin phase[i]<=RSP_WAIT;set_age(i,0);end
      if(read_response&&response_slot==i)begin
       phase[i]<=read_fault!=OK||(read_take&&head==i)?EMPTY:DATA_WAIT;
       if(blk_rsp_error&&slot_fault[i]==OK)slot_fault[i]<=MEM_ERROR;
       if(i==0)payload<=blk_rsp_data;else prefetch_payload<=blk_rsp_data;
       set_age(i,0);
      end
      if(read_take&&head==i)begin phase[i]<=EMPTY;slot_fault[i]<=OK;end
      if(read_fault!=OK&&phase[i]==DATA_WAIT)begin phase[i]<=EMPTY;slot_fault[i]<=OK;end
     end
     if(read_command)address<=address+4;
     if(read_response)response_slot<=!response_slot;
     if(read_take)begin
      head<=!head;remaining<=remaining-1;completed<=completed+1;
      if(remaining==1)begin nice_rsp_rdat<=0;state<=REPLY;end
     end
     if(allocate)begin phase[tail]<=CMD_WAIT;slot_fault[tail]<=OK;set_age(tail,0);tail<=!tail;end
     if(read_fault!=OK&&!draining_memory)fail(read_fault,0);
    end
    // Original output-write control, including visible-request hold, first
    // fault, timeout, physical-response drain and final source ACK.
    MEM_REQ,MEM_RSP:begin
     if(first_error==OK)begin
      if(stop!=OK)begin first_error<=stop;first_bad<=completed;end
      else if(timer==TIMEOUT-1)begin first_error<=WAIT_TIMEOUT;first_bad<=completed;end
      else timer<=timer+1;
     end
     if(state==MEM_REQ&&blk_mem_ready)begin state<=MEM_RSP;timer<=0;if(stop==OK)first_error<=OK;end
     if(memory_response)begin
      timer<=0;if(stop==OK)first_error<=OK;
      if(stop!=OK)fail(stop,kind==2&&!blk_rsp_error);
      else if(blk_rsp_error)fail(MEM_ERROR,0);
      else if(kind==2)begin if(remaining==1)blk_source_ack<=1;advance();end
      else if(blk_sink_ready)advance();else begin payload<=blk_rsp_data;state<=HOLD;end
     end
    end
    HOLD:if(stop!=OK)fail(stop,0);else if(blk_sink_ready)advance();else if(timer==TIMEOUT-1)fail(WAIT_TIMEOUT,0);else timer<=timer+1;
    OUTPUT_WAIT:if(stop!=OK)fail(stop,0);
     else if(blk_source_valid)begin
      if(blk_source_last!=(remaining==1))fail(LENGTH_ERROR,0);
      else begin payload<=blk_source_data;state<=MEM_REQ;timer<=0;end
     end else if(timer==TIMEOUT-1)fail(WAIT_TIMEOUT,0);else timer<=timer+1;
    REPLY:if(nice_rsp_ready)state<=IDLE;
    default:begin nice_rsp_rdat<=32'h80000005;state<=REPLY;end
   endcase
  end
 end
endmodule
