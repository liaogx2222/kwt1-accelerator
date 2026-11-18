module tb_accel;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,abort=0,core_enable=1,mem_enable=1,frame_valid=0,frame_common=0,cfg_valid=0,cfg_last=0;
 reg [3:0] frame_layer=0;reg [31:0] cfg_data=0,input_data=0;reg input_valid=0,input_last=0,start_valid=0,output_ready=1,result_ack=0;
 wire frame_ready,cfg_ready,input_ready,start_ready,output_valid,output_last,done,error,busy,need_parameters,awaiting_ack;
 wire common_valid,input_loaded,layer_valid;wire [31:0] output_data;wire [7:0] state,error_code;wire [3:0] layer;
 wire [63:0] task_cycles,compute_cycles,read_words,write_words,stall_cycles;
`ifdef FULL_MODEL
 localparam SINGLE=0;
`else
 localparam SINGLE=1;
`endif
 kwt1_accel #(.SINGLE_LAYER(SINGLE)) dut(clk,rst_n,abort,core_enable,mem_enable,frame_valid,frame_ready,frame_common,frame_layer,
 cfg_valid,cfg_ready,cfg_data,cfg_last,input_valid,input_ready,input_data,input_last,start_valid,start_ready,
 output_valid,output_ready,output_data,output_last,result_ack,need_parameters,awaiting_ack,layer,busy,done,error,error_code,
 common_valid,input_loaded,layer_valid,state,task_cycles,compute_cycles,read_words,write_words,stall_cycles);
 reg [31:0] packet[0:15431],inputs[0:1583],expected[0:1583];
`ifdef CROSS_SMOKE
 reg [31:0] golden_ln1[0:1583];integer cross_c;
 always @(negedge clk)if(rst_n&&!abort&&dut.core.token==1&&dut.core.kind==3&&state==15)begin
  for(cross_c=0;cross_c<64;cross_c=cross_c+1)
   if({24'd0,dut.banks.bank[8].ram.mem[cross_c][7:0]}!==((golden_ln1[cross_c/4]>>(8*(cross_c%4)))&255))$fatal(1,"cross simulator Attention/LN row mismatch channel=%0d",cross_c);
  $display("PASS CROSS Attention Softmax PV residual LN row=0 codes=64");$finish;
 end
`endif
 reg [4095:0] root,path;integer cycles=0,received=0,caseid=0,profile=0,fd,n,metrics,cases=0,stalls=0,resets=0;
 integer i,j,watch,status,output_file;reg checking=0,was_held=0,force_hold=0;reg [31:0] held_word;
 always @(negedge clk)begin
  cycles=cycles+1;core_enable=(cycles%11!=0&&cycles%17!=0);mem_enable=(cycles%7!=0);
  if(cycles%100000==0)begin $fdisplay(status,"cycle=%0d state=%0d layer=%0d kind=%0d token=%0d oc=%0d sent=%0d received=%0d",cycles,state,layer,dut.core.kind,dut.core.token,dut.core.oc,dut.core.sent,dut.core.received);$fflush(status);end
  output_ready=!force_hold&&(cycles%9!=0&&cycles%9!=1);
 end
 always @(posedge clk)begin
  if(!rst_n||abort)was_held=0;
  else begin
   if(was_held&&(!output_valid||output_data!==held_word))$fatal(1,"held output changed");
   was_held=output_valid&&!output_ready;held_word=output_data;
   if(output_valid&&!output_ready)stalls=stalls+1;
   if(checking&&output_valid&&output_ready)begin
    $fdisplay(output_file,"%08h",output_data);
    if(output_data!==expected[received])$fatal(1,"MISMATCH case=%0d profile=%0d word=%0d got=%h expected=%h",caseid,profile,received,output_data,expected[received]);
    if(output_last!==(received==1583))$fatal(1,"output TLAST");received=received+1;
   end
  end
 end
 task reset_task;
  begin
   @(negedge clk);abort=1;frame_valid=0;cfg_valid=0;input_valid=0;start_valid=0;checking=0;result_ack=0;force_hold=0;
   repeat(3)@(negedge clk);rst_n=1;abort=0;resets=resets+1;
   repeat(10)begin @(posedge clk);#1;if(start_ready||output_valid||done||busy||error||common_valid||input_loaded||layer_valid||task_cycles!=0)$fatal(1,"stale reset state");end
  end
 endtask
 task frame_start(input integer common_flag,input integer layer_id);
  begin
   @(negedge clk);frame_common=common_flag;frame_layer=layer_id;frame_valid=1;
   @(posedge clk);while(!frame_ready)@(posedge clk);
   @(negedge clk);frame_valid=0;
  end
 endtask
 task packet_send(input integer common_flag,input integer layer_id,input integer bad,input integer limit_words);
  integer count,k,limit;reg [31:0] data;
  begin
   if(common_flag)path={root,"/common.bin.hex"};else $sformat(path,"%0s/layer_%02d.bin.hex",root,layer_id);
   if(common_flag)$readmemh(path,packet,0,4143);else $readmemh(path,packet,0,15431);
   frame_start(common_flag,layer_id);count=common_flag?4144:15432;limit=limit_words==0?count:limit_words;
   for(k=0;k<limit;k=k+1)begin
    @(negedge clk);data=packet[k];if((bad==1&&k==count-1)||(bad==2&&k==0)||(bad==3&&k==31))data=data^32'd1;
    cfg_data=data;cfg_last=(k==limit-1);cfg_valid=1;
    @(posedge clk);while(!cfg_ready)@(posedge clk);
   end
   @(negedge clk);cfg_valid=0;cfg_last=0;
   repeat(8)@(negedge clk);
  end
 endtask
 task load_input;
  integer k;
  begin
   $sformat(path,"%0s/input_%03d.hex",root,caseid);$readmemh(path,inputs);
   for(k=0;k<1584;k=k+1)begin
    @(negedge clk);input_valid=1;input_data=inputs[k];input_last=(k==1583);
    @(posedge clk);while(!input_ready)@(posedge clk);
   end
   @(negedge clk);input_valid=0;input_last=0;
   while(!input_loaded&&!error)@(negedge clk);
  end
 endtask
 task launch;
  begin
   @(negedge clk);start_valid=1;
   @(posedge clk);if(!start_ready)$fatal(1,"START not ready error=%0d",error_code);
   @(negedge clk);start_valid=0;
  end
 endtask
 task check_job;
  integer next_layer;
  reg [63:0] frozen_cycles;
  begin
   $sformat(path,"%0s/expected_%03d.hex",root,caseid);$readmemh(path,expected);
   $sformat(path,"%0s/observed_%03d.hex",root,caseid);output_file=$fopen(path,"w");
   load_input();checking=1;received=0;launch();watch=0;next_layer=1;
   while(received<1584)begin
    @(negedge clk);watch=watch+1;
    if(error)$fatal(1,"DUT error=%0d state=%0d",error_code,state);
    if(watch>20000000)$fatal(1,"job timeout state=%0d",state);
    if(!SINGLE&&need_parameters)begin packet_send(0,next_layer,0,0);next_layer=next_layer+1;end
   end
   checking=0;$fclose(output_file);
   repeat(20)begin @(negedge clk);if(!busy||done||!awaiting_ack)$fatal(1,"completion before final acknowledgement");end
   @(negedge clk);result_ack=1;@(negedge clk);result_ack=0;
   if(!done||busy)$fatal(1,"missing final completion");frozen_cycles=task_cycles;
   repeat(10)@(negedge clk);if(task_cycles!=frozen_cycles)$fatal(1,"counter after completion");
   $display("CASE %0d profile=%0d cycles=%0d compute=%0d reads=%0d writes=%0d PASS",caseid,profile,task_cycles,compute_cycles,read_words,write_words);
   $fdisplay(metrics,"%0d %0d %0d %0d %0d %0d %0d",caseid,profile,task_cycles,compute_cycles,read_words,write_words,stall_cycles);$fflush(metrics);
  end
 endtask
 initial begin
  if(!$value$plusargs("root=%s",root))$fatal(1,"missing root");
  metrics=$fopen({root,"/metrics.txt"},"w");status=$fopen({root,"/status.txt"},"w");
`ifdef CROSS_SMOKE
  $readmemh({root,"/layernorm1_output.hex"},golden_ln1);
`endif
  reset_task();
  fd=$fopen({root,"/cases.txt"},"r");
  while(!$feof(fd))begin
   n=$fscanf(fd,"%d %d\n",caseid,profile);
   if(n==2)begin packet_send(1,0,0,0);packet_send(0,profile,0,0);check_job();cases=cases+1;reset_task();end
  end
  $display("PASS cases=%0d codes=%0d stalls=%0d resets=%0d",cases,cases*6336,stalls,resets);
  $fclose(metrics);$fclose(status);$finish;
 end
endmodule
