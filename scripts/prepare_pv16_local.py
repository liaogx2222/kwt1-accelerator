"""Prepare independent unchanged-SYSBUS projects for baseline/PV16 validation."""
import argparse
import hashlib
import json
from pathlib import Path
from prepare_sysbus_opt_local import ROOT,snapshot

def once(s,old,new):
    assert s.count(old)==1,(old[:80],s.count(old));return s.replace(old,new)

def prepare(out,variant):
    m=snapshot(out)
    if variant=='pv16':
        data=(ROOT/'rtl/pv16_opt/kwt_layer_banked.sv').read_bytes()
        target='rtl/v2/kwt_layer_banked.sv';m['parent_layer_sha256']=m['files'][target]
        (out/target).write_bytes(data);m['files'][target]=hashlib.sha256(data).hexdigest()
    tb=out/'flow/tb_soc_metrics.sv';s=tb.read_text()
    s=once(s,' reg started=0;', ' reg soft_clear=0,legacy_started=0;reg [63:0]legacy_first_tick=0;\n integer task_epoch=0,task_count=1,task_index=0,result_file=0;\n reg started=0;')
    s=once(s,'  if(!erst_n)begin','  if(!erst_n||soft_clear)begin')
    s=once(s,'   id_seen<=0;done<=0;', '   id_seen<=!erst_n?0:id_seen;done<=0;')
    s=once(s,'started<=0;\n', 'started<=0;legacy_started<=0;legacy_first_tick<=0;\n')
    s=once(s,'   if(host_en&&host_ready)begin host_words<=host_words+1;if(!started)begin started<=1;first_tick<=ticks;end end',
        '   if(host_en&&!started)begin started<=1;first_tick<=ticks;end\n   if(host_en&&host_ready)begin host_words<=host_words+1;if(!legacy_started)begin legacy_started<=1;legacy_first_tick<=ticks;end end')
    s=once(s,'     outputs<=outputs+1;','     if(result_file!=0)$fdisplay(result_file,"%08x",xw);\n     outputs<=outputs+1;')
    s=once(s,"push('h9000,15432);host_write(0,1);","push('h9000,15432);host_write(0,task_epoch+1);")
    s=once(s,'wait(ack==layer);','wait(ack==task_epoch+layer);')
    s=once(s,"push('h9000,15432);host_write(0,layer+1);","push('h9000,15432);host_write(0,task_epoch+layer+1);")
    s=once(s,'  if(!$value$plusargs("CASE=%d",case_id))case_id=0;',
        '  if(!$value$plusargs("CASE=%d",case_id))case_id=0;\n  if(!$value$plusargs("TASKS=%d",task_count))task_count=1;\n  if(task_count<1||task_count>2)$fatal(1,"LOCAL_TASK_COUNT");')
    s=once(s,'  supply();repeat(2)@(negedge hfextclk);', '''  for(task_index=0;task_index<task_count;task_index=task_index+1)begin
   if(task_index!=0)begin
    task_epoch=task_epoch+16;soft_clear=1;
    @(negedge hfextclk);soft_clear=0;
   end
   result_file=$fopen($sformatf("%s/matrix_task_%02d.hex",outdir,task_index),"w");
   if(result_file==0)$fatal(1,"LOCAL_OUTPUT_FILE");
   supply();repeat(2)@(negedge hfextclk);''')
    s=once(s,'  $finish;', '''   $display("LOCAL_TASK_PROFILE task=%0d legacy_cycles=%0d issue_cycles=%0d compute_cycles=%0d read_words=%0d write_words=%0d",task_index,last_tick-legacy_first_tick+1,last_tick-first_tick+1,dut.u_kwt1_mmio.accel.compute_cycles,dut.u_kwt1_mmio.accel.read_words,dut.u_kwt1_mmio.accel.write_words);
   $fclose(result_file);result_file=0;
  end
  $finish;''')
    s=s.replace('endmodule',''' reg [63:0] phase_cycles[0:255];reg phase_printed=0;integer phase_i;
 always @(posedge hfextclk)begin
  if(!erst_n||soft_clear)begin
   phase_printed=0;for(phase_i=0;phase_i<256;phase_i=phase_i+1)phase_cycles[phase_i]=0;
  end else begin
   if(dut.u_kwt1_mmio.accel.state==2&&dut.u_kwt1_mmio.accel.core.enable)
    phase_cycles[dut.u_kwt1_mmio.accel.core.debug_state]=phase_cycles[dut.u_kwt1_mmio.accel.core.debug_state]+1;
   if(done&&!phase_printed)begin
    phase_printed=1;
    for(phase_i=0;phase_i<256;phase_i=phase_i+1)if(phase_cycles[phase_i])
     $display("LOCAL_PHASE state=%0d cycles=%0d",phase_i,phase_cycles[phase_i]);
   end
  end
 end
endmodule''')
    # These are optional testbench controls only. Production bindings and
    # frozen CPU firmware remain byte-identical between the two variants.
    s=once(s,' reg soft_clear=',' reg crc_pending=0,crc_error_seen=0;integer reset_point=0;\n reg soft_clear=')
    s=once(s,'started<=0;legacy_started<=0;','started<=0;crc_error_seen<=0;legacy_started<=0;')
    s=once(s,'if(ma==32\'ha0000008&&mw==32\'hbad00000)$fatal(1,"SOC_FIRMWARE_ERROR");',
        'if(ma==32\'ha0000008&&mw==32\'hbad00000)begin if(crc_pending)crc_error_seen<=1;else $fatal(1,"SOC_FIRMWARE_ERROR");end')
    s=once(s,'  if(mode)begin','  if(mode||crc_pending)begin')
    s=once(s,'  if(task_count<1||task_count>2)$fatal(1,"LOCAL_TASK_COUNT");',
        '  if(task_count<1||task_count>2)$fatal(1,"LOCAL_TASK_COUNT");\n  crc_pending=$test$plusargs("CRC_FAULT");\n  if(!$value$plusargs("RESET_POINT=%d",reset_point))reset_point=0;')
    s=once(s,"$readmemh(fn,image,0,15431);push('h9000,15432);",
        "$readmemh(fn,image,0,15431);if(crc_pending&&layer==3)image[15431]=image[15431]^1;push('h9000,15432);")
    old='''     wait(compute_seen===1);repeat(20000)@(negedge hfextclk);
     $display("SOC_GATE_RESET_IN_FLIGHT outputs=%0d packets=%0d",outputs,packets);'''
    new='''     if(crc_pending)begin
      wait(crc_error_seen===1);
      if(outputs!=0||params!=65872||packets!=5)$fatal(1,"LOCAL_CRC_REJECTION_TOTALS");
      $display("PASS LOCAL_PREFETCH_CRC_REJECT params=%0d packets=%0d outputs=%0d",params,packets,outputs);
     end else begin
      case(reset_point)
       0:begin wait(compute_seen===1);repeat(20000)@(negedge hfextclk);end
       1:wait(dut.u_kwt1_mmio.accel.core.state==29&&dut.u_kwt1_mmio.accel.core.red==50&&dut.u_kwt1_mmio.accel.core.token==0);
       2:wait(dut.u_kwt1_mmio.accel.core.state==29&&dut.u_kwt1_mmio.accel.core.red==98&&dut.u_kwt1_mmio.accel.core.token==96);
       3:wait(dut.u_kwt1_mmio.accel.core.state==31&&dut.u_kwt1_mmio.accel.core.math_valid);
       default:$fatal(1,"LOCAL_RESET_POINT");
      endcase
      $display("SOC_GATE_RESET_IN_FLIGHT point=%0d outputs=%0d packets=%0d",reset_point,outputs,packets);
     end'''
    s=once(s,old,new)
    s=once(s,'   erst_n=0;host_en=0;host_addr=0;host_wdata=0;',
        '   crc_pending=0;erst_n=0;host_en=0;host_addr=0;host_wdata=0;')
    s=once(s,'endmodule',''' integer stall_lane;reg [8:0]stall_red;reg [63:0]stall_result[0:3];reg[7:0]stall_tag[0:3];
 initial begin
  if($test$plusargs("STALL_PV"))begin
   wait(erst_n===1);
   wait(dut.u_kwt1_mmio.accel.core.state==29&&dut.u_kwt1_mmio.accel.core.red==20);
   @(negedge hfextclk);stall_red=dut.u_kwt1_mmio.accel.core.red;
   force dut.u_kwt1_mmio.accel.core_enable=1'b0;
   repeat(17)begin
    @(negedge hfextclk);
    if(dut.u_kwt1_mmio.accel.core.state!=29||dut.u_kwt1_mmio.accel.core.red!=stall_red)$fatal(1,"LOCAL_PV_MAC_STALL_STATE");
   end
   // Restore the known top-level tie-high before release: Verilator's
   // variable-input force lowering otherwise retains the forced zero.
   $display("LOCAL_PV_MAC_STALL_COMPLETE red=%0d",stall_red);$fflush();
   force dut.u_kwt1_mmio.accel.core_enable=1'b1;
   @(negedge hfextclk);
   release dut.u_kwt1_mmio.accel.core_enable;
   if(dut.u_kwt1_mmio.accel.core_enable!==1'b1)$fatal(1,"LOCAL_ENABLE_NOT_RESTORED");
   wait(dut.u_kwt1_mmio.accel.core.state==31&&dut.u_kwt1_mmio.accel.core.math_valid);
   @(negedge hfextclk);
   for(stall_lane=0;stall_lane<4;stall_lane=stall_lane+1)begin
    stall_result[stall_lane]=dut.u_kwt1_mmio.accel.core.lane_result[stall_lane];
    stall_tag[stall_lane]=dut.u_kwt1_mmio.accel.core.lane_tag[stall_lane];
   end
   force dut.u_kwt1_mmio.accel.core_enable=1'b0;
   repeat(11)begin
    @(negedge hfextclk);
    if(dut.u_kwt1_mmio.accel.core.state!=31||!dut.u_kwt1_mmio.accel.core.math_valid)$fatal(1,"LOCAL_PV_RQ_STALL_STATE");
    for(stall_lane=0;stall_lane<4;stall_lane=stall_lane+1)
     if(dut.u_kwt1_mmio.accel.core.lane_result[stall_lane]!==stall_result[stall_lane]||
        dut.u_kwt1_mmio.accel.core.lane_tag[stall_lane]!==stall_tag[stall_lane])$fatal(1,"LOCAL_PV_HELD_RESULT_CHANGED");
   end
   force dut.u_kwt1_mmio.accel.core_enable=1'b1;
   @(negedge hfextclk);
   release dut.u_kwt1_mmio.accel.core_enable;
   if(dut.u_kwt1_mmio.accel.core_enable!==1'b1)$fatal(1,"LOCAL_ENABLE_NOT_RESTORED");
   $display("PASS LOCAL_PV_STALL mac_cycles=17 held_requant_cycles=11");$fflush();
  end
 end
 initial if($test$plusargs("STALL_PV"))begin
  #50000000;
  $fatal(1,"LOCAL_STALL_WATCHDOG state=%0d red=%0d enable=%b",dut.u_kwt1_mmio.accel.core.state,dut.u_kwt1_mmio.accel.core.red,dut.u_kwt1_mmio.accel.core.enable);
 end
endmodule''')
    tb.write_text(s)
    m['files']['flow/tb_soc_metrics.sv']=hashlib.sha256(tb.read_bytes()).hexdigest()
    m.update(variant=variant,verification_only_changes=['first-request-inclusive timing','same-object two cold tasks','output files','phase counters','PV reset/stall and CRC fault controls'],
        arithmetic_changed_files=['rtl/v2/kwt_layer_banked.sv'] if variant=='pv16' else [],
        numerical_parameters_changed=False,CPU_firmware_changed=False,System_Bus_or_interfaces_changed=False)
    (out/'source_manifest.json').write_text(json.dumps(m,indent=2)+'\n');return m

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--variant',choices=['baseline','pv16'],required=True);a=ap.parse_args()
    r=prepare(a.output.resolve(),a.variant);print('PREPARED',r['variant'],len(r['files']),'source-bound files')
