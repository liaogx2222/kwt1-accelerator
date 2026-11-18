"""Reproduce/collect the default-gap campaign, including interrupted split runs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
REV='d6d6bd23efd047c4f89b73b4b78398026ab29fe5'
PARENT='97efbfc666a1ba7569ff999408b740a8e731a8d1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def run(name,*args):subprocess.run([sys.executable,str(ROOT/'scripts'/name),*map(str,args)],cwd=ROOT,check=True)

def reproduce(out):
    assert not out.exists(),'preserve existing logs'
    for label,extra in [('baseline',['--baseline']),('candidate',[])]:
        p=out/label/'project';run('prepare_nice_prefetch2.py','--output',p,*extra)
        run('check_pv16_soc.py','--project',p,'--output',out/label/'cold0_gap4','--cases','0','--jobs','1','--host-gap','4')
    p=out/'candidate/project';exe=out/'candidate/cold0_gap4/model/sim.exe'
    jobs=[('full12_gap4',['--cases','0,1,2,3','--jobs','4']),
          ('full12_remaining_gap4',['--cases','4,5,6,7,8,9,10,11','--jobs','4']),
          ('consecutive_v2_gap4',['--cases','0','--tasks','2']),('crc_recovery_gap4',['--cases','0','--crc']),
          ('inflight_reads_v2',['--cases','0','--recovery','--reset-point','8']),
          ('held_read_recovery',['--cases','0','--recovery','--reset-point','9']),
          ('output_recovery',['--cases','0','--recovery','--reset-point','10'])]
    for name,args in jobs:run('check_pv16_soc.py','--project',p,'--model',exe,'--output',out/name,'--host-gap','4',*args)
    run('check_nice_prefetch2.py','--output',out/'contract_v5')
    run('inventory_nice_prefetch2.py','--output',out/'inventory')

def collect(out):
    dest=out/'release_summary.json';assert not dest.exists(),'preserve existing summary'
    cp=out/'candidate/project';bp=out/'baseline/project'
    cm,bm=[read(p/'source_manifest.json') for p in [cp,bp]]
    for p,m in [(cp,cm),(bp,bm)]:assert len(m['files'])==194 and all(sha(p/n)==h for n,h in m['files'].items())
    diff=[n for n in cm['files'] if cm['files'][n]!=bm['files'][n]]
    assert sorted(diff)==['soc/kwt_nice_block.sv','soc/kwt_sysbus_arbiter3.sv']
    for n in diff:
        blob=subprocess.check_output(['git','show',REV+':rtl/nice_prefetch2/'+Path(n).name],cwd=ROOT)
        assert hashlib.sha256(blob).hexdigest()==cm['files'][n]==sha(ROOT/'rtl/nice_prefetch2'/Path(n).name)
    evidence={}
    def case(folder,case_id,tasks=1,point=0,crc=False,baseline=False):
        d=out/folder/('case_%02d'%case_id);r=read(d/'result.json');cmd=read(d/'command.json');exe=Path(cmd[0]);stamp=read(exe.parent/'sources.json')
        p=Path(next(x.split('=',1)[1] for x in cmd if x.startswith('+FIXTURES='))).parent;m=read(p/'source_manifest.json')
        assert m['files']==stamp['files'] and sha(p/'source_manifest.json')==stamp['source_manifest_sha256']
        assert all(sha(p/n)==h for n,h in m['files'].items())
        expected=bm['files'] if baseline else cm['files']
        assert all(stamp['files'][n]==h for n,h in expected.items() if n!='flow/tb_soc_metrics.sv')
        assert '+HOST_GAP=4' in cmd and r['host_gap_cycles']==4
        assert r['passed'] and r['case']==case_id and r['tasks']==tasks and r['reset_point']==point
        assert r['recovery']==bool(point) and r['CRC_rejection_full_recovery']==crc
        assert sha(d/'run.log')==r['log_sha256'];log=(d/'run.log').read_text()
        assert log.count('PASS SOC_INPUT16_GATE')==tasks
        assert log.count('params=189328 input_words=3168 output_words=1584 host_words=192508')==tasks
        if point:assert 'SOC_GATE_RESET_IN_FLIGHT point=%d'%point in log
        if crc:assert 'PASS LOCAL_PREFETCH_CRC_REJECT' in log
        for i in range(tasks):assert (d/('matrix_task_%02d.hex'%i)).read_text().split()==(p/('fixtures/expected_%03d.hex'%case_id)).read_text().split()
        assert len(r['profiles'])==tasks and len(r['transfer_profiles'])==tasks
        for profile,transfer in zip(r['profiles'],r['transfer_profiles']):
            assert profile[3]==2027232 and profile[5]==1239000
            assert transfer[1:4]==[4,192496,1584] and transfer[4]==(1 if baseline else 2) and transfer[7]==0
        evidence[str(d.relative_to(out)).replace('\\','/')]=dict(result=r,model_sha256=sha(exe),source_receipt_sha256=sha(exe.parent/'sources.json'),command_sha256=sha(d/'command.json'))
        return r
    b=case('baseline/cold0_gap4',0,baseline=True);c=case('candidate/cold0_gap4',0)
    assert b['profiles'][0][2]==2695118 and c['profiles'][0][2]==2330328
    for i in range(12):
        r=case('full12_gap4' if i<4 else 'full12_remaining_gap4',i)
        assert r['profiles'][0][2]==2330328
    warm=case('consecutive_v2_gap4',0,tasks=2);case('crc_recovery_gap4',0,crc=True)
    for name,point in [('inflight_reads_v2',8),('held_read_recovery',9),('output_recovery',10)]:case(name,0,point=point)
    unit=read(out/'contract_v5/summary.json');assert unit['passed'] and unit['four_state'] and unit['TIMEOUT']==32
    for label in ['baseline','prefetch']:assert 'successes=20 faults=17' in unit['cases'][label]['result']
    assert unit['cases']['prefetch']['source_sha256']==cm['files']['soc/kwt_nice_block.sv']
    inv=read(out/'inventory/summary.json');assert inv['passed'] and inv['production_TIMEOUT']==131072 and inv['total_declared_state_delta_bits']==70
    assert inv['cases']['prefetch']['source_sha256']==cm['files']['soc/kwt_nice_block.sv']
    r=dict(passed=True,branch='codex/nice-prefetch2-20261114',parent_commit=PARENT,production_source_commit=REV,
        changed_production_files=diff,production_sources={n:cm['files'][n] for n in diff},evidence=evidence,
        full_network_cold_classes=12,full_network_codes=76032,host_gap_cycles=4,
        timing_window='first host request to CPU completion-marker response; includes final output physical ACK',
        case0=dict(baseline=b['profiles'][0],candidate=c['profiles'][0],task_cycles_saved=364790,
            latency_reduction_percent=100*364790/2695118,compute_cycles_change=0,private_read_write_change=[0,0],
            baseline_transfer=b['transfer_profiles'][0],candidate_transfer=c['transfer_profiles'][0]),
        conditional150MHz=dict(frequency_signed_off=False,baseline_tasks_s=150000000/2695118,candidate_tasks_s=150000000/2330328,goal120_achieved=False),
        declared_state=dict(NICE_before=168,NICE_after=229,upstream_arbiter_before=8,upstream_arbiter_after=17,delta_bits=70),
        PE_array='8x16 unchanged',math_lanes=4,private_macros=20,full_SoC_macro_count_expected=100,
        numeric_or_parameter_or_original_decoder_or_ports_changed=False,
        verification=dict(SoC_two_state_timed=True,unit_four_state=True,vendor_macro_or_gate=False,physical_signoff=False),
        accuracy=dict(inherited_samples=4445,FP_correct=4348,integer_correct=4345,drop_pp=300/4445,new_official600_or_4445_RTL=False),
        area_mm2=None,power_mW=None,energy_uJ=None,
        server_notes=['resynthesize CPU/NICE; old CPU DDC contains old NICE','retain matching LN8 core a08f682 and original SystemBus',
                      'check reset/drain/backpressure with vendor RET1N and mapped four-state','measure full-corner timing and same-configuration full SoC PPA'])
    dest.write_text(json.dumps(r,indent=2)+'\n');print('PASS NICE CAMPAIGN 76032 cold codes; source-bound warm/CRC/three recovery groups')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);ap.add_argument('--collect',action='store_true');a=ap.parse_args();out=a.output.resolve()
    if not a.collect:reproduce(out)
    collect(out)
