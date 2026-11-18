"""Unified fresh reproduction and strict collection of the Dense candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PARENT='8ef274d289e1d8ba094c8b5021b9db365b906072'
REV='40d532337410cbd6cdf4a6d3556dc318d790d3cf'
CORE='rtl/v2/kwt_layer_banked.sv'
BENCH='flow/tb_soc_metrics.sv'
GROUPS=[('full12',['--cases',','.join(map(str,range(12))),'--jobs','4']),
        ('consecutive',['--tasks','2']),('crc_recovery',['--crc'])]
TARGETS=[('overlap_reset',11),('tail_reset',12),('s16_reset',13),('error_recovery',14)]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def run(script,*args):subprocess.run([sys.executable,str(ROOT/'scripts'/script),*map(str,args)],cwd=ROOT,check=True)

def reproduce(out):
    assert not out.exists(),'preserve existing logs'
    for label,opts in [('baseline',['--baseline']),('candidate',[])]:
        p=out/label/'project';run('prepare_dense_overlap.py','--output',p,*opts)
        run('check_pv16_soc.py','--project',p,'--output',out/label/('cold0' if opts else 'cold0_gap4'),'--cases','0','--jobs','1','--host-gap','4')
    p=out/'candidate/project';exe=out/'candidate/cold0_gap4/model/sim.exe'
    for name,args in GROUPS:run('check_pv16_soc.py','--project',p,'--model',exe,'--output',out/name,'--host-gap','4',*args)
    p=out/'error_target/project';run('prepare_dense_overlap.py','--output',p,'--targeted','--error-checks')
    run('check_pv16_soc.py','--project',p,'--output',out/'targeted/stall','--host-gap','4','--stall','--stall-kind','dense')
    exe=out/'targeted/stall/model/sim.exe'
    for name,point in TARGETS:run('check_pv16_soc.py','--project',p,'--model',exe,'--output',out/name,'--host-gap','4','--recovery','--reset-point',point)
    run('inventory_pv16.py','--project',out/'candidate/project','--output',out/'inventory')
    run('calculate_dense_overlap_ceiling.py','--output',out/'ceiling_v2','--log',out/'candidate/cold0_gap4/case_00/run.log')

def collect(out):
    dest=out/'release_summary.json';assert not dest.exists()
    cp=out/'candidate/project';bp=out/'baseline/project';cm,bm=[read(p/'source_manifest.json') for p in [cp,bp]]
    for p,m in [(cp,cm),(bp,bm)]:assert len(m['files'])==194 and all(sha(p/n)==h for n,h in m['files'].items())
    assert [n for n in cm['files'] if cm['files'][n]!=bm['files'][n]]==[CORE]
    raw=subprocess.check_output(['git','show',REV+':rtl/dense_overlap/kwt_layer_banked.sv'],cwd=ROOT)
    assert hashlib.sha256(raw).hexdigest()==sha(ROOT/'rtl/dense_overlap/kwt_layer_banked.sv')==cm['files'][CORE]
    previous=read(ROOT/'evidence/nice_prefetch2_20261115/candidate/project/source_manifest.json')
    assert [n for n in bm['files'] if bm['files'][n]!=previous['files'][n]]==[BENCH]
    # The final parent preparer adds three optional reset-point waits that were
    # absent from its earlier cold0 snapshot. Both new variants use the same
    # bench; cold0 does not enter this recovery case statement. Prove the full
    # old bench byte identity after removing only those exact three lines.
    bench_raw=(bp/BENCH).read_bytes();lines=bench_raw.splitlines(keepends=True)
    removed=[x for x in lines if any(x.startswith(('       %d:wait('%i).encode()) for i in [8,9,10])]
    assert len(removed)==3
    normalized=b''.join(x for x in lines if x not in removed)
    assert hashlib.sha256(normalized).hexdigest()==previous['files'][BENCH]
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
            assert r['CRC_rejection_full_recovery']==crc and bool(r.get('Dense_stalls',False))==stall
            d=folder/('case_%02d'%r['case']);cmd=read(d/'command.json');exe=Path(cmd[0]);assert sha(exe)==s['model_sha256']
            assert read(exe.parent/'sources.json')==s['source_bindings']
            project=Path(next(v.split('=',1)[1] for v in cmd if v.startswith('+FIXTURES='))).parent;m=read(project/'source_manifest.json')
            assert m['files']==bound and sha(project/'source_manifest.json')==s['source_bindings']['source_manifest_sha256']
            assert all(sha(project/n)==h for n,h in bound.items()) and '+HOST_GAP=4' in cmd
            assert sha(d/'run.log')==r['log_sha256'];log=(d/'run.log').read_text()
            assert log.count('PASS SOC_INPUT16_GATE')==tasks
            assert log.count('params=189328 input_words=3168 output_words=1584 host_words=192508')==tasks
            if point:assert 'SOC_GATE_RESET_IN_FLIGHT point=%d'%point in log
            if point==14:assert 'PASS LOCAL_DENSE_ERROR_QUIESCENT cycles=8' in log
            if crc:assert 'PASS LOCAL_PREFETCH_CRC_REJECT' in log
            if stall:assert 'PASS LOCAL_DENSE_STALL mac_cycles=17 held_requant_cycles=11' in log
            for i in range(tasks):assert (d/('matrix_task_%02d.hex'%i)).read_text().split()==(project/('fixtures/expected_%03d.hex'%r['case'])).read_text().split()
            assert len(r['profiles'])==len(r['transfer_profiles'])==tasks
            for profile,tr in zip(r['profiles'],r['transfer_profiles']):
                assert profile[3]==(2027232 if baseline else 1865788 if stall else 1865760) and profile[5]==1239000
                assert tr[1:5]==[4,192496,1584,2] and tr[7]==0
            phases={int(n):int(c) for n,c in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',log)}
            # Phase counters require RUN && core.enable. The accelerator's
            # compute counter also includes twelve KICK clocks and disabled
            # stall clocks. Those are different documented counter enables.
            assert sum(phases.values())+12+(28 if stall else 0)==r['profiles'][-1][3]
            evidence[d.relative_to(out).as_posix()]=dict(result=r,model_sha256=sha(exe),source_receipt_sha256=sha(exe.parent/'sources.json'),command_sha256=sha(d/'command.json'))
        return s
    b=soc('baseline/cold0',baseline=True);c=soc('candidate/cold0_gap4')
    full=soc('full12',cases=tuple(range(12)));warm=soc('consecutive',tasks=2);soc('crc_recovery',crc=True)
    soc('targeted/stall',stall=True)
    for name,point in TARGETS:soc(name,point=point)
    assert b['cases'][0]['profiles'][0][2:]==[2330328,2027232,7615408,1239000]
    assert c['cases'][0]['profiles'][0][2:]==[2294607,1865760,7615408,1239000]
    assert all(r['profiles'][0][2]==2294607 for r in full['cases'])
    phase=lambda p:{int(n):int(c) for n,c in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',p.read_text())}
    old_phase=phase(out/'baseline/cold0/case_00/run.log');new_phase=phase(out/'candidate/cold0_gap4/case_00/run.log')
    delta={n:new_phase.get(n,0)-old_phase.get(n,0) for n in old_phase.keys()|new_phase.keys() if old_phase.get(n,0)!=new_phase.get(n,0)}
    assert delta=={8:-168576,10:-4512,94:11616}
    inv=read(out/'inventory/summary.json');assert inv['passed'] and inv['declared_register_bits']==33012 and inv['multiplier_operator_instances']==144 and inv['private_SRAM_macros']==20
    assert inv['source_sha256'][CORE]==cm['files'][CORE]
    ceiling=read(out/'ceiling_v2/ceiling.json');assert ceiling['necessary_serial_cycles']==1326804 and ceiling['source_SHA256']==cm['files'][CORE]
    result=dict(passed=True,parent_commit=PARENT,production_source_commit=REV,branch='codex/dense-overlap-20261115',
        changed_production_files=[CORE],production_SHA256=cm['files'][CORE],evidence=evidence,
        full_network_cold_classes=12,full_network_codes=76032,same_object_consecutive_codes=12672,host_gap_cycles=4,
        timing_window='first host request through physical CPU completion-marker response after final output ACK',
        case0_parent=b['cases'][0],case0_candidate=c['cases'][0],warm_second_cycles=warm['cases'][0]['profiles'][1][2],
        task_cycles_saved=35721,latency_reduction_percent=100*35721/2330328,compute_cycles_saved=161472,
        noncompute_wait_added=125751,phase_cycle_changes=delta,private_case0_read_write_change=[0,0],shared_case0_read_write_change=[4772,0],
        declared_accelerator_bits_before=33003,declared_accelerator_bits_after=33012,new_control_bits=9,
        PE_array='8x16 unchanged',math_lanes=4,private_macros=20,full_SoC_macros_expected=100,
        numerical_model_parameters_firmware_NICE_owner_original_decoder_ports_changed=False,
        conditional_150MHz=dict(frequency_signed_off=False,parent_tasks_s=150000000/2330328,candidate_tasks_s=150000000/2294607,goal120_achieved=False),
        necessary_compute_cycles_lower_bound=1326804,ideal_upper_tasks_s_for_this_schedule_at_assumed150MHz=150000000/1326804,
        verification=dict(full_SoC_two_state=True,timed_SV=True,full_SoC_four_state=False,vendor_gate=False,physical_signoff=False),
        compiler_versions=compiler,area_mm2=None,power_mW=None,energy_uJ=None,
        inherited_accuracy=dict(samples=4445,FP_correct=4348,integer_correct=4345,drop_pp=300/4445,new_RTL_4445_or_official600=False))
    dest.write_text(json.dumps(result,indent=2)+'\n');print('PASS DENSE RELEASE COLLECTION',76032,'codes')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--collect-only',action='store_true');a=ap.parse_args();out=a.output.resolve()
    if not a.collect_only:reproduce(out)
    collect(out)
