module tb_layer_control;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,core_enable=1,mem_enable=1,frame_valid=0,frame_common=0,cfg_valid=0,cfg_last=0;
 reg [3:0] frame_layer=0;reg [31:0] cfg_data=0,input_data=0;reg input_valid=0,input_last=0,start_valid=0,output_ready=1;
 wire frame_ready,cfg_ready,input_ready,start_ready,output_valid,output_last,done,error;wire [31:0] output_data;wire [7:0] state;
 kwt_layer dut(clk,rst_n,core_enable,mem_enable,frame_valid,frame_ready,frame_common,frame_layer,
  cfg_valid,cfg_ready,cfg_data,cfg_last,input_valid,input_ready,input_data,input_last,start_valid,start_ready,
  output_valid,output_ready,output_data,output_last,done,error,state);
 reg [31:0] packet[0:15431],inputs[0:1583];reg [4095:0] root,path;
 integer i,j,target,watch,resets=0;reg [31:0] old_header;
 task reset_task;
  begin @(negedge clk);rst_n=0;frame_valid=0;cfg_valid=0;input_valid=0;start_valid=0;
   repeat(2)@(negedge clk);rst_n=1;resets=resets+1;
   repeat(100)begin @(posedge clk);#1;if(start_ready||output_valid||done||state!=0)$fatal(1,"stale reset");end
  end
 endtask
 task load_packet(input integer iscommon);
  integer n,k;begin
   path=iscommon?{root,"/common.bin.hex"}:{root,"/layer_00.bin.hex"};n=iscommon?4144:15432;
   if(iscommon)$readmemh(path,packet,0,4143);else $readmemh(path,packet,0,15431);
   @(negedge clk);frame_valid=1;frame_common=iscommon;frame_layer=0;
   @(posedge clk);if(!frame_ready)$fatal(1,"frame blocked");@(negedge clk);frame_valid=0;
   for(k=0;k<n;k=k+1)begin @(negedge clk);cfg_valid=1;cfg_data=packet[k];cfg_last=k==n-1;@(posedge clk);if(!cfg_ready)$fatal(1,"cfg blocked");end
   @(negedge clk);cfg_valid=0;cfg_last=0;if(error)$fatal(1,"good packet rejected");
  end
 endtask
 task load_input;
  integer k;begin
   for(k=0;k<1584;k=k+1)begin @(negedge clk);input_valid=1;input_data=inputs[k];input_last=k==1583;@(posedge clk);if(!input_ready)$fatal(1,"input blocked");end
   @(negedge clk);input_valid=0;input_last=0;
  end
 endtask
 task launch;
  begin @(negedge clk);start_valid=1;@(posedge clk);if(!start_ready)$fatal(1,"start blocked");@(negedge clk);start_valid=0;end
 endtask
 initial begin
  if(!$value$plusargs("root=%s",root))$fatal(1,"root");
  path={root,"/input_000.hex"};$readmemh(path,inputs);reset_task();
  // Partial input reset, forbidden -128 and wrong input TLAST.
  for(i=0;i<17;i=i+1)begin @(negedge clk);input_valid=1;input_data=inputs[i];@(posedge clk);end
  reset_task();
  @(negedge clk);input_valid=1;input_data=32'h00000080;input_last=0;@(posedge clk);#1;if(!error)$fatal(1,"-128 accepted");reset_task();
  @(negedge clk);input_valid=1;input_data=0;input_last=1;@(posedge clk);#1;if(!error||start_ready)$fatal(1,"early input TLAST accepted");reset_task();
  @(negedge clk);frame_valid=1;frame_layer=15;@(posedge clk);#1;if(!error||dut.active)$fatal(1,"bad profile accepted");reset_task();
  // Abort pending Softmax divide, LN sqrt and LN reciprocal divide.
  for(j=0;j<3;j=j+1)begin
   load_packet(1);load_packet(0);load_input();launch();target=j==0?9:(j==1?18:20);watch=0;
   while(state!=target)begin @(posedge clk);watch=watch+1;if(watch>400000)$fatal(1,"control state timeout");end
   old_header=dut.par[0];
   @(negedge clk);frame_valid=1;cfg_valid=1;cfg_data=32'hbadbad;cfg_last=1;
   repeat(5)begin @(posedge clk);#1;if(frame_ready||cfg_ready||dut.par[0]!==old_header)$fatal(1,"busy overwrite");end
   reset_task();
  end
  $display("PASS control resets=%0d input_errors=2 bad_profile=1 busy_overwrite=3 iterative_resets=3",resets);$finish;
 end
endmodule
