"""Verification-only SRAM/EXP freeze and max-cache alias lifetime tests."""
import re
def once(s,old,new):
    assert s.count(old)==1,(s.count(old),old);return s.replace(old,new)
def instrument(s):
    core='dut.u_kwt1_mmio.accel.core.'
    cases='''       18:wait(COREstate==69&&COREnorm_row==7);
       19:wait(COREstate==19&&COREtoken==96&&COREnorm_row==2&&COREsent==98&&COREexp_pending);
       20:wait(COREstate==24&&COREnorm_row==7&&COREreceived==84&&COREmath_valid);
'''
    s=once(s,'       default:$fatal(1,"LOCAL_RESET_POINT");',re.sub(r'CORE(?=[a-z])',core,cases)+'       default:$fatal(1,"LOCAL_RESET_POINT");')
    begin=s.index(' integer stall_lane;');end=s.index(' integer nice_reads=',begin)
    body=''' integer stream_test,stream_lane;reg[7:0]stream_state;
 reg[8:0]stream_sent,stream_received;reg[31:0]stream_score,stream_exp;
 reg stream_pending,stream_zero;reg[63:0]stream_result[0:3];reg[7:0]stream_tag[0:3];
 reg[12671:0]stream_probability;
 initial if($test$plusargs("STALL_STREAM"))begin
  wait(erst_n===1);
  for(stream_test=0;stream_test<2;stream_test=stream_test+1)begin
   if(stream_test==0)wait(COREstate==19&&COREsent==37&&COREmath_valid&&COREexp_pending);
   else wait(COREstate==24&&COREnorm_row==7&&COREreceived==84&&COREmath_valid);
   @(negedge hfextclk);
   stream_state=COREstate;stream_sent=COREsent;stream_received=COREreceived;
   stream_score=COREscore_rdata;stream_exp=COREmem_rdata[288+:32];stream_pending=COREexp_pending;stream_zero=COREexp_zero;
   for(stream_lane=0;stream_lane<4;stream_lane=stream_lane+1)begin
    stream_result[stream_lane]=CORElane_result[stream_lane];stream_tag[stream_lane]=CORElane_tag[stream_lane];
   end
   for(stream_lane=0;stream_lane<792;stream_lane=stream_lane+1)stream_probability[stream_lane*16+:16]=COREprobabilities[stream_lane];
   force dut.u_kwt1_mmio.accel.core_enable=1'b0;
   repeat(stream_test==0?17:11)begin
    @(negedge hfextclk);
    if(COREstate!=stream_state||COREsent!=stream_sent||COREreceived!=stream_received||COREmem_en!=0||COREmem_we!=0||
       COREmath_accept||COREmath_take||!COREmath_valid||COREscore_rdata!==stream_score||COREmem_rdata[288+:32]!==stream_exp||
       COREexp_pending!=stream_pending||COREexp_zero!=stream_zero)$fatal(1,"LOCAL_STREAM_STALL_CHANGED");
    for(stream_lane=0;stream_lane<(stream_test==0?1:4);stream_lane=stream_lane+1)
     if(CORElane_result[stream_lane]!==stream_result[stream_lane]||CORElane_tag[stream_lane]!==stream_tag[stream_lane])
      $fatal(1,"LOCAL_STREAM_HELD_RESULT_CHANGED");
    for(stream_lane=0;stream_lane<792;stream_lane=stream_lane+1)
     if(COREprobabilities[stream_lane]!==stream_probability[stream_lane*16+:16])$fatal(1,"LOCAL_STREAM_CACHE_CHANGED");
   end
   force dut.u_kwt1_mmio.accel.core_enable=1'b1;
   @(negedge hfextclk);release dut.u_kwt1_mmio.accel.core_enable;
   if(dut.u_kwt1_mmio.accel.core_enable!==1'b1)$fatal(1,"LOCAL_ENABLE_NOT_RESTORED");
  end
  $display("PASS LOCAL_STREAM_STALL score_exp_cycles=17 alias_result_cycles=11");$fflush();
 end
 initial if($test$plusargs("STALL_STREAM"))begin #50000000;$fatal(1,"LOCAL_STREAM_STALL_WATCHDOG");end
 always @(negedge hfextclk)if(!erst_n)begin
  if(COREdq_active||COREmem_en!=0||COREmem_we!=0||COREmath_accept||COREmath_take)
   $fatal(1,"LOCAL_STREAM_RESET_NOT_QUIESCENT");
 end
'''
    return s[:begin]+re.sub(r'CORE(?=[a-z])',core,body)+s[end:]
