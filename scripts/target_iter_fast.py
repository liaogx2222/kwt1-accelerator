"""Verification-only actual iterative response stalls and mid-operation resets."""
import re
def once(s,old,new):
    assert s.count(old)==1,(s.count(old),old);return s.replace(old,new)
def instrument(s):
    core='dut.u_kwt1_mmio.accel.core.'
    cases='''       21:wait(COREstate==93&&COREiter_sqrt&&COREiterative_unit.state==2&&COREiterative_unit.count==7);
       22:wait(COREstate==93&&COREiter_a==64'h800000000000&&COREiterative_unit.quad_step&&COREiterative_unit.count==3);
       23:wait(iter_held_reset_ready);
       24:wait(COREstate==93&&COREiter_a==64'h10000000000&&COREiterative_unit.quad_step&&COREiterative_unit.count==1);
'''
    s=once(s,'       default:$fatal(1,"LOCAL_RESET_POINT");',re.sub(r'CORE(?=[a-z])',core,cases)+'       default:$fatal(1,"LOCAL_RESET_POINT");')
    begin=s.index(' integer stall_lane;');end=s.index(' integer nice_reads=',begin)
    body=''' integer iter_stall_test;reg[63:0]iter_hold_q,iter_hold_r;
 reg[7:0]iter_hold_state;reg iter_hold_error;reg iter_held_reset_ready=0;
 task capture_iter;
  begin iter_hold_q=COREiter_result;iter_hold_r=COREiter_remainder;iter_hold_error=COREiter_error;iter_hold_state=COREstate;end
 endtask
 task check_iter;
  begin
   if(COREstate!=iter_hold_state||!COREiter_valid||COREiter_ready||COREiter_result!==iter_hold_q||
      COREiter_remainder!==iter_hold_r||COREiter_error!==iter_hold_error||COREmem_en!=0||COREmem_we!=0||COREmath_accept||COREmath_take)
    $fatal(1,"LOCAL_ITER_HELD_CHANGED");
  end
 endtask
 task restore_core_enable;
  begin force dut.u_kwt1_mmio.accel.core_enable=1'b1;@(negedge hfextclk);release dut.u_kwt1_mmio.accel.core_enable;
   if(dut.u_kwt1_mmio.accel.core_enable!==1'b1)$fatal(1,"LOCAL_ENABLE_NOT_RESTORED");end
 endtask
 initial if($test$plusargs("STALL_ITER"))begin
  wait(erst_n===1);
  for(iter_stall_test=0;iter_stall_test<2;iter_stall_test=iter_stall_test+1)begin
   if(iter_stall_test==0)wait(COREstate==93&&COREiter_sqrt&&COREiter_valid);
   else wait(COREstate==93&&COREiter_a==64'h10000000000&&!COREiter_sqrt&&COREiter_valid);
   @(negedge hfextclk);capture_iter();force dut.u_kwt1_mmio.accel.core_enable=1'b0;
   repeat(iter_stall_test==0?17:11)begin @(negedge hfextclk);check_iter();end
   restore_core_enable();
  end
  $display("PASS LOCAL_ITER_STALL sqrt_result_cycles=17 div_result_cycles=11");$fflush();
 end
 initial begin
  wait(erst_n===1);
  if(mode&&reset_point==23)begin
   wait(COREstate==93&&COREiter_sqrt&&COREiter_valid);
   @(negedge hfextclk);capture_iter();force dut.u_kwt1_mmio.accel.core_enable=1'b0;
   repeat(3)begin @(negedge hfextclk);check_iter();end
   $display("PASS LOCAL_ITER_HELD_RESET_SETUP");$fflush();iter_held_reset_ready=1;
   wait(!erst_n);@(negedge hfextclk);restore_core_enable();
  end
 end
 initial if($test$plusargs("STALL_ITER"))begin #50000000;$fatal(1,"LOCAL_ITER_STALL_WATCHDOG");end
 reg iter_reset_seen_high=0;
 always @(negedge hfextclk)begin
  if(!erst_n&&iter_reset_seen_high)$display("LOCAL_ITER_RESET_PRE core_rst=%b valid=%b",CORErst_n,COREiter_valid);
  // The external pin, reset synchronizer and unit flops update in successive
  // NBA deltas. Sample1ps after the same edge, before any next active clock.
  #0.001;
  if(!erst_n)begin
   if(iter_reset_seen_high)$display("LOCAL_ITER_RESET_POST core_rst=%b valid=%b",CORErst_n,COREiter_valid);
   if(CORErst_n||COREiter_valid||COREiter_ready||COREdq_active||COREmem_en!=0||COREmem_we!=0||COREmath_accept||COREmath_take)
    $fatal(1,"LOCAL_ITER_RESET_NOT_QUIESCENT");
  end
  iter_reset_seen_high=erst_n;
 end
'''
    return s[:begin]+re.sub(r'CORE(?=[a-z])',core,body)+s[end:]
