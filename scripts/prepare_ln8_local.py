"""Prepare the unchanged compliant SYSBUS snapshot with only the LN8 overlay."""
import argparse
import hashlib
import json
from pathlib import Path
from prepare_pv16_local import prepare,ROOT

def once(s,old,new):
    assert s.count(old)==1,(s.count(old),old);return s.replace(old,new)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);ap.add_argument('--ln-checks',action='store_true');a=ap.parse_args();out=a.output.resolve()
    manifest=prepare(out,'pv16');name='rtl/v2/kwt_layer_banked.sv'
    manifest['PV16_parent_layer_sha256']=manifest['files'][name]
    data=(ROOT/'rtl/ln8_opt/kwt_layer_banked.sv').read_bytes();(out/name).write_bytes(data)
    manifest['files'][name]=hashlib.sha256(data).hexdigest();manifest['variant']='ln8'
    manifest['worktree_parent']='d011cbafdb38f15aa3395fbb2276e09692546356'
    if a.ln_checks:
        bench=out/'flow/tb_soc_metrics.sv';s=bench.read_text();core='dut.u_kwt1_mmio.accel.core.'
        cases='''       4:wait(COREstate==41&&COREch==63&&COREtoken==0);
       5:wait(COREstate==44&&COREnorm_row==6&&COREmath_valid);
       6:wait(COREstate==51&&COREtoken==96&&COREnorm_row==2&&COREmath_valid);
       7:wait(COREstate==76&&COREnorm_row==1&&COREch==32);
'''.replace('CORE',core)
        s=once(s,'       default:$fatal(1,"LOCAL_RESET_POINT");',cases+'       default:$fatal(1,"LOCAL_RESET_POINT");')
        s=once(s,'wait('+core+'state==29&&'+core+'red==20);','wait('+core+'state==41&&'+core+'ch==31);')
        s=once(s,'stall_red='+core+'red;','stall_red={2\'b0,'+core+'ch};')
        s=once(s,core+'state!=29||'+core+'red!=stall_red',core+'state!=41||'+core+'ch!=stall_red')
        s=once(s,'   wait('+core+'state==31&&'+core+'math_valid);','   wait('+core+'state==51&&'+core+'token==96&&'+core+'norm_row==2&&'+core+'math_valid);')
        s=once(s,core+'state!=31||!'+core+'math_valid',core+'state!=51||!'+core+'math_valid')
        s=s.replace('STALL_PV','STALL_LN').replace('LOCAL_PV_','LOCAL_LN_')
        s=once(s,'endmodule',''' always @(posedge hfextclk)if(erst_n&&dut.u_kwt1_mmio.accel.core.done)begin
  $display("LOCAL_LAYER_DONE layer=%0d norm2=%0d",dut.u_kwt1_mmio.accel.core.layer,dut.u_kwt1_mmio.accel.core.norm2);$fflush();
 end
endmodule''')
        bench.write_text(s);manifest['files']['flow/tb_soc_metrics.sv']=hashlib.sha256(bench.read_bytes()).hexdigest()
        manifest['verification_only_changes'].append('LN group/tail reset and gather/result stalls, progress traces')
    (out/'source_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('PREPARED LN8',manifest['files'][name])
