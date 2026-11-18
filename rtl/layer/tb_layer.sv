module tb_layer;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,core_enable=1,mem_enable=1,frame_valid=0,frame_common=0,cfg_valid=0,cfg_last=0;
 reg [3:0] frame_layer=0;reg [31:0] cfg_data=0,input_data=0;reg input_valid=0,input_last=0,start_valid=0,output_ready=1;
 wire frame_ready,cfg_ready,input_ready,start_ready,output_valid,output_last,done,error;wire [31:0] output_data;wire [7:0] state;
 kwt_layer dut(clk,rst_n,core_enable,mem_enable,frame_valid,frame_ready,frame_common,frame_layer,
  cfg_valid,cfg_ready,cfg_data,cfg_last,input_valid,input_ready,input_data,input_last,start_valid,start_ready,
  output_valid,output_ready,output_data,output_last,done,error,state);
 reg [31:0] packet[0:15431],inputs[0:1583],expected[0:1583],debugmem[0:6335];
 reg [4095:0] root,path;integer cycles=0,received=0,caseid,profile,fd,n,metrics,cases=0,stalls=0,resets=0,ack;
 integer i,j,watch,begin_cycle,status,output_file;reg checking=0,force_hold=0,was_held=0;reg [31:0] held_word;
 always @(negedge clk)begin
  cycles=cycles+1;core_enable=(cycles%11!=0&&cycles%17!=0);mem_enable=(cycles%7!=0);
  if(cycles%10000==0)begin $fdisplay(status,"cycle=%0d state=%0d pos=%0d active=%0d case=%0d sent=%0d received=%0d",cycles,state,dut.pos,dut.active,caseid,dut.sent,dut.received);$fflush(status);end
  output_ready=!force_hold&&(cycles%9!=0&&cycles%9!=1);
 end
 always @(posedge clk)begin
  if(!rst_n)was_held=0;
  else begin
   if(was_held && (!output_valid||output_data!==held_word))$fatal(1,"held output changed");
   was_held=output_valid&&!output_ready;held_word=output_data;
   if(output_valid&&!output_ready)stalls=stalls+1;
   if(checking&&output_valid&&output_ready)begin
    $fdisplay(output_file,"%08h",output_data);
    if(output_data!==expected[received])begin
     $display("MISMATCH case=%0d profile=%0d word=%0d got=%h expected=%h",caseid,profile,received,output_data,expected[received]);
     $fatal(1,"output differs");
    end
    if(output_last!==(received==1583))$fatal(1,"output TLAST");
    received=received+1;
   end
  end
 end
 task reset_task;
  begin
   @(negedge clk);rst_n=0;frame_valid=0;cfg_valid=0;input_valid=0;start_valid=0;checking=0;force_hold=0;
   repeat(3)@(negedge clk);rst_n=1;resets=resets+1;
   repeat(100)begin @(posedge clk);#1;if(start_ready||output_valid||done||state!=0)$fatal(1,"stale reset state");end
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
    @(negedge clk);data=packet[k];
    if((bad==1&&k==count-1)||(bad==2&&k==0)||(bad==3&&k==31))data=data^32'd1;
    cfg_data=data;cfg_last=(k==limit-1);cfg_valid=1;
    @(posedge clk);while(!cfg_ready)@(posedge clk);
   end
   @(negedge clk);cfg_valid=0;cfg_last=0;
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
  end
 endtask
 task launch;
  begin
   @(negedge clk);start_valid=1;
   @(posedge clk);if(!start_ready)$fatal(1,"START not ready");
   @(negedge clk);start_valid=0;
  end
 endtask
 task check_job;
  begin
   $sformat(path,"%0s/expected_%03d.hex",root,caseid);$readmemh(path,expected);
   $sformat(path,"%0s/observed_%03d.hex",root,caseid);output_file=$fopen(path,"w");
   load_input();checking=1;received=0;begin_cycle=cycles;launch();watch=0;
   while(received<1584)begin @(posedge clk);#1;watch=watch+1;if(error)$fatal(1,"DUT arithmetic/protocol error state=%0d",state);if(watch>2500000)$fatal(1,"job timeout state=%0d",state);end
   checking=0;$fclose(output_file);
   $display("CASE %0d profile=%0d cycles=%0d codes=6336 PASS",caseid,profile,cycles-begin_cycle);
   $fdisplay(metrics,"%0d %0d %0d 6336 0",caseid,profile,cycles-begin_cycle);$fflush(metrics);
   repeat(3)@(posedge clk);
  end
 endtask
 initial begin
  if(!$value$plusargs("root=%s",root))$fatal(1,"missing root");
  metrics=$fopen({root,"/metrics.txt"},"w");
  status=$fopen({root,"/status.txt"},"w");
  reset_task();
  // Real corrupted canonical packets, and early TLAST. No valid slot survives.
  packet_send(1,0,1,0);if(!error||start_ready)$fatal(1,"CRC error accepted");
  packet_send(1,0,2,0);if(!error||start_ready)$fatal(1,"header error accepted");
  packet_send(1,0,3,0);if(!error||start_ready)$fatal(1,"layout error accepted");
  packet_send(1,0,0,25);if(!error||start_ready)$fatal(1,"truncated accepted");
  // Reset in header, directory, payload. No new data, 100 idle edges.
  for(j=0;j<3;j=j+1)begin
   frame_start(1,0);
   for(i=0;i<(j==0?5:(j==1?20:200));i=i+1)begin
    @(negedge clk);cfg_valid=1;cfg_data=packet[i];cfg_last=0;
    @(posedge clk);while(!cfg_ready)@(posedge clk);
   end
   reset_task();
  end
  caseid=0;profile=0;
  // Mid-MAC reset on a real input; abort and reload cold.
  packet_send(1,0,0,0);packet_send(0,0,0,0);load_input();launch();repeat(1000)@(posedge clk);reset_task();
  // All cases reuse this same DUT. Every case reloads common + its layer.
  fd=$fopen({root,"/cases.txt"},"r");
  while(!$feof(fd))begin
   n=$fscanf(fd,"%d %d\n",caseid,profile);
   if(n==2)begin
    packet_send(1,profile,0,0);packet_send(0,profile,0,0);check_job();cases=cases+1;
   end
  end
  // A complete computation held at final response, then reset cancels it.
  caseid=0;profile=0;packet_send(1,0,0,0);packet_send(0,0,0,0);load_input();force_hold=1;launch();watch=0;
  while(!output_valid)begin @(posedge clk);watch=watch+1;if(watch>2500000)$fatal(1,"held reset timeout");end
  repeat(20)@(posedge clk);reset_task();
  $display("PASS cases=%0d codes=%0d output_stalls=%0d resets=%0d errors=4",cases,cases*6336,stalls,resets);
  $fclose(metrics);$finish;
 end
endmodule
