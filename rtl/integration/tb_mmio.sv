// Isolated production MMIO wrapper with a controllable accelerator endpoint.
// Encoder correctness is checked separately with the entire gate netlist.
module kwt1_accel #(parameter SINGLE_LAYER=0)(
 input wire clk,rst_n,abort,core_enable,mem_enable,
 input wire frame_valid,output wire frame_ready,input wire frame_common,input wire [3:0] frame_layer,
 input wire cfg_valid,output wire cfg_ready,input wire [31:0] cfg_data,input wire cfg_last,
 input wire input_valid,output wire input_ready,input wire [31:0] input_data,input wire input_last,
 input wire start_valid,output wire start_ready,
 output wire output_valid,input wire output_ready,output wire [31:0] output_data,output wire output_last,input wire result_ack,
 output wire need_parameters,awaiting_ack,output wire [3:0] current_layer,
 output reg busy,done,output wire error,output wire [7:0] error_code,
 output wire common_valid,input_loaded,layer_valid,output wire [7:0] debug_state,
 output wire [63:0] task_cycles,compute_cycles,read_words,write_words,stall_cycles);
 reg cfg_allow=1,output_present=0;reg [31:0] value=0;
 integer cfg_taken=0,output_taken=0,acks=0;
 assign frame_ready=rst_n&&!abort;assign cfg_ready=rst_n&&!abort&&cfg_allow;
 assign input_ready=rst_n&&!abort;assign start_ready=rst_n&&!abort;
 assign output_valid=rst_n&&!abort&&busy&&output_present;assign output_data=value;assign output_last=1;
 assign need_parameters=0;assign awaiting_ack=busy&&output_taken!=0;
 assign current_layer=0;assign error=0;assign error_code=0;assign debug_state=0;
 assign common_valid=0;assign input_loaded=0;assign layer_valid=0;
 assign task_cycles=0;assign compute_cycles=0;assign read_words=0;assign write_words=0;assign stall_cycles=0;
 wire endpoint_rst_n=rst_n&&!abort;
 always @(posedge clk or negedge endpoint_rst_n)begin
  if(!endpoint_rst_n)begin busy<=0;done<=0;cfg_taken<=0;output_taken<=0;acks<=0;end
  else begin
   if(start_valid&&start_ready)begin busy<=1;done<=0;end
   if(cfg_valid&&cfg_ready)cfg_taken<=cfg_taken+1;
   if(output_valid&&output_ready)output_taken<=output_taken+1;
   if(result_ack)begin acks<=acks+1;done<=1;busy<=0;end
  end
 end
endmodule

module tb_mmio;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,abort_hw=0,core_enable=1,mem_enable=1;
 reg req_valid=0,req_write=0;reg [31:0] req_addr=0,req_wdata=0;reg [3:0] req_wstrb=15;
 reg resp_ready=0;wire req_ready,resp_valid,resp_error,irq;wire [31:0] resp_rdata;
 kwt1_mmio dut(clk,rst_n,abort_hw,core_enable,mem_enable,req_valid,req_ready,req_write,req_addr,req_wdata,req_wstrb,resp_valid,resp_ready,resp_rdata,resp_error,irq);
 integer accepted=0,retired=0,cancelled=0,exchanges=0,depth=0,k,cases=0;
 reg [31:0] expected,held_data;reg expected_error,held_error,held=0;
 always @(posedge clk)begin
  if(!rst_n||abort_hw)begin if(depth!=0)cancelled=cancelled+depth;depth=0;held=0;end
  else begin
   if(held&&(!resp_valid||resp_rdata!==held_data||resp_error!==held_error))$fatal(1,"held response changed");
   if(resp_valid&&resp_ready)begin
    if(depth!=1||resp_rdata!==expected||resp_error!==expected_error)$fatal(1,"response loss/reorder/value");
    depth=0;retired=retired+1;
   end
   if(req_valid&&req_ready)begin
    if(depth!=0)$fatal(1,"accepted without response slot");depth=1;accepted=accepted+1;
    if(resp_valid&&resp_ready)exchanges=exchanges+1;
    expected=0;expected_error=0;
    if(req_write)begin
     if(req_wstrb!=15||req_addr[1:0]!=0)expected_error=1;
     else case(req_addr)0,8,12,16,20:begin end default:expected_error=1;endcase
    end else case(req_addr)
     72:expected=32'h4b575431;
     24:expected=dut.accel.value;
     default:expected_error=1;
    endcase
   end
   // A newly accepted response replaces the one consumed on this same edge.
   held=resp_valid&&!resp_ready;held_data=resp_rdata;held_error=resp_error;
  end
 end
 task issue(input wr,input [31:0] addr,input [31:0] data);
  begin @(negedge clk);req_valid=1;req_write=wr;req_addr=addr;req_wdata=data;
   @(posedge clk);while(!req_ready)@(posedge clk);@(negedge clk);req_valid=0;
  end
 endtask
 task drain;
  begin @(negedge clk);resp_ready=1;@(negedge clk);resp_ready=0;end
 endtask
 task exchange(input wr,input [31:0] addr,input [31:0] data);
  begin @(negedge clk);req_valid=1;req_write=wr;req_addr=addr;req_wdata=data;resp_ready=1;
   #1;if(!req_ready||!resp_valid)$fatal(1,"same-edge handoff unavailable");
   @(negedge clk);req_valid=0;resp_ready=0;
  end
 endtask
 task start_output;
  begin issue(1,0,1);drain();@(negedge clk);dut.accel.value=32'hc5a312ef;dut.accel.output_present=1;issue(0,24,0);dut.accel.output_present=0;end
 endtask
 initial begin
  repeat(3)@(negedge clk);rst_n=1;
  issue(0,72,0);repeat(40)@(negedge clk);
  for(k=0;k<64;k=k+1)begin exchange(0,k%2?72:256,0);repeat(k%3)@(negedge clk);end
  drain();cases=cases+1;
  // Real DATA readiness gates acceptance; held request cannot duplicate writes.
  @(negedge clk);dut.accel.cfg_allow=0;req_valid=1;req_write=1;req_addr=16;req_wdata=32'hbad01234;
  repeat(17)begin @(negedge clk);if(req_ready||resp_valid)$fatal(1,"DATA bypassed ready");end
  dut.accel.cfg_allow=1;@(negedge clk);req_valid=0;drain();
  if(dut.accel.cfg_taken!=1)$fatal(1,"DATA duplicated");cases=cases+1;
  start_output();repeat(40)begin @(negedge clk);if(irq||dut.accel.acks)$fatal(1,"early final ACK");end
  drain();@(negedge clk);if(!irq||dut.accel.acks!=1)$fatal(1,"missing final ACK");cases=cases+1;
  issue(1,0,2);repeat(4)@(negedge clk);if(irq||!resp_valid)$fatal(1,"software abort response lost");drain();
  // Final ACK and software ABORT are accepted on one edge. The internal abort
  // rises after that edge, asynchronously clearing the accelerator endpoint
  // while retaining the wrapper's control response (same as production).
  start_output();exchange(1,0,2);repeat(4)@(negedge clk);
  if(irq||!resp_valid||dut.accel.acks)$fatal(1,"final ACK/ABORT ordering");drain();cases=cases+1;
  start_output();@(negedge clk);abort_hw=1;resp_ready=1;req_valid=1;req_write=0;req_addr=72;
  #1;if(req_ready)$fatal(1,"accepted during hardware abort");@(negedge clk);abort_hw=0;resp_ready=0;req_valid=0;
  repeat(5)@(negedge clk);if(resp_valid||irq||dut.accel.acks)$fatal(1,"hard abort ghost");cases=cases+1;
  start_output();@(negedge clk);rst_n=0;repeat(3)@(negedge clk);rst_n=1;
  repeat(5)@(negedge clk);if(resp_valid||irq||dut.accel.acks)$fatal(1,"reset ghost");cases=cases+1;
  issue(0,72,0);drain();repeat(5)@(negedge clk);
  if(depth||accepted!=retired+cancelled||exchanges<65)$fatal(1,"transaction conservation");
  $display("PASS MMIO cases=%0d exchanges=%0d accepted=%0d retired=%0d reset_discarded=%0d",cases,exchanges,accepted,retired,cancelled);$finish;
 end
 initial begin #100000;$fatal(1,"protocol watchdog cases=%0d request=%b/%b response=%b/%b addr=%h",cases,req_valid,req_ready,resp_valid,resp_ready,req_addr);end
endmodule
