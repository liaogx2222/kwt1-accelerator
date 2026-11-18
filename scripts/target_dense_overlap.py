"""Verification-only instrumentation; never changes production or host timing."""
def once(s,old,new):
    assert s.count(old)==1,(s.count(old),old);return s.replace(old,new)

def instrument(s,error_checks=False):
    core='dut.u_kwt1_mmio.accel.core.'
    cases='''       11:wait(CORElayer==1&&COREstate==7&&COREdq_live&&COREmath_valid);
       12:wait(COREstate==94&&COREdq_tail&&COREmath_valid);
       13:wait(CORElayer==0&&COREkind==0&&COREstate==94&&COREmath_valid);
'''.replace('CORE',core)
    if error_checks:cases+='       14:wait(dense_error_checked);\n'
    s=once(s,'       default:$fatal(1,"LOCAL_RESET_POINT");',cases+'       default:$fatal(1,"LOCAL_RESET_POINT");')
    begin=s.index(' integer stall_lane;');end=s.index(' integer nice_reads=',begin)
    body=''' integer stall_lane;reg [8:0]stall_red,stall_sent,stall_received;
 reg[7:0]stall_state;reg[4095:0]stall_acc;
 reg [63:0]stall_result[0:3];reg[7:0]stall_tag[0:3];integer stall_test;
 initial if($test$plusargs("STALL_DENSE"))begin
  wait(erst_n===1);
  for(stall_test=0;stall_test<2;stall_test=stall_test+1)begin
   if(stall_test==0)wait(CORElayer==1&&COREstate==7&&COREdq_live&&COREmath_valid);
   else wait(COREstate==94&&COREdq_tail&&COREmath_valid);
   @(negedge hfextclk);
   stall_state=COREstate;stall_red=COREred;stall_sent=COREsent;stall_received=COREreceived;stall_acc=COREacc;
   for(stall_lane=0;stall_lane<4;stall_lane=stall_lane+1)begin
    stall_result[stall_lane]=CORElane_result[stall_lane];stall_tag[stall_lane]=CORElane_tag[stall_lane];
   end
   force dut.u_kwt1_mmio.accel.core_enable=1'b0;
   repeat(stall_test==0?17:11)begin
    @(negedge hfextclk);
    if(COREstate!=stall_state||COREred!=stall_red||COREsent!=stall_sent||COREreceived!=stall_received||COREacc!==stall_acc||
       !COREdq_live||!COREmath_valid||COREmem_en!=0||COREmem_we!=0||COREmath_accept||COREmath_take)
     $fatal(1,"LOCAL_DENSE_STALL_STATE");
    if(stall_test==1&&(CORErequest_mask[3]||COREresponse_mask[3]))$fatal(1,"LOCAL_DENSE_TAIL_MASK");
    for(stall_lane=0;stall_lane<(stall_test==0?4:3);stall_lane=stall_lane+1)
     if(CORElane_result[stall_lane]!==stall_result[stall_lane]||CORElane_tag[stall_lane]!==stall_tag[stall_lane])
      $fatal(1,"LOCAL_DENSE_HELD_RESULT_CHANGED");
   end
   force dut.u_kwt1_mmio.accel.core_enable=1'b1;
   @(negedge hfextclk);release dut.u_kwt1_mmio.accel.core_enable;
   if(dut.u_kwt1_mmio.accel.core_enable!==1'b1)$fatal(1,"LOCAL_ENABLE_NOT_RESTORED");
  end
  $display("PASS LOCAL_DENSE_STALL mac_cycles=17 held_requant_cycles=11");$fflush();
 end
 initial if($test$plusargs("STALL_DENSE"))begin
  #50000000;$fatal(1,"LOCAL_DENSE_STALL_WATCHDOG");
 end
 always @(negedge hfextclk)if(!erst_n)begin
  if(COREdq_active||COREmem_en!=0||COREmem_we!=0||COREmath_accept||COREmath_take)
   $fatal(1,"LOCAL_DENSE_RESET_NOT_QUIESCENT");
 end
'''.replace('CORE',core)
    if error_checks:
        body+=''' reg dense_error_checked=0;reg[8:0]dense_error_received;
 initial begin
  wait(erst_n===1);
  if(mode&&reset_point==14)begin
   wait(CORElayer==1&&COREstate==7&&COREdq_live&&COREmath_valid);
   @(negedge hfextclk);dense_error_received=COREreceived;
   force CORElane_error=4'b0001;
   repeat(8)begin
    @(negedge hfextclk);
    if(!COREfault||COREstate!=68||COREdq_active||COREmem_we!=0||COREmath_accept||COREmath_take||COREreceived!=dense_error_received)
     $fatal(1,"LOCAL_DENSE_ERROR_NOT_QUIESCENT");
   end
   force CORElane_error=4'b0000;release CORElane_error;
   $display("PASS LOCAL_DENSE_ERROR_QUIESCENT cycles=8");$fflush();dense_error_checked=1;
  end
 end
'''.replace('CORE',core)
    return s[:begin]+body+s[end:]
