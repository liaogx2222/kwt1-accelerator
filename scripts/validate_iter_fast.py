"""Unified fresh reproduction and strict source-bound iterative acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PARENT='8901e14ba4028d0711f25e0cfa598c6abe13835b';REV='c90b1e2a8be95ec1df2e2d73cf832239b684cde1'
CORE='rtl/v2/kwt_layer_banked.sv';ITER='rtl/v2/kwt_iterative.sv';BENCH='flow/tb_soc_metrics.sv'
RESETS=[('sqrt_reset',21),('div47_reset',22),('held_reset_v2',23),('div40_last_reset',24)]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def run(script,*args):subprocess.run([sys.executable,str(ROOT/'scripts'/script),*map(str,args)],cwd=ROOT,check=True)

def reproduce(out):
    assert not out.exists(),'preserve prior attempts'
    for label,opts in [('baseline',['--baseline']),('candidate',[])]:
        p=out/label/'project';run('prepare_iter_fast.py','--output',p,*opts)
        run('check_pv16_soc.py','--project',p,'--output',out/label/'cold0','--cases','0','--jobs','1','--host-gap','4')
    p=out/'candidate/project';exe=out/'candidate/cold0/model/sim.exe'
    for name,args in [('full12',['--cases',','.join(map(str,range(12))),'--jobs','4']),('consecutive',['--tasks','2']),('crc_recovery',['--crc'])]:
        run('check_pv16_soc.py','--project',p,'--model',exe,'--output',out/name,'--host-gap','4',*args)
    p=out/'targeted_v2/project';run('prepare_iter_fast.py','--output',p,'--targeted')
    run('check_pv16_soc.py','--project',p,'--output',out/'targeted/stall','--host-gap','4','--stall','--stall-kind','iter')
    exe=out/'targeted/stall/model/sim.exe'
    for name,point in RESETS:run('check_pv16_soc.py','--project',p,'--model',exe,'--output',out/name,'--host-gap','4','--recovery','--reset-point',point)
    for label,pp,mm in [('parent','baseline/project','baseline/cold0/model/sim.exe'),('iter','candidate/project','candidate/cold0/model/sim.exe')]:
        run('check_pv16_soc.py','--project',out/pp,'--model',out/mm,'--output',out/('profiles/gap0_'+label),'--host-gap','0','--cases','0','--jobs','1')
    run('check_iter_fast.py','--output',out/'unit');run('check_iter_consumers.py','--project',out/'candidate/project','--output',out/'consumers')
    run('inventory_pv16.py','--project',out/'candidate/project','--output',out/'inventory')
    run('analyze_iter_fast.py','--round',out,'--output',out/'analysis')

def collect(out):
    dest=out/'release_summary.json';assert not dest.exists()
    cp,bp=[out/n/'project' for n in ['candidate','baseline']];cm,bm=[read(p/'source_manifest.json') for p in [cp,bp]]
    for p,m in [(cp,cm),(bp,bm)]:assert len(m['files'])==194 and all(sha(p/n)==h for n,h in m['files'].items())
    assert sorted(n for n in cm['files'] if cm['files'][n]!=bm['files'][n])==sorted([CORE,ITER])
    parent=read(ROOT/'evidence/softmax_stream_20261115/candidate/cold0/summary.json');assert bm['files']==parent['source_bindings']['files']
    for n in [CORE,ITER]:
        raw=subprocess.check_output(['git','show',REV+':rtl/iter_fast/'+Path(n).name],cwd=ROOT)
        assert hashlib.sha256(raw).hexdigest()==sha(ROOT/'rtl/iter_fast'/Path(n).name)==cm['files'][n]
    evidence={};compiler=None
    def soc(name,cases=(0,),tasks=1,point=0,crc=False,stall=False,baseline=False,gap=4):
        nonlocal compiler
        folder=out/name;s=read(folder/'summary.json');assert s['passed'] and s['two_state'] and s['timed_SV']
        assert s['total_codes']==len(cases)*tasks*6336 and [r['case'] for r in s['cases']]==list(cases)
        if compiler is None:compiler=s['compiler_versions']
        else:assert compiler==s['compiler_versions']
        expected=bm['files'] if baseline else cm['files'];bound=s['source_bindings']['files']
        assert bound.keys()==expected.keys() and all(bound[n]==expected[n] for n in bound if n!=BENCH)
        for r in s['cases']:
            assert r['passed'] and r['tasks']==tasks and r['reset_point']==point and r['recovery']==bool(point)
            assert r['CRC_rejection_full_recovery']==crc and bool(r.get('Iter_stalls',False))==stall
            d=folder/('case_%02d'%r['case']);cmd=read(d/'command.json');exe=Path(cmd[0]);assert sha(exe)==s['model_sha256'] and read(exe.parent/'sources.json')==s['source_bindings']
            p=Path(next(x.split('=',1)[1] for x in cmd if x.startswith('+FIXTURES='))).parent;m=read(p/'source_manifest.json')
            assert m['files']==bound and sha(p/'source_manifest.json')==s['source_bindings']['source_manifest_sha256'] and all(sha(p/n)==h for n,h in bound.items())
            assert ('+HOST_GAP='+str(gap)) in cmd and sha(d/'run.log')==r['log_sha256'];log=(d/'run.log').read_text()
            assert log.count('PASS SOC_INPUT16_GATE')==tasks and log.count('params=189328 input_words=3168 output_words=1584 host_words=192508')==tasks
            if point:assert 'SOC_GATE_RESET_IN_FLIGHT point=%d'%point in log
            if point==23:assert 'PASS LOCAL_ITER_HELD_RESET_SETUP' in log and 'LOCAL_ITER_RESET_POST core_rst=0 valid=0' in log
            if crc:assert 'PASS LOCAL_PREFETCH_CRC_REJECT' in log
            if stall:assert 'PASS LOCAL_ITER_STALL sqrt_result_cycles=17 div_result_cycles=11' in log
            for i in range(tasks):assert (d/('matrix_task_%02d.hex'%i)).read_text().split()==(p/('fixtures/expected_%03d.hex'%r['case'])).read_text().split()
            assert len(r['profiles'])==len(r['transfer_profiles'])==tasks
            for profile,tr in zip(r['profiles'],r['transfer_profiles']):
                assert profile[3]==(1644792 if baseline else 1568788 if stall else 1568760) and profile[5]==1239000
                assert tr[1:5]==[gap,192496,1584,2] and tr[7]==0
            phases={int(n):int(v) for n,v in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',log)}
            assert sum(phases.values())+12+(28 if stall else 0)==r['profiles'][-1][3]
            evidence[d.relative_to(out).as_posix()]=dict(result=r,model_sha256=sha(exe),source_receipt_sha256=sha(exe.parent/'sources.json'),command_sha256=sha(d/'command.json'))
        return s
    b=soc('baseline/cold0',baseline=True);c=soc('candidate/cold0');full=soc('full12',cases=tuple(range(12)));w=soc('consecutive',tasks=2)
    assert compiler==parent['compiler_versions']
    reuse=out/'baseline/parent_model/reuse_receipt.json'
    if reuse.exists():assert read(reuse)['exe_SHA256']==b['model_sha256']==parent['model_sha256']
    soc('crc_recovery',crc=True);soc('targeted/stall',stall=True)
    for name,point in RESETS:soc(name,point=point)
    fastb=soc('profiles/gap0_parent',baseline=True,gap=0);fastc=soc('profiles/gap0_iter',gap=0)
    assert b['cases'][0]['profiles'][0][2:]==[2271587,1644792,7615408,1239000] and c['cases'][0]['profiles'][0][2:]==[2265230,1568760,7615408,1239000]
    assert all(r['profiles'][0][2]==2265230 for r in full['cases'])
    phase=lambda p:{int(n):int(v) for n,v in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',p.read_text())}
    old,new=[phase(out/n/'case_00/run.log') for n in ['baseline/cold0','candidate/cold0']]
    delta={n:new.get(n,0)-old.get(n,0) for n in old.keys()|new.keys() if old.get(n,0)!=new.get(n,0)};assert delta=={93:-76032}
    inv=read(out/'inventory/summary.json');assert inv['passed'] and inv['declared_register_bits']==32949 and inv['multiplier_operator_instances']==144 and inv['private_SRAM_macros']==20
    assert all(inv['source_sha256'][n]==cm['files'][n] for n in [CORE,ITER])
    unit=read(out/'unit/summary.json');assert unit['passed'] and unit['four_state'] and unit['source_SHA256']==cm['files'][ITER] and unit['bench_SHA256']==sha(out/'unit/tb_iter.sv')
    assert unit['exhaustive_sqrt_input0_to65535'] and unit['Python_divmod_isqrt_independent_oracle'] and len(unit['cases'])==6
    assert unit['cases']['fast']['params']==[1,1,1,1] and unit['cases']['fast']['vectors']==78473
    for label,row in unit['cases'].items():
        assert row['passed'] and row['reset_groups']==10 and sha(out/'unit'/label/'run.log')==row['log_SHA256'] and sha(out/'unit'/row['vector_file'])==row['vector_SHA256']
    cons=read(out/'consumers/summary.json');assert cons['passed'] and cons['four_state'] and cons['math_results']==4152 and cons['iterative_vectors']==821 and cons['actual_RADIX16_CONST']==cons['actual_DOUBLE_SQRT']==1
    for fn,h in cons['source_sha256'].items():
        p=Path(fn);assert sha(p)==h
        if p.name!='tb_consumers.sv':assert cm['files'][p.relative_to(cp).as_posix()]==h
    analysis=read(out/'analysis/summary.json');assert analysis['passed'] and analysis['files']=={n:cm['files'][n] for n in [CORE,ITER]} and analysis['I_WAIT_cycles']==[154440,78408]
    r=dict(passed=True,parent_commit=PARENT,production_source_commit=REV,branch='codex/iter-fast-20261115',changed_production_files=[ITER,CORE],production_SHA256={n:cm['files'][n] for n in [ITER,CORE]},
        evidence=evidence,full_network_cold_classes=12,full_network_codes=76032,same_object_consecutive_codes=12672,host_gap_cycles=4,
        timing_window='first host request through physical CPU completion-marker response after final output ACK',case0_parent=b['cases'][0],case0_candidate=c['cases'][0],warm_second_cycles=w['cases'][0]['profiles'][1][2],
        task_cycles_saved=6357,latency_reduction_percent=100*6357/2271587,compute_cycles_saved=76032,phase_cycle_changes=delta,noncompute_wait_added=69675,
        private_case0_read_write_change=[0,0],shared_case0_read_write_change=[1538,0],declared_accelerator_bits=[33012,32949],declared_unit_bits=[526,463],
        PE_array='8x16 unchanged',math_lanes=4,iterative_units=1,private_macros=20,full_SoC_macros_expected=100,numeric_results_parameters_firmware_NICE_owner_decoder_ports_changed=False,
        separate_gap0_profile=dict(parent=fastb['cases'][0],candidate=fastc['cases'][0],same_original_interface=True,only_one_class=True,counts_not_mixed_with_default_gain=True),
        verification=dict(full_SoC_two_state=True,timed_SV=True,full_SoC_four_state=False,vendor_gate=False,physical_signoff=False),
        unit=unit,actual_consumers=cons,analysis=analysis,compiler_versions=compiler,target_tasks_s=100,
        conditional_150MHz=dict(frequency_signed_off=False,parent_tasks_s=150000000/2271587,candidate_tasks_s=150000000/2265230,goal100_achieved=False),
        area_mm2=None,power_mW=None,energy_uJ=None,inherited_accuracy=dict(samples=4445,FP_correct=4348,integer_correct=4345,drop_pp=300/4445,new_RTL_4445_or_official600=False))
    dest.write_text(json.dumps(r,indent=2)+'\n');print('PASS ITER RELEASE COLLECTION',76032,'codes')
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--collect-only',action='store_true');a=ap.parse_args();out=a.output.resolve()
    if not a.collect_only:reproduce(out)
    collect(out)
