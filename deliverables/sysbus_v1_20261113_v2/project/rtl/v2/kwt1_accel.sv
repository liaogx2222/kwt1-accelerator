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
 output wire need_parameters,awaiting_ack,output wire [3:0] current_layer,
 output reg busy,done,error,output reg [7:0] error_code,
 output wire common_valid,input_loaded,layer_valid,output wire [7:0] debug_state,
 output reg [63:0] task_cycles,compute_cycles,read_words,write_words,stall_cycles);
 wire task_rst_n=rst_n&&!abort;
 localparam IDLE=0,KICK=1,RUN=2,WAIT_LAYER=3,OUTPUT_READ=4,OUTPUT_CAPTURE=5,OUTPUT_HOLD=6,ACK_WAIT=7,COMPLETE=8,FAILED=9;
 reg [3:0] state;reg common_ok,input_ok,layer_ok,task_seen;reg [3:0] loaded_layer,active_layer;
 reg parameter_slot,receive_slot,loaded_slot,receive_next,next_ok;
 wire loader_ready,loader_loaded,loader_error,loader_active;
 reg receive_common;reg [3:0] receive_layer;
 wire [19:0] l_en,l_we,c_en,c_we;wire [239:0] l_addr,c_addr;wire [319:0] l_wdata,c_wdata;
 reg [19:0] bank_en,bank_we;reg [239:0] bank_addr;reg [319:0] bank_wdata;wire [319:0] bank_rdata;
 wire core_ready,core_done,core_fault,core_prefetch;wire [7:0] core_state;
 wire prefetch_window=!SINGLE_LAYER&&state==RUN&&active_layer<11&&core_prefetch&&!error;
 wire target_slot=state==IDLE?1'b0:!parameter_slot;
 wire loader_grant=mem_enable&&!error&&(!(state==RUN||state==KICK)||!(|(l_en&c_en)));
 reg [7:0] pair_buffer[0:255];reg [5:0] input_word;reg [6:0] input_ch;reg [5:0] pair_index;
 reg input_drain;reg [13:0] input_bytes;
 reg [12:0] output_offset;reg [1:0] gather_byte;reg [31:0] output_hold;
 wire allow_frame=(state==IDLE||state==WAIT_LAYER||prefetch_window)&&!input_drain&&input_bytes==0&&!error;
 assign frame_ready=task_rst_n&&allow_frame&&loader_ready&&!loader_loaded&&!(state==WAIT_LAYER&&layer_ok)&&!next_ok;
 wire frame_accept=frame_valid&&frame_ready;
 wire valid_order=frame_common?(state==IDLE&&!busy):(SINGLE_LAYER?state==IDLE:frame_layer==current_layer);
 kwt_packet_loader loader(clk,task_rst_n,loader_grant,frame_accept&&valid_order,loader_ready,frame_common,frame_layer,
  cfg_valid,cfg_ready,cfg_data,cfg_last,loader_loaded,loader_error,loader_active,l_en,l_we,l_addr,l_wdata,target_slot);
 kwt_layer_banked core(clk,task_rst_n,core_enable&&mem_enable&&!error,state==KICK,core_ready,active_layer,core_done,core_fault,core_state,c_en,c_we,c_addr,c_wdata,bank_rdata,parameter_slot,core_prefetch);
 kwt_banks banks(clk,bank_en,bank_we,bank_addr,bank_wdata,bank_rdata);
 assign start_ready=task_rst_n&&state==IDLE&&!loader_active&&!input_drain&&!error&&common_ok&&input_ok&&layer_ok&&!frame_valid;
 assign input_ready=task_rst_n&&mem_enable&&state==IDLE&&!loader_active&&!input_drain&&!input_ok&&!error&&!frame_accept;
 assign output_valid=task_rst_n&&state==OUTPUT_HOLD&&!error;
 assign output_data=output_hold;assign output_last=output_offset==6332;
 assign need_parameters=task_rst_n&&(state==WAIT_LAYER||prefetch_window)&&!loader_active&&!loader_loaded&&!next_ok&&!(state==WAIT_LAYER&&layer_ok)&&!error;
 assign current_layer=prefetch_window?active_layer+4'd1:active_layer;
 assign awaiting_ack=task_rst_n&&state==ACK_WAIT;
 assign common_valid=common_ok;assign input_loaded=input_ok;assign layer_valid=prefetch_window?next_ok:(layer_ok||next_ok);
 assign debug_state=(state==RUN||state==KICK)?core_state:{4'hf,state};
 integer k,ob_token,ob_ch,ob_bank,ob_addr;
 reg [5:0] reads_this_cycle,writes_this_cycle;
 always @* begin
  bank_en=0;bank_we=0;bank_addr=0;bank_wdata=0;ob_token=0;ob_ch=0;ob_bank=0;ob_addr=0;
  if(task_rst_n&&!error)begin
   if(loader_active&&loader_grant)begin bank_en=l_en;bank_we=l_we;bank_addr=l_addr;bank_wdata=l_wdata;end
   if(state==RUN||state==KICK)begin
    for(integer b=0;b<20;b=b+1)if(c_en[b])begin
     bank_en[b]=1;bank_we[b]=c_we[b];bank_addr[b*12+:12]=c_addr[b*12+:12];bank_wdata[b*16+:16]=c_wdata[b*16+:16];
    end
   end
   else if(input_drain&&mem_enable)begin
    if(SINGLE_LAYER&&loaded_layer!=0)begin
     ob_bank=8+(pair_index%8);ob_addr=(pair_index/8)*64+input_ch;
     bank_wdata[ob_bank*16+:16]={pair_index==49?8'd0:pair_buffer[128+2*input_ch],pair_buffer[2*input_ch]};
    end else begin
     ob_bank=8+((2*pair_index+input_ch/64)%8);ob_addr=2688+((2*pair_index+input_ch/64)/8)*64+input_ch%64;
     bank_wdata[ob_bank*16+:16]={pair_buffer[2*input_ch+1],pair_buffer[2*input_ch]};
    end
    bank_en[ob_bank]=1;bank_we[ob_bank]=1;bank_addr[ob_bank*12+:12]=ob_addr;
   end else if(state==OUTPUT_READ&&mem_enable)begin
    ob_token=output_offset/64;ob_ch=(output_offset%64)+gather_byte;
    ob_bank=8+(ob_token%16)/2;ob_addr=448+(ob_token/16)*64+ob_ch;
    bank_en[ob_bank]=1;bank_addr[ob_bank*12+:12]=ob_addr;
   end
  end
  reads_this_cycle=0;writes_this_cycle=0;
  for(integer p=0;p<20;p=p+1)if(bank_en[p])begin if(bank_we[p])writes_this_cycle=writes_this_cycle+1;else reads_this_cycle=reads_this_cycle+1;end
 end
 always @(posedge clk or negedge task_rst_n)begin
  if(!task_rst_n)begin
   state<=IDLE;common_ok<=0;input_ok<=0;layer_ok<=0;task_seen<=0;loaded_layer<=0;receive_common<=0;receive_layer<=0;active_layer<=0;
   parameter_slot<=0;receive_slot<=0;loaded_slot<=0;receive_next<=0;next_ok<=0;
   busy<=0;done<=0;error<=0;error_code<=0;input_word<=0;input_ch<=0;pair_index<=0;input_drain<=0;input_bytes<=0;output_offset<=0;gather_byte<=0;output_hold<=0;
   task_cycles<=0;compute_cycles<=0;read_words<=0;write_words<=0;stall_cycles<=0;
  end else begin
   if((task_seen||frame_accept||(input_valid&&input_ready))&&!done)task_cycles<=task_cycles+1;
   if(state==RUN||state==KICK)begin compute_cycles<=compute_cycles+1;if(!core_enable||!mem_enable)stall_cycles<=stall_cycles+1;end
   if(!done)begin read_words<=read_words+reads_this_cycle;write_words<=write_words+writes_this_cycle;end
   if(frame_accept)begin
    task_seen<=1;receive_common<=frame_common;receive_layer<=frame_layer;receive_next<=state!=IDLE;receive_slot<=target_slot;
    if(frame_common)common_ok<=0;else if(state==IDLE)layer_ok<=0;else next_ok<=0;
    if(!valid_order||frame_layer>11)begin error<=1;error_code<=1;state<=FAILED;end
   end
   if(loader_loaded)begin
    if(receive_common)common_ok<=1;
    else begin
     loaded_layer<=receive_layer;loaded_slot<=receive_slot;
     if(receive_next)next_ok<=1;else layer_ok<=1;
     if(SINGLE_LAYER)active_layer<=receive_layer;
    end
   end
   if(loader_error)begin error<=1;error_code<=2;state<=FAILED;end
   if(input_valid&&input_ready)begin
    task_seen<=1;
    for(integer z=0;z<4;z=z+1)pair_buffer[input_word*4+z]<=input_data[z*8+:8];
    input_bytes<=input_bytes+4;
    if(input_data[15:0]==16'h8000||input_data[31:16]==16'h8000)begin error<=1;error_code<=3;state<=FAILED;end
    if(input_last!=(input_bytes==12668))begin error<=1;error_code<=4;state<=FAILED;end
    if(input_word==(pair_index==49?31:63))begin input_word<=0;input_ch<=0;input_drain<=1;end else input_word<=input_word+1;
   end
   if(input_drain&&mem_enable&&!error)begin
    if(input_ch==(SINGLE_LAYER&&loaded_layer!=0?63:pair_index==49?63:127))begin
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
      if(SINGLE_LAYER||active_layer==11)begin output_offset<=0;gather_byte<=0;state<=OUTPUT_READ;end
      else begin
       active_layer<=active_layer+1;
       if(next_ok&&!loader_active)begin
        if(loaded_layer==active_layer+1)begin parameter_slot<=loaded_slot;next_ok<=0;layer_ok<=1;state<=KICK;end
        else begin error<=1;error_code<=1;state<=FAILED;end
       end else state<=WAIT_LAYER;
      end
     end
    end
    WAIT_LAYER:if((layer_ok||next_ok)&&!loader_active)begin
     if(loaded_layer==active_layer)begin parameter_slot<=loaded_slot;layer_ok<=1;next_ok<=0;state<=KICK;end
     else begin error<=1;error_code<=1;state<=FAILED;end
    end
    OUTPUT_READ:if(mem_enable)state<=OUTPUT_CAPTURE;
    OUTPUT_CAPTURE:if(mem_enable)begin
     output_hold[gather_byte*8+:8]<=bank_rdata[(8+((output_offset/64)%16)/2)*16+8*((output_offset/64)%2)+:8];
     if(gather_byte==3)state<=OUTPUT_HOLD;else begin gather_byte<=gather_byte+1;state<=OUTPUT_READ;end
    end
    OUTPUT_HOLD:if(output_valid&&output_ready)begin
     if(output_last)state<=ACK_WAIT;else begin output_offset<=output_offset+4;gather_byte<=0;state<=OUTPUT_READ;end
    end
    ACK_WAIT:if(result_ack)begin busy<=0;done<=1;state<=COMPLETE;end
   endcase
  end
 end
`ifdef KWT_SIM
 // Contract checker shared by the host and actual E203 elaborations. This
 // only observes real bank accesses; no SRAM data are initialized here.
 reg sim_written[0:81919];reg sim_in_reset=0;
 integer sim_bank,sim_word,sim_i;
 integer sim_prefetch_frames,sim_overlap_writes,sim_loader_stalls;
 always @(posedge clk)begin
  if(!task_rst_n)begin
   if(!sim_in_reset)for(sim_i=0;sim_i<81920;sim_i=sim_i+1)sim_written[sim_i]=0;
   sim_in_reset=1;sim_prefetch_frames=0;sim_overlap_writes=0;sim_loader_stalls=0;
  end else begin
   sim_in_reset=0;
   if(frame_accept&&state==RUN)sim_prefetch_frames=sim_prefetch_frames+1;
   if(state==RUN&&loader_active&&(|l_en))begin
    if(loader_grant)sim_overlap_writes=sim_overlap_writes+1;else sim_loader_stalls=sim_loader_stalls+1;
    if(!receive_next||!core_prefetch)$fatal(1,"prefetch before current FC1 last consumer");
    for(sim_bank=0;sim_bank<20;sim_bank=sim_bank+1)if(l_en[sim_bank])begin
     sim_word=l_addr[sim_bank*12+:12];
     if(sim_bank<8)begin
      if(sim_word>=2048&&((sim_word>>10)&1)==parameter_slot)$fatal(1,"prefetch overwrote live FC2 slot");
     end else if(sim_bank==16||sim_bank==17)begin
      if((sim_word>>11)==parameter_slot)$fatal(1,"prefetch overwrote live coefficient slot");
     end else $fatal(1,"prefetch wrote non-parameter bank");
    end
   end
   if(loader_grant&&(state==RUN||state==KICK)&&(|(l_en&c_en)))$fatal(1,"single-port bank ownership collision");
   if(state==KICK&&core_ready&&core_enable&&mem_enable)
    if(!layer_ok||loaded_layer!=active_layer||loaded_slot!=parameter_slot||loader_active)$fatal(1,"layer started without CRC-published slot");
   for(sim_bank=0;sim_bank<20;sim_bank=sim_bank+1)if(bank_en[sim_bank])begin
    sim_word=sim_bank*4096+bank_addr[sim_bank*12+:12];
    if(bank_we[sim_bank])sim_written[sim_word]=1;
    else if(!sim_written[sim_word])$fatal(1,"read before current-task write bank=%0d addr=%0d layer=%0d state=%0d",sim_bank,sim_word%4096,active_layer,core_state);
   end
   if(state==ACK_WAIT&&result_ack)$display("PREFETCH_METRICS frames=%0d write_cycles=%0d stall_cycles=%0d",sim_prefetch_frames,sim_overlap_writes,sim_loader_stalls);
  end
 end
`endif
endmodule
