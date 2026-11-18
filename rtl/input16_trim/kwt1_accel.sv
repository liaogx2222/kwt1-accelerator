// Experimental S16-first-input complete 8x8 baseline. Not the 16x16 model.
// Complete cold-task controller. Production SINGLE_LAYER=0 always executes
// layer0..11; test-only elaboration SINGLE_LAYER=1 validates individual profiles.
// 20x4096x16 SRAM; final result_ack is part of the measured task window.
module kwt1_accel #(parameter SINGLE_LAYER=0)(
 input wire clk,rst_n,abort,input wire core_enable,mem_enable,
 input wire frame_valid,output wire frame_ready,input wire frame_common,input wire [3:0] frame_layer,
 input wire cfg_valid,output wire cfg_ready,input wire [31:0] cfg_data,input wire cfg_last,
 input wire input_valid,output wire input_ready,input wire [31:0] input_data,input wire input_last,
 input wire start_valid,output wire start_ready,
 output wire output_valid,input wire output_ready,output wire [31:0] output_data,output wire output_last,input wire result_ack,
 output wire need_parameters,awaiting_ack,output reg [3:0] current_layer,
 output reg busy,done,error,output reg [7:0] error_code,
 output wire common_valid,input_loaded,layer_valid,output wire [7:0] debug_state,
 output reg [63:0] task_cycles,compute_cycles,read_words,write_words,stall_cycles);
 wire task_rst_n=rst_n&&!abort;
 localparam IDLE=0,KICK=1,RUN=2,WAIT_LAYER=3,OUTPUT_READ=4,OUTPUT_CAPTURE=5,OUTPUT_HOLD=6,ACK_WAIT=7,COMPLETE=8,FAILED=9;
 reg [3:0] state;reg common_ok,input_ok,layer_ok,task_seen;reg [3:0] loaded_layer;
 wire loader_ready,loader_loaded,loader_error,loader_active;
 reg receive_common;reg [3:0] receive_layer;
 wire [19:0] l_en,l_we,c_en,c_we;wire [239:0] l_addr,c_addr;wire [319:0] l_wdata,c_wdata;
 reg [19:0] bank_en,bank_we;reg [239:0] bank_addr;reg [319:0] bank_wdata;wire [319:0] bank_rdata;
 wire core_ready,core_done,core_fault;wire [7:0] core_state;
 reg [7:0] pair_buffer[0:255];reg [5:0] input_word;reg [5:0] input_ch;reg [5:0] pair_index;
 reg input_drain;reg [13:0] input_bytes;
 reg [12:0] output_offset;reg [1:0] gather_byte;reg [31:0] output_hold;
 wire allow_frame=(state==IDLE||state==WAIT_LAYER)&&!input_drain&&input_bytes==0&&!error;
 assign frame_ready=task_rst_n&&allow_frame&&loader_ready&&!loader_loaded&&!(state==WAIT_LAYER&&layer_ok);
 wire frame_accept=frame_valid&&frame_ready;
 wire valid_order=frame_common?(state==IDLE&&!busy):(SINGLE_LAYER?state==IDLE:frame_layer==current_layer);
 kwt_packet_loader loader(clk,task_rst_n,mem_enable,frame_accept&&valid_order,loader_ready,frame_common,frame_layer,
  cfg_valid,cfg_ready,cfg_data,cfg_last,loader_loaded,loader_error,loader_active,l_en,l_we,l_addr,l_wdata);
 kwt_layer_banked core(clk,task_rst_n,core_enable&&mem_enable,state==KICK,core_ready,current_layer,core_done,core_fault,core_state,c_en,c_we,c_addr,c_wdata,bank_rdata);
 kwt_banks banks(clk,bank_en,bank_we,bank_addr,bank_wdata,bank_rdata);
 assign start_ready=task_rst_n&&state==IDLE&&!loader_active&&!input_drain&&!error&&common_ok&&input_ok&&layer_ok&&!frame_valid;
 assign input_ready=task_rst_n&&mem_enable&&state==IDLE&&!loader_active&&!input_drain&&!input_ok&&!error&&!frame_accept;
 assign output_valid=task_rst_n&&state==OUTPUT_HOLD&&!error;
 assign output_data=output_hold;assign output_last=output_offset==6332;
 assign need_parameters=task_rst_n&&state==WAIT_LAYER&&!loader_active&&!loader_loaded&&!layer_ok&&!error;
 assign awaiting_ack=task_rst_n&&state==ACK_WAIT;
 assign common_valid=common_ok;assign input_loaded=input_ok;assign layer_valid=layer_ok;
 assign debug_state=(state==RUN||state==KICK)?core_state:{4'hf,state};
 integer k,ob_token,ob_ch,ob_bank,ob_addr;
 reg [5:0] reads_this_cycle,writes_this_cycle;
 always @* begin
  bank_en=0;bank_we=0;bank_addr=0;bank_wdata=0;ob_token=0;ob_ch=0;ob_bank=0;ob_addr=0;
  if(task_rst_n&&!error)begin
   if(loader_active)begin bank_en=l_en;bank_we=l_we;bank_addr=l_addr;bank_wdata=l_wdata;end
   else if(state==RUN||state==KICK)begin bank_en=c_en;bank_we=c_we;bank_addr=c_addr;bank_wdata=c_wdata;end
   else if(input_drain&&mem_enable)begin
    ob_bank=8+(pair_index%4);ob_addr=(pair_index/4)*64+input_ch;
    bank_en[ob_bank]=1;bank_we[ob_bank]=1;bank_addr[ob_bank*12+:12]=ob_addr;
    bank_wdata[ob_bank*16+:16]={pair_index==49?8'd0:pair_buffer[128+2*input_ch],pair_buffer[2*input_ch]};
    bank_en[ob_bank+4]=1;bank_we[ob_bank+4]=1;bank_addr[(ob_bank+4)*12+:12]=1664+ob_addr;
    bank_wdata[(ob_bank+4)*16+:16]={pair_index==49?8'd0:pair_buffer[129+2*input_ch],pair_buffer[2*input_ch+1]};
   end else if(state==OUTPUT_READ&&mem_enable)begin
    ob_token=output_offset/64;ob_ch=(output_offset%64)+gather_byte;
    ob_bank=8+(ob_token%8)/2;ob_addr=832+(ob_token/8)*64+ob_ch;
    bank_en[ob_bank]=1;bank_addr[ob_bank*12+:12]=ob_addr;
   end
  end
  reads_this_cycle=0;writes_this_cycle=0;
  for(integer p=0;p<20;p=p+1)if(bank_en[p])begin if(bank_we[p])writes_this_cycle=writes_this_cycle+1;else reads_this_cycle=reads_this_cycle+1;end
 end
 always @(posedge clk or negedge task_rst_n)begin
  if(!task_rst_n)begin
   state<=IDLE;common_ok<=0;input_ok<=0;layer_ok<=0;task_seen<=0;loaded_layer<=0;receive_common<=0;receive_layer<=0;current_layer<=0;
   busy<=0;done<=0;error<=0;error_code<=0;input_word<=0;input_ch<=0;pair_index<=0;input_drain<=0;input_bytes<=0;output_offset<=0;gather_byte<=0;output_hold<=0;
   task_cycles<=0;compute_cycles<=0;read_words<=0;write_words<=0;stall_cycles<=0;
  end else begin
   if((task_seen||frame_accept||(input_valid&&input_ready))&&!done)task_cycles<=task_cycles+1;
   if(state==RUN||state==KICK)begin compute_cycles<=compute_cycles+1;if(!core_enable||!mem_enable)stall_cycles<=stall_cycles+1;end
   if(!done)begin read_words<=read_words+reads_this_cycle;write_words<=write_words+writes_this_cycle;end
   if(frame_accept)begin
    task_seen<=1;receive_common<=frame_common;receive_layer<=frame_layer;
    if(frame_common)common_ok<=0;else layer_ok<=0;
    if(!valid_order||frame_layer>11)begin error<=1;error_code<=1;state<=FAILED;end
   end
   if(loader_loaded)begin
    if(receive_common)common_ok<=1;
    else begin layer_ok<=1;loaded_layer<=receive_layer;if(SINGLE_LAYER)current_layer<=receive_layer;end
   end
   if(loader_error)begin error<=1;error_code<=2;state<=FAILED;end
   if(input_valid&&input_ready)begin
    task_seen<=1;
    for(integer z=0;z<4;z=z+1)pair_buffer[input_word*4+z]<=input_data[z*8+:8];
    input_bytes<=input_bytes+4;
    if(input_data[15:0]==16'h8000||input_data[31:16]==16'h8000||(SINGLE_LAYER&&current_layer!=0&&($signed(input_data[15:0])>127||$signed(input_data[15:0])< -127||$signed(input_data[31:16])>127||$signed(input_data[31:16])< -127)))begin error<=1;error_code<=3;state<=FAILED;end
    if(input_last!=(input_bytes==12668))begin error<=1;error_code<=4;state<=FAILED;end
    if(input_word==(pair_index==49?31:63))begin input_word<=0;input_ch<=0;input_drain<=1;end else input_word<=input_word+1;
   end
   if(input_drain&&mem_enable&&!error)begin
    if(input_ch==63)begin
     input_drain<=0;input_ch<=0;
     if(pair_index==49)begin input_ok<=1;input_bytes<=0;end else pair_index<=pair_index+1;
    end else input_ch<=input_ch+1;
   end
   if(!error&&!loader_error&&!(frame_accept&&(!valid_order||frame_layer>11)))case(state)
    IDLE:if(start_valid&&start_ready)begin busy<=1;done<=0;state<=KICK;end
    KICK:if(core_ready&&core_enable&&mem_enable)state<=RUN;
    RUN:begin
     if(core_fault)begin error<=1;error_code<=5;state<=FAILED;end
     else if(core_done)begin
      layer_ok<=0;
      if(SINGLE_LAYER||current_layer==11)begin output_offset<=0;gather_byte<=0;state<=OUTPUT_READ;end
      else begin current_layer<=current_layer+1;state<=WAIT_LAYER;end
     end
    end
    WAIT_LAYER:if(layer_ok&&!loader_active)begin if(loaded_layer==current_layer)state<=KICK;else begin error<=1;error_code<=1;state<=FAILED;end end
    OUTPUT_READ:if(mem_enable)state<=OUTPUT_CAPTURE;
    OUTPUT_CAPTURE:if(mem_enable)begin
     output_hold[gather_byte*8+:8]<=bank_rdata[(8+((output_offset/64)%8)/2)*16+8*((output_offset/64)%2)+:8];
     if(gather_byte==3)state<=OUTPUT_HOLD;else begin gather_byte<=gather_byte+1;state<=OUTPUT_READ;end
    end
    OUTPUT_HOLD:if(output_valid&&output_ready)begin
     if(output_last)state<=ACK_WAIT;else begin output_offset<=output_offset+4;gather_byte<=0;state<=OUTPUT_READ;end
    end
    ACK_WAIT:if(result_ack)begin busy<=0;done<=1;state<=COMPLETE;end
   endcase
  end
 end
endmodule
