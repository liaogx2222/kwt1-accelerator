// Simulation-only independent observer. Not in production synthesis file list.
module kwt1_observed(input wire clk,rst_n,abort_hw,core_enable,mem_enable,
 input wire req_valid,output wire req_ready,input wire req_write,input wire [31:0] req_addr,req_wdata,input wire [3:0] req_wstrb,
 output wire resp_valid,input wire resp_ready,output wire [31:0] resp_rdata,output wire resp_error,output wire irq);
 kwt1_mmio dut(clk,rst_n,abort_hw,core_enable,mem_enable,req_valid,req_ready,req_write,req_addr,req_wdata,req_wstrb,resp_valid,resp_ready,resp_rdata,resp_error,irq);
 reg [4095:0] path;integer fd,task_number=0,z,idx,op,phase,reason,real_state,live_cells;
 reg [63:0] cycles,compute,reads,writes,issues,retires,launches,valid_mac;
 reg [63:0] sc[0:511],sr[0:511],sw[0:511],si[0:511],st[0:511];
 reg [63:0] pc[0:12],pr[0:12],pw[0:12],pi[0:12],pt[0:12],bc[0:5],mc[0:7],vc[0:7];
 integer last_enabled_state,last_red;
 initial begin fd=0;if($value$plusargs("metrics=%s",path))fd=$fopen(path,"w");end
 always @(posedge clk)begin
  if(!rst_n||abort_hw||dut.sw_abort)begin
   cycles=0;compute=0;reads=0;writes=0;issues=0;retires=0;launches=0;valid_mac=0;last_enabled_state=0;last_red=0;
   for(z=0;z<512;z=z+1)begin sc[z]=0;sr[z]=0;sw[z]=0;si[z]=0;st[z]=0;end
   for(z=0;z<13;z=z+1)begin pc[z]=0;pr[z]=0;pw[z]=0;pi[z]=0;pt[z]=0;end
   for(z=0;z<6;z=z+1)bc[z]=0;for(z=0;z<8;z=z+1)begin mc[z]=0;vc[z]=0;end
  end else if((dut.accel.task_seen||dut.accel.frame_accept||(dut.accel.input_valid&&dut.accel.input_ready))&&!dut.accel.done)begin
   cycles=cycles+1;
   idx=256+dut.accel.state;phase=12;
   if(dut.accel.state==1||dut.accel.state==2)begin
    compute=compute+1;idx=dut.accel.core_state;real_state=idx;
    if(idx>=80&&idx<=93)real_state=dut.accel.core.return_state;
    if(real_state>=1&&real_state<=10)phase=dut.accel.core.kind;
    else if(real_state>=15&&real_state<=18)phase=6;
    else if((real_state>=11&&real_state<=14)||(real_state>=19&&real_state<=26)||(real_state>=69&&real_state<=70))phase=7;
    else if(real_state>=27&&real_state<=32)phase=8;
    else if((real_state>=33&&real_state<=59)||(real_state>=74&&real_state<=76))phase=9;
    else if((real_state>=60&&real_state<=64)||(real_state>=71&&real_state<=73))phase=10;
    else if(real_state==65||real_state==66)phase=11;
    pc[phase]=pc[phase]+1;
    reason=5;
    if(!core_enable)reason=0;else if(!mem_enable)reason=1;
    else if(idx==93&&!dut.accel.core.iter_valid)reason=2;
    else if(idx==91&&!dut.accel.core.math_valid)reason=3;
    else if(dut.accel.core.logical_mvalid&&!dut.accel.core.math_ready)reason=4;
    bc[reason]=bc[reason]+1;
    if(dut.accel.core.math_accept)begin issues=issues+1;si[idx]=si[idx]+1;pi[phase]=pi[phase]+1;end
    if(dut.accel.core.math_take)begin retires=retires+1;st[idx]=st[idx]+1;pt[phase]=pt[phase]+1;end
    if(dut.accel.core.mac_en)begin
     op=idx==17?6:idx==29?7:dut.accel.core.kind;
     live_cells=$countones(dut.accel.core.row_mask)*$countones(dut.accel.core.col_mask);
     launches=launches+1;valid_mac=valid_mac+live_cells;mc[op]=mc[op]+1;vc[op]=vc[op]+live_cells;
`ifdef PIPELINED
     if(dut.accel.core.red>0&&(last_enabled_state!=idx||last_red+1!=dut.accel.core.red))$fatal(1,"MAC recurrence is not one per enabled cycle");
`endif
    end
    if(core_enable&&mem_enable)begin last_enabled_state=idx;last_red=dut.accel.core.red;end
   end
   sc[idx]=sc[idx]+1;
   for(z=0;z<20;z=z+1)if(dut.accel.bank_en[z])begin
    if(dut.accel.bank_we[z])begin writes=writes+1;sw[idx]=sw[idx]+1;if(idx<256)pw[phase]=pw[phase]+1;end
    else begin reads=reads+1;sr[idx]=sr[idx]+1;if(idx<256)pr[phase]=pr[phase]+1;end
   end
   if(dut.ack_output)begin
    if(cycles!=dut.accel.task_cycles+1||compute!=dut.accel.compute_cycles||reads!=dut.accel.read_words||writes!=dut.accel.write_words)$fatal(1,"observer/top counters disagree");
    if(fd)begin
     $fdisplay(fd,"T %0d %0d %0d %0d %0d %0d %0d %0d %0d",task_number,cycles,compute,reads,writes,issues,retires,launches,valid_mac);
     for(z=0;z<512;z=z+1)if(sc[z])$fdisplay(fd,"S %0d %0d %0d %0d %0d %0d %0d",task_number,z,sc[z],sr[z],sw[z],si[z],st[z]);
     for(z=0;z<13;z=z+1)$fdisplay(fd,"P %0d %0d %0d %0d %0d %0d %0d",task_number,z,pc[z],pr[z],pw[z],pi[z],pt[z]);
     for(z=0;z<6;z=z+1)$fdisplay(fd,"B %0d %0d %0d",task_number,z,bc[z]);
     for(z=0;z<8;z=z+1)$fdisplay(fd,"O %0d %0d %0d %0d",task_number,z,mc[z],vc[z]);$fflush(fd);
    end
    task_number=task_number+1;
   end
  end
 end
endmodule
