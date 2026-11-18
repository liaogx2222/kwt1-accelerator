"""Fresh full reproduction or strict source/model/output collection of score4."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PARENT='9476619b7c85d8b5806744478a3419d8e5965015'
REV='4a163f7abe5043e4cfb269f7a8d71d12291e7535'
CORE='rtl/v2/kwt_layer_banked.sv';BENCH='flow/tb_soc_metrics.sv'
GROUPS=[('full12',['--cases',','.join(map(str,range(12))),'--jobs','4']),('consecutive',['--tasks','2']),('crc_recovery',['--crc'])]
RESETS=[('store_reset',15),('tail_reset',16),('read_reset',17)]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def run(script,*args):subprocess.run([sys.executable,str(ROOT/'scripts'/script),*map(str,args)],cwd=ROOT,check=True)

def reproduce(out):
    assert not out.exists(),'preserve logs'
    for label,opts in [('baseline',['--baseline']),('candidate',[])]:
        p=out/label/'project';run('prepare_score4.py','--output',p,*opts)
        run('check_pv16_soc.py','--project',p,'--output',out/label/'cold0','--cases','0','--jobs','1','--host-gap','4')
    p=out/'candidate/project';exe=out/'candidate/cold0/model/sim.exe'
    for name,args in GROUPS:run('check_pv16_soc.py','--project',p,'--model',exe,'--output',out/name,'--host-gap','4',*args)
    p=out/'targeted_v2/project';run('prepare_score4.py','--output',p,'--targeted')
    run('check_pv16_soc.py','--project',p,'--output',out/'targeted_v2/stall','--host-gap','4','--stall','--stall-kind','score')
    exe=out/'targeted_v2/stall/model/sim.exe'
    for name,point in RESETS:run('check_pv16_soc.py','--project',p,'--model',exe,'--output',out/name,'--host-gap','4','--recovery','--reset-point',point)
    run('inventory_pv16.py','--project',out/'candidate/project','--output',out/'inventory')
    run('calculate_score4_ceiling.py','--output',out/'ceiling_v2','--log',out/'candidate/cold0/case_00/run.log')

def collect(out):
    dest=out/'release_summary.json';assert not dest.exists()
    cp,bp=[out/n/'project' for n in ['candidate','baseline']];cm,bm=[read(p/'source_manifest.json') for p in [cp,bp]]
    for p,m in [(cp,cm),(bp,bm)]:assert len(m['files'])==194 and all(sha(p/n)==h for n,h in m['files'].items())
    assert [n for n in cm['files'] if cm['files'][n]!=bm['files'][n]]==[CORE]
    parent=read(ROOT/'evidence/dense_overlap_20261115/candidate/cold0_gap4/summary.json')
    assert bm['files']==parent['source_bindings']['files']
    raw=subprocess.check_output(['git','show',REV+':rtl/score4_opt/kwt_layer_banked.sv'],cwd=ROOT)
    assert hashlib.sha256(raw).hexdigest()==sha(ROOT/'rtl/score4_opt/kwt_layer_banked.sv')==cm['files'][CORE]
    evidence={};compiler=None
    def soc(name,cases=(0,),tasks=1,point=0,crc=False,stall=False,baseline=False):
        nonlocal compiler
        folder=out/name;s=read(folder/'summary.json');assert s['passed'] and s['two_state'] and s['timed_SV']
        assert s['total_codes']==len(cases)*tasks*6336 and [r['case'] for r in s['cases']]==list(cases)
        if compiler is None:compiler=s['compiler_versions']
        else:assert compiler==s['compiler_versions']
        files=bm['files'] if baseline else cm['files'];bound=s['source_bindings']['files']
        assert files.keys()==bound.keys() and all(files[n]==bound[n] for n in files if n!=BENCH)
        for r in s['cases']:
            assert r['passed'] and r['tasks']==tasks and r['reset_point']==point and r['recovery']==bool(point)
            assert r['CRC_rejection_full_recovery']==crc and bool(r.get('Score_stalls',False))==stall
            d=folder/('case_%02d'%r['case']);cmd=read(d/'command.json');exe=Path(cmd[0]);assert sha(exe)==s['model_sha256']
            assert read(exe.parent/'sources.json')==s['source_bindings']
            p=Path(next(v.split('=',1)[1] for v in cmd if v.startswith('+FIXTURES='))).parent;m=read(p/'source_manifest.json')
            assert m['files']==bound and sha(p/'source_manifest.json')==s['source_bindings']['source_manifest_sha256']
            assert all(sha(p/n)==h for n,h in bound.items()) and '+HOST_GAP=4' in cmd
            assert sha(d/'run.log')==r['log_sha256'];log=(d/'run.log').read_text()
            assert log.count('PASS SOC_INPUT16_GATE')==tasks and log.count('params=189328 input_words=3168 output_words=1584 host_words=192508')==tasks
            if point:assert 'SOC_GATE_RESET_IN_FLIGHT point=%d'%point in log
            if crc:assert 'PASS LOCAL_PREFETCH_CRC_REJECT' in log
            if stall:assert 'PASS LOCAL_SCORE_STALL mac_cycles=17 held_requant_cycles=11' in log
            for i in range(tasks):assert (d/('matrix_task_%02d.hex'%i)).read_text().split()==(p/('fixtures/expected_%03d.hex'%r['case'])).read_text().split()
            assert len(r['profiles'])==len(r['transfer_profiles'])==tasks
            for profile,tr in zip(r['profiles'],r['transfer_profiles']):
                assert profile[3]==(1865760 if baseline else 1762432 if stall else 1762404) and profile[5]==1239000
                assert tr[1:5]==[4,192496,1584,2] and tr[7]==0
            phases={int(n):int(c) for n,c in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',log)}
            assert sum(phases.values())+12+(28 if stall else 0)==r['profiles'][-1][3]
            evidence[d.relative_to(out).as_posix()]=dict(result=r,model_sha256=sha(exe),source_receipt_sha256=sha(exe.parent/'sources.json'),command_sha256=sha(d/'command.json'))
        return s
    b=soc('baseline/cold0',baseline=True);c=soc('candidate/cold0');soc('full12',cases=tuple(range(12)));w=soc('consecutive',tasks=2)
    reuse=out/'baseline/parent_model/reuse_receipt.json'
    if reuse.exists():assert read(reuse)['exe_SHA256']==b['model_sha256']==parent['model_sha256']
    soc('crc_recovery',crc=True);soc('targeted_v2/stall',stall=True)
    for name,point in RESETS:soc(name,point=point)
    assert b['cases'][0]['profiles'][0][2:]==[2294607,1865760,7615408,1239000]
    assert c['cases'][0]['profiles'][0][2:]==[2281457,1762404,7615408,1239000]
    phase=lambda p:{int(n):int(v) for n,v in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',p.read_text())}
    old,new=[phase(out/n/'case_00/run.log') for n in ['baseline/cold0','candidate/cold0']]
    delta={n:new.get(n,0)-old.get(n,0) for n in old.keys()|new.keys() if old.get(n,0)!=new.get(n,0)};assert delta=={18:-103356}
    inv=read(out/'inventory/summary.json');assert inv['passed'] and inv['declared_register_bits']==33012 and inv['multiplier_operator_instances']==144 and inv['private_SRAM_macros']==20 and inv['source_sha256'][CORE]==cm['files'][CORE]
    bound=read(out/'ceiling_v2/ceiling.json');assert bound['source_SHA256']==cm['files'][CORE] and bound['necessary_serial_cycles']==1377888
    assert bound['iterative_SHA256']==cm['files']['rtl/v2/kwt_iterative.sv']
    r=dict(passed=True,parent_commit=PARENT,production_source_commit=REV,branch='codex/score4-opt-20261115',changed_production_files=[CORE],production_SHA256=cm['files'][CORE],
        evidence=evidence,full_network_cold_classes=12,full_network_codes=76032,same_object_consecutive_codes=12672,host_gap_cycles=4,
        timing_window='first host request through physical CPU completion-marker response after final output ACK',
        case0_parent=b['cases'][0],case0_candidate=c['cases'][0],warm_second_cycles=w['cases'][0]['profiles'][1][2],
        task_cycles_saved=13150,latency_reduction_percent=100*13150/2294607,compute_cycles_saved=103356,phase_cycle_changes=delta,
        noncompute_wait_added=90206,private_case0_read_write_change=[0,0],shared_case0_read_write_change=[3508,0],
        declared_accelerator_bits_before=33012,declared_accelerator_bits_after=33012,new_control_bits=0,
        PE_array='8x16 unchanged',math_lanes=4,private_macros=20,full_SoC_macros_expected=100,
        score_bank_mapping='low/high=2*(row%4),2*(row%4)+1; address=99*(row/4)+key; only dead Q-weight addresses0..197',
        arithmetic_parameters_firmware_NICE_owner_original_decoder_ports_changed=False,
        conditional_150MHz=dict(frequency_signed_off=False,parent_tasks_s=150000000/2294607,candidate_tasks_s=150000000/2281457,goal120_achieved=False),
        necessary_serial_cycles=1377888,ideal_upper_tasks_s_for_this_schedule_at_assumed150MHz=150000000/1377888,
        verification=dict(full_SoC_two_state=True,timed_SV=True,full_SoC_four_state=False,vendor_gate=False,physical_signoff=False),
        compiler_versions=compiler,area_mm2=None,power_mW=None,energy_uJ=None,
        inherited_accuracy=dict(samples=4445,FP_correct=4348,integer_correct=4345,drop_pp=300/4445,new_RTL_4445_or_official600=False))
    dest.write_text(json.dumps(r,indent=2)+'\n');print('PASS SCORE4 RELEASE COLLECTION',76032,'codes')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--collect-only',action='store_true');a=ap.parse_args();out=a.output.resolve()
    if not a.collect_only:reproduce(out)
    collect(out)
