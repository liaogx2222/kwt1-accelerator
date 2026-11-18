"""Verification-only four-row fork, packed write, reset and error scenarios."""
import re
def once(s,old,new):
    assert s.count(old)==1,(s.count(old),old);return s.replace(old,new)
def instrument(s):
    core='dut.u_kwt1_mmio.accel.core.'
    cases='''       25:wait(COREstate==50&&COREnorm_row==6&&COREtoken==0);
       26:wait(COREstate==95&&COREnorm_row==0&&COREnorm_pass==2&&COREreceived==63&&COREmath_valid);
       27:wait(COREstate==95&&COREnorm_row==1&&COREnorm_pass==2&&COREreceived==31&&COREmath_valid);
       28:wait(COREstate==51&&COREtoken==96&&COREnorm_row==2&&COREnorm_pass==1&&COREreceived==60&&COREmath_valid);
       30:wait(ln4_error_checked);
'''
    s=once(s,'       default:$fatal(1,"LOCAL_RESET_POINT");',re.sub(r'CORE(?=[a-z])',core,cases)+'       default:$fatal(1,"LOCAL_RESET_POINT");')
    begin=s.index(' integer stall_lane;');end=s.index(' integer nice_reads=',begin)
    body=''' reg[63:0]ln4_a[0:3],ln4_b[0:3],ln4_result[0:3];reg[7:0]ln4_tag[0:3];integer ln4_lane;
 reg[8:0]ln4_sent,ln4_received;reg[12671:0]ln4_prob;reg[4095:0]ln4_high;reg[511:0]ln4_stats;
 reg ln4_error_checked=0;
 task restore_ln4_enable;
  begin force dut.u_kwt1_mmio.accel.core_enable=1'b1;@(negedge hfextclk);release dut.u_kwt1_mmio.accel.core_enable;
   if(dut.u_kwt1_mmio.accel.core_enable!==1'b1)$fatal(1,"LOCAL_ENABLE_NOT_RESTORED");end
 endtask
 initial if($test$plusargs("STALL_LN4"))begin
  wait(erst_n===1);
  wait(COREstate==95&&COREnorm_row==0&&COREnorm_pass==1&&COREsent==31);
  @(negedge hfextclk);ln4_sent=COREsent;
  for(ln4_lane=0;ln4_lane<4;ln4_lane=ln4_lane+1)begin ln4_a[ln4_lane]=CORElane_a[ln4_lane];ln4_b[ln4_lane]=CORElane_b[ln4_lane];ln4_tag[ln4_lane]=CORErequest_tag[ln4_lane];end
  force CORElane_ready=4'b1110;
  repeat(11)begin
   @(negedge hfextclk);
   if(COREstate!=95||COREnorm_row!=0||COREnorm_pass!=1||COREsent!=ln4_sent||COREmath_accept||CORErequest_mask!=15)$fatal(1,"LOCAL_LN4_FORK_STALL");
   for(ln4_lane=0;ln4_lane<4;ln4_lane=ln4_lane+1)
    if(CORElane_a[ln4_lane]!==ln4_a[ln4_lane]||CORElane_b[ln4_lane]!==ln4_b[ln4_lane]||CORErequest_tag[ln4_lane]!==ln4_tag[ln4_lane])$fatal(1,"LOCAL_LN4_REQUEST_CHANGED");
  end
  force CORElane_ready=4'b1111;@(negedge hfextclk);release CORElane_ready;
  wait(COREstate==95&&COREnorm_row==1&&COREnorm_pass==2&&COREreceived==63&&COREmath_valid);
  @(negedge hfextclk);ln4_sent=COREsent;ln4_received=COREreceived;
  for(ln4_lane=0;ln4_lane<4;ln4_lane=ln4_lane+1)begin ln4_result[ln4_lane]=CORElane_result[ln4_lane];ln4_tag[ln4_lane]=CORElane_tag[ln4_lane];end
  for(ln4_lane=0;ln4_lane<792;ln4_lane=ln4_lane+1)ln4_prob[ln4_lane*16+:16]=COREprobabilities[ln4_lane];
  for(ln4_lane=0;ln4_lane<128;ln4_lane=ln4_lane+1)ln4_high[ln4_lane*32+:32]=CORElow_pv[ln4_lane];
  for(ln4_lane=0;ln4_lane<16;ln4_lane=ln4_lane+1)ln4_stats[ln4_lane*32+:32]=CORErow_data[ln4_lane];
  force dut.u_kwt1_mmio.accel.core_enable=1'b0;
  repeat(17)begin
   @(negedge hfextclk);
   if(COREstate!=95||COREnorm_row!=1||COREnorm_pass!=2||COREsent!=ln4_sent||COREreceived!=ln4_received||!COREmath_valid||COREmath_take||COREmath_accept||COREmem_en!=0||COREmem_we!=0)$fatal(1,"LOCAL_LN4_RESPONSE_STALL");
   for(ln4_lane=0;ln4_lane<4;ln4_lane=ln4_lane+1)
    if(CORElane_result[ln4_lane]!==ln4_result[ln4_lane]||CORElane_tag[ln4_lane]!==ln4_tag[ln4_lane])$fatal(1,"LOCAL_LN4_RESULT_CHANGED");
   for(ln4_lane=0;ln4_lane<792;ln4_lane=ln4_lane+1)if(COREprobabilities[ln4_lane]!==ln4_prob[ln4_lane*16+:16])$fatal(1,"LOCAL_LN4_PROB_CHANGED");
   for(ln4_lane=0;ln4_lane<128;ln4_lane=ln4_lane+1)if(CORElow_pv[ln4_lane]!==ln4_high[ln4_lane*32+:32])$fatal(1,"LOCAL_LN4_HIGH_CHANGED");
   for(ln4_lane=0;ln4_lane<16;ln4_lane=ln4_lane+1)if(CORErow_data[ln4_lane]!==ln4_stats[ln4_lane*32+:32])$fatal(1,"LOCAL_LN4_STATS_CHANGED");
  end
  restore_ln4_enable();
  $display("PASS LOCAL_LN4_STALL fork_cycles=11 held_packed_write_cycles=17");$fflush();
 end
 initial begin
  wait(erst_n===1);
  if(mode&&reset_point==30)begin
   wait(COREstate==95&&COREnorm_row==1&&COREnorm_pass==2&&COREreceived==31&&COREmath_valid);
   @(negedge hfextclk);ln4_received=COREreceived;force CORElane_error=4'b0100;
   repeat(8)begin
    @(negedge hfextclk);
    if(!COREfault||COREstate!=68||COREmath_accept||COREmath_take||COREmem_en!=0||COREmem_we!=0||COREreceived!=ln4_received)$fatal(1,"LOCAL_LN4_ERROR_NOT_QUIESCENT");
   end
   force CORElane_error=4'b0000;release CORElane_error;
   $display("PASS LOCAL_LN4_ERROR_QUIESCENT cycles=8");$fflush();ln4_error_checked=1;
  end
 end
 task check_ln4_reset;
  begin if(CORErst_n||COREiter_valid||(|CORElane_valid)||COREdq_active||COREmem_en!=0||COREmem_we!=0||COREmath_accept||COREmath_take)$fatal(1,"LOCAL_LN4_RESET_NOT_QUIESCENT");end
 endtask
 always @(negedge erst_n)begin #0.001;check_ln4_reset();end
 always @(negedge hfextclk)if(!erst_n)begin #0.001;check_ln4_reset();end
 initial if($test$plusargs("STALL_LN4"))begin #50000000;$fatal(1,"LOCAL_LN4_STALL_WATCHDOG");end
'''
    return s[:begin]+re.sub(r'CORE(?=[a-z])',core,body)+s[end:]
