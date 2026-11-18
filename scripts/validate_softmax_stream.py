"""Fresh full reproduction and strict binding of the exact streaming candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PARENT='5b3deec31c8e34d8e1484ae794fb1912ce4c8986'
REV='d8fe71081eb893b3c8394dc1d9c3a0ea1aa129ff'
CORE='rtl/v2/kwt_layer_banked.sv';BENCH='flow/tb_soc_metrics.sv'
GROUPS=[('full12',['--cases',','.join(map(str,range(12))),'--jobs','4']),('consecutive',['--tasks','2']),('crc_recovery',['--crc'])]
RESETS=[('max_capture_reset',18),('stream_tail_reset',19),('alias_reset',20)]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def run(script,*args):subprocess.run([sys.executable,str(ROOT/'scripts'/script),*map(str,args)],cwd=ROOT,check=True)

def reproduce(out):
    assert not out.exists(),'preserve logs'
    for label,opts in [('baseline',['--baseline']),('candidate',[])]:
        p=out/label/'project';run('prepare_softmax_stream.py','--output',p,*opts)
        run('check_pv16_soc.py','--project',p,'--output',out/label/'cold0','--cases','0','--jobs','1','--host-gap','4')
    p=out/'candidate/project';exe=out/'candidate/cold0/model/sim.exe'
    for name,args in GROUPS:run('check_pv16_soc.py','--project',p,'--model',exe,'--output',out/name,'--host-gap','4',*args)
    p=out/'targeted/project';run('prepare_softmax_stream.py','--output',p,'--targeted')
    run('check_pv16_soc.py','--project',p,'--output',out/'targeted/stall','--host-gap','4','--stall','--stall-kind','stream')
    exe=out/'targeted/stall/model/sim.exe'
    for name,point in RESETS:run('check_pv16_soc.py','--project',p,'--model',exe,'--output',out/name,'--host-gap','4','--recovery','--reset-point',point)
    run('check_stream_max.py','--output',out/'max_unit')
    run('check_pv16_consumers.py','--project',out/'candidate/project','--output',out/'consumers')
    for label,proj,model in [('parent','baseline/project','baseline/cold0/model/sim.exe'),('stream','candidate/project','candidate/cold0/model/sim.exe')]:
        run('check_pv16_soc.py','--project',out/proj,'--model',out/model,'--output',out/('profiles/gap0_'+label),'--host-gap','0','--cases','0','--jobs','1')
    run('inventory_pv16.py','--project',out/'candidate/project','--output',out/'inventory')
    run('calculate_stream_ceiling.py','--output',out/'ceiling','--log',out/'candidate/cold0/case_00/run.log')

def collect(out):
    dest=out/'release_summary.json';assert not dest.exists()
    cp,bp=[out/n/'project' for n in ['candidate','baseline']];cm,bm=[read(p/'source_manifest.json') for p in [cp,bp]]
    for p,m in [(cp,cm),(bp,bm)]:assert len(m['files'])==194 and all(sha(p/n)==h for n,h in m['files'].items())
    assert [n for n in cm['files'] if cm['files'][n]!=bm['files'][n]]==[CORE]
    parent=read(ROOT/'evidence/score4_20261115/candidate/cold0/summary.json')
    assert bm['files']==parent['source_bindings']['files']
    raw=subprocess.check_output(['git','show',REV+':rtl/softmax_stream/kwt_layer_banked.sv'],cwd=ROOT)
    assert hashlib.sha256(raw).hexdigest()==sha(ROOT/'rtl/softmax_stream/kwt_layer_banked.sv')==cm['files'][CORE]
    evidence={};compiler=None
    def soc(name,cases=(0,),tasks=1,point=0,crc=False,stall=False,baseline=False,gap=4):
        nonlocal compiler
        folder=out/name;s=read(folder/'summary.json');assert s['passed'] and s['two_state'] and s['timed_SV']
        assert s['total_codes']==len(cases)*tasks*6336 and [r['case'] for r in s['cases']]==list(cases)
        if compiler is None:compiler=s['compiler_versions']
        else:assert compiler==s['compiler_versions']
        files=bm['files'] if baseline else cm['files'];bound=s['source_bindings']['files']
        assert files.keys()==bound.keys() and all(files[n]==bound[n] for n in files if n!=BENCH)
        for r in s['cases']:
            assert r['passed'] and r['tasks']==tasks and r['reset_point']==point and r['recovery']==bool(point)
            assert r['CRC_rejection_full_recovery']==crc and bool(r.get('Stream_stalls',False))==stall
            d=folder/('case_%02d'%r['case']);cmd=read(d/'command.json');exe=Path(cmd[0]);assert sha(exe)==s['model_sha256']
            assert read(exe.parent/'sources.json')==s['source_bindings']
            p=Path(next(v.split('=',1)[1] for v in cmd if v.startswith('+FIXTURES='))).parent;m=read(p/'source_manifest.json')
            assert m['files']==bound and sha(p/'source_manifest.json')==s['source_bindings']['source_manifest_sha256']
            assert all(sha(p/n)==h for n,h in bound.items()) and ('+HOST_GAP='+str(gap)) in cmd
            assert sha(d/'run.log')==r['log_sha256'];log=(d/'run.log').read_text()
            assert log.count('PASS SOC_INPUT16_GATE')==tasks and log.count('params=189328 input_words=3168 output_words=1584 host_words=192508')==tasks
            if point:assert 'SOC_GATE_RESET_IN_FLIGHT point=%d'%point in log
            if crc:assert 'PASS LOCAL_PREFETCH_CRC_REJECT' in log
            if stall:assert 'PASS LOCAL_STREAM_STALL score_exp_cycles=17 alias_result_cycles=11' in log
            for i in range(tasks):assert (d/('matrix_task_%02d.hex'%i)).read_text().split()==(p/('fixtures/expected_%03d.hex'%r['case'])).read_text().split()
            assert len(r['profiles'])==len(r['transfer_profiles'])==tasks
            for profile,tr in zip(r['profiles'],r['transfer_profiles']):
                assert profile[3]==(1762404 if baseline else 1644820 if stall else 1644792) and profile[5]==1239000
                assert tr[1:5]==[gap,192496,1584,2] and tr[7]==0
            phases={int(n):int(c) for n,c in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',log)}
            assert sum(phases.values())+12+(28 if stall else 0)==r['profiles'][-1][3]
            evidence[d.relative_to(out).as_posix()]=dict(result=r,model_sha256=sha(exe),source_receipt_sha256=sha(exe.parent/'sources.json'),command_sha256=sha(d/'command.json'))
        return s
    b=soc('baseline/cold0',baseline=True);c=soc('candidate/cold0');soc('full12',cases=tuple(range(12)));w=soc('consecutive',tasks=2)
    assert compiler==parent['compiler_versions'],'cached parent compiled with different tools'
    reuse=out/'baseline/parent_model/reuse_receipt.json'
    if reuse.exists():assert read(reuse)['exe_SHA256']==b['model_sha256']==parent['model_sha256']
    soc('crc_recovery',crc=True);soc('targeted/stall',stall=True)
    for name,point in RESETS:soc(name,point=point)
    fastb=soc('profiles/gap0_parent',baseline=True,gap=0);fastc=soc('profiles/gap0_stream',gap=0)
    unit=read(out/'max_unit/summary.json');assert unit['passed'] and unit['four_state'] and unit['source_SHA256']==cm['files'][CORE] and unit['integer_max_vectors']==8354 and unit['unknown_old_first_tests']==2
    assert all(sha(out/'max_unit'/n)==h for n,h in unit['files'].items())
    consumers=read(out/'consumers/summary.json');assert consumers['passed'] and consumers['four_state'] and consumers['math_results']==4152 and consumers['iterative_vectors']==821
    for filename,h in consumers['source_sha256'].items():
        p=Path(filename);assert sha(p)==h
        if p.name!='tb_consumers.sv':assert cm['files'][p.relative_to(cp).as_posix()]==h
    assert b['cases'][0]['profiles'][0][2:]==[2281457,1762404,7615408,1239000]
    assert c['cases'][0]['profiles'][0][2:]==[2271587,1644792,7615408,1239000]
    phase=lambda p:{int(n):int(v) for n,v in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',p.read_text())}
    old,new=[phase(out/n/'case_00/run.log') for n in ['baseline/cold0','candidate/cold0']]
    delta={n:new.get(n,0)-old.get(n,0) for n in old.keys()|new.keys() if old.get(n,0)!=new.get(n,0)};assert delta=={70:-117612}
    inv=read(out/'inventory/summary.json');assert inv['passed'] and inv['declared_register_bits']==33012 and inv['multiplier_operator_instances']==144 and inv['private_SRAM_macros']==20 and inv['source_sha256'][CORE]==cm['files'][CORE]
    bound=read(out/'ceiling/ceiling.json');assert bound['source_SHA256']==cm['files'][CORE] and bound['necessary_serial_cycles']==1260276
    assert bound['base_iterative_SHA256']==cm['files']['rtl/v2/kwt_iterative.sv']
    r=dict(passed=True,parent_commit=PARENT,production_source_commit=REV,branch='codex/softmax-stream-20261115',changed_production_files=[CORE],production_SHA256=cm['files'][CORE],
        separate_gap0_profile=dict(parent=fastb['cases'][0],candidate=fastc['cases'][0],same_original_interface=True,only_one_class=True,counts_not_mixed_with_default_gain=True),
        evidence=evidence,full_network_cold_classes=12,full_network_codes=76032,same_object_consecutive_codes=12672,host_gap_cycles=4,
        timing_window='first host request through physical CPU completion-marker response after final output ACK',
        case0_parent=b['cases'][0],case0_candidate=c['cases'][0],warm_second_cycles=w['cases'][0]['profiles'][1][2],
        task_cycles_saved=9870,latency_reduction_percent=100*9870/2281457,compute_cycles_saved=117612,phase_cycle_changes=delta,
        noncompute_wait_added=107742,private_case0_read_write_change=[0,0],shared_case0_read_write_change=[3994,0],
        declared_accelerator_bits_before=33012,declared_accelerator_bits_after=33012,new_control_bits=0,
        PE_array='8x16 unchanged',math_lanes=4,private_macros=20,full_SoC_macros_expected=100,
        score_bank_mapping='low/high=2*(row%4),2*(row%4)+1; address=99*(row/4)+key; only dead Q-weight addresses0..197',
        arithmetic_parameters_firmware_NICE_owner_original_decoder_ports_changed=False,
        conditional_150MHz=dict(frequency_signed_off=False,parent_tasks_s=150000000/2281457,candidate_tasks_s=150000000/2271587,goal100_achieved=False),
        necessary_serial_cycles=1260276,ideal_upper_tasks_s_for_this_schedule_at_assumed150MHz=150000000/1260276,
        verification=dict(full_SoC_two_state=True,timed_SV=True,full_SoC_four_state=False,vendor_gate=False,physical_signoff=False),
        max_unit_four_state=unit,actual_math_iter_unit_four_state=consumers,target_tasks_s=100,compiler_versions=compiler,area_mm2=None,power_mW=None,energy_uJ=None,
        inherited_accuracy=dict(samples=4445,FP_correct=4348,integer_correct=4345,drop_pp=300/4445,new_RTL_4445_or_official600=False))
    dest.write_text(json.dumps(r,indent=2)+'\n');print('PASS STREAM RELEASE COLLECTION',76032,'codes')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--collect-only',action='store_true');a=ap.parse_args();out=a.output.resolve()
    if not a.collect_only:reproduce(out)
    collect(out)
