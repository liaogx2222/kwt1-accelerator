"""Same original-interface LN8 SoC; replace only NICE and upstream owners."""
import argparse
import hashlib
import json
from pathlib import Path
from prepare_pv16_local import ROOT,prepare

def once(s,old,new):
    assert s.count(old)==1,(old,s.count(old));return s.replace(old,new)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);ap.add_argument('--baseline',action='store_true');a=ap.parse_args();out=a.output.resolve()
    m=prepare(out,'pv16');core='rtl/v2/kwt_layer_banked.sv'
    m['PV16_parent_layer_sha256']=m['files'][core]
    data=(ROOT/'rtl/ln8_opt/kwt_layer_banked.sv').read_bytes();(out/core).write_bytes(data);m['files'][core]=hashlib.sha256(data).hexdigest()
    changed=[];parents={}
    if not a.baseline:
        for source,target in [('kwt_nice_block.sv','soc/kwt_nice_block.sv'),('kwt_sysbus_arbiter3.sv','soc/kwt_sysbus_arbiter3.sv')]:
            parents[target]=m['files'][target];data=(ROOT/'rtl/nice_prefetch2'/source).read_bytes()
            (out/target).write_bytes(data);m['files'][target]=hashlib.sha256(data).hexdigest();changed.append(target)
    tb=out/'flow/tb_soc_metrics.sv';s=tb.read_text()
    s=once(s,' integer mode=0,recovered=0,k,case_id=0;', ' integer host_gap=4;\n integer mode=0,recovered=0,k,case_id=0;')
    s=once(s,'host_en=0;repeat(4)@(negedge hfextclk);','host_en=0;repeat(host_gap)@(negedge hfextclk);')
    s=once(s,'  if(!$value$plusargs("CASE=%d",case_id))case_id=0;',
        '  if(!$value$plusargs("CASE=%d",case_id))case_id=0;\n  if(!$value$plusargs("HOST_GAP=%d",host_gap))host_gap=4;\n  if(host_gap!=0&&host_gap!=4)$fatal(1,"LOCAL_HOST_GAP");')
    main='dut.u_e203_subsys_top.u_e203_subsys_main.'
    checks='''       8:wait(compute_seen&&dut.u_kwt1_mmio.accel.state==2&&params>19576&&nice_outstanding==2);
       9:wait(compute_seen&&dut.u_kwt1_mmio.accel.state==2&&params>19576&&nice_outstanding>0&&MAINblk_sink_valid&&!MAINblk_sink_ready);
       10:wait(outputs==1583&&nice_outstanding==1&&!MAINblk_mem_read);
'''.replace('MAIN',main)
    s=once(s,'       default:$fatal(1,"LOCAL_RESET_POINT");',checks+'       default:$fatal(1,"LOCAL_RESET_POINT");')
    s=once(s,'   $fclose(result_file);result_file=0;',
        '   $display("LOCAL_TRANSFER_PROFILE task=%0d host_gap=%0d nice_reads=%0d nice_writes=%0d nice_peak=%0d shared_reads=%0d shared_writes=%0d pending=%0d",task_index,host_gap,nice_reads,nice_writes,nice_peak,shared_reads,shared_writes,nice_outstanding);\n   $fclose(result_file);result_file=0;')
    s=once(s,'endmodule',''' integer nice_reads=0,nice_writes=0,nice_outstanding=0,nice_peak=0;
 integer shared_reads=0,shared_writes=0;
 always @(posedge hfextclk)begin
  if(!erst_n||soft_clear)begin nice_reads=0;nice_writes=0;nice_outstanding=0;nice_peak=0;shared_reads=0;shared_writes=0;end
  else begin
   if((started||host_en)&&!done)begin
    if(dut.u_e203_subsys_top.u_e203_subsys_main.blk_mem_valid&&dut.u_e203_subsys_top.u_e203_subsys_main.blk_mem_ready)begin
     if(dut.u_e203_subsys_top.u_e203_subsys_main.blk_mem_read)nice_reads=nice_reads+1;else nice_writes=nice_writes+1;
     nice_outstanding=nice_outstanding+1;
    end
    if(dut.u_e203_subsys_top.u_e203_subsys_main.blk_rsp_valid&&dut.u_e203_subsys_top.u_e203_subsys_main.blk_rsp_ready)nice_outstanding=nice_outstanding-1;
    if(nice_outstanding>nice_peak)nice_peak=nice_outstanding;
    if(nice_outstanding<0||nice_outstanding>2)$fatal(1,"LOCAL_NICE_OUTSTANDING");
    if(mv&&mr)begin if(mread)shared_reads=shared_reads+1;else shared_writes=shared_writes+1;end
   end
   if(dut.u_kwt1_mmio.accel.core.done)begin
    $display("LOCAL_LAYER_DONE layer=%0d",dut.u_kwt1_mmio.accel.core.layer);$fflush();
   end
  end
 end
endmodule''')
    tb.write_text(s);m['files']['flow/tb_soc_metrics.sv']=hashlib.sha256(tb.read_bytes()).hexdigest()
    m.update(variant='ln8' if a.baseline else 'nice_prefetch2',worktree_parent='97efbfc666a1ba7569ff999408b740a8e731a8d1',
        changed_production_files_relative_LN8=changed,LN8_parent_sources=parents,original_decoder_or_SRAM_interface_changed=False,
        supported_reset_points=[0,1,2,3,8,9,10],
        host_gap_default_preserved=4,host_gap0_is_separate_source_profile=True,CPU_firmware_changed=False,numerical_parameters_changed=False)
    (out/'source_manifest.json').write_text(json.dumps(m,indent=2)+'\n');print('PREPARED',m['variant'],changed)
