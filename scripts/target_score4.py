"""Verification-only score-store and synchronous-consumer stalls/resets."""
import re
def once(s,old,new):
    assert s.count(old)==1,(s.count(old),old);return s.replace(old,new)
def instrument(s):
    core='dut.u_kwt1_mmio.accel.core.'
    cases='''       15:wait(CORElayer==1&&COREstate==18&&COREkg==0&&COREstore_index==16);
       16:wait(COREstate==18&&COREtoken==96&&COREkg==6&&COREstore_index==2);
       17:wait(COREstate==70&&COREnorm_row==7&&COREch==98);
'''.replace('CORE',core)
    s=once(s,'       default:$fatal(1,"LOCAL_RESET_POINT");',cases+'       default:$fatal(1,"LOCAL_RESET_POINT");')
    begin=s.index(' integer stall_lane;');end=s.index(' integer nice_reads=',begin)
    body=''' reg[7:0]score_stall_state,score_stall_index;reg[6:0]score_stall_ch;
 reg[4095:0]score_stall_acc;reg[31:0]score_stall_data;integer score_stall_test;
 initial if($test$plusargs("STALL_SCORE"))begin
  wait(erst_n===1);
  for(score_stall_test=0;score_stall_test<2;score_stall_test=score_stall_test+1)begin
   if(score_stall_test==0)wait(CORElayer==1&&COREstate==18&&COREstore_index==16);
   else wait(COREstate==70&&COREtoken==96&&COREnorm_row==2&&COREch==98);
   @(negedge hfextclk);
   score_stall_state=COREstate;score_stall_index=COREstore_index;score_stall_ch=COREch;
   score_stall_acc=COREacc;score_stall_data=COREscore_rdata;
   force dut.u_kwt1_mmio.accel.core_enable=1'b0;
   repeat(score_stall_test==0?17:11)begin
    @(negedge hfextclk);
    if(COREstate!=score_stall_state||COREstore_index!=score_stall_index||COREch!=score_stall_ch||COREacc!==score_stall_acc||
       COREmem_en!=0||COREmem_we!=0||COREmath_accept||COREmath_take||
       (score_stall_test==1&&COREscore_rdata!==score_stall_data))$fatal(1,"LOCAL_SCORE_STALL_CHANGED");
   end
   force dut.u_kwt1_mmio.accel.core_enable=1'b1;
   @(negedge hfextclk);release dut.u_kwt1_mmio.accel.core_enable;
   if(dut.u_kwt1_mmio.accel.core_enable!==1'b1)$fatal(1,"LOCAL_ENABLE_NOT_RESTORED");
  end
  $display("PASS LOCAL_SCORE_STALL mac_cycles=17 held_requant_cycles=11");$fflush();
 end
 initial if($test$plusargs("STALL_SCORE"))begin #50000000;$fatal(1,"LOCAL_SCORE_STALL_WATCHDOG");end
 always @(negedge hfextclk)if(!erst_n)begin
  if(COREdq_active||COREmem_en!=0||COREmem_we!=0||COREmath_accept||COREmath_take)
   $fatal(1,"LOCAL_SCORE_RESET_NOT_QUIESCENT");
 end
'''
    return s[:begin]+re.sub(r'CORE(?=[a-z])',core,body)+s[end:]
