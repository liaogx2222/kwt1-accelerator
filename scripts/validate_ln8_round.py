"""Reproduce or collect LN8 without altering any frozen baseline project."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
REV='ccd3f9e3c534938bbd191e3b3e7de90fac4cfdd8'
PARENT='d011cbafdb38f15aa3395fbb2276e09692546356'
CORE='rtl/v2/kwt_layer_banked.sv'
BENCH='flow/tb_soc_metrics.sv'
GROUPS=[('full12',['--cases',','.join(map(str,range(12))),'--jobs','4']),
        ('consecutive',['--tasks','2']),('crc_recovery',['--crc']),
        ('ln_gather_reset',['--recovery','--reset-point','4']),
        ('ln_later_row_reset',['--recovery','--reset-point','5']),
        ('ln_tail_reset',['--recovery','--reset-point','6']),
        ('ln_pair_write_reset',['--recovery','--reset-point','7']),
        ('targeted/stall',['--stall','--stall-kind','ln'])]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def run(script,*args):subprocess.run([sys.executable,str(ROOT/'scripts'/script),*map(str,args)],cwd=ROOT,check=True)

def reproduce(out):
    assert not out.exists(),'use a fresh output path'
    project=out/'candidate/project'
    run('prepare_ln8_local.py','--output',project,'--ln-checks')
    run('check_pv16_soc.py','--project',project,'--output',out/'candidate/cold0','--cases','0','--jobs','1')
    model=out/'candidate/cold0/model/sim.exe'
    for name,args in GROUPS:
        run('check_pv16_soc.py','--project',project,'--model',model,'--output',out/name,*args)
    run('inventory_pv16.py','--project',project,'--output',out/'inventory')

def collect(out):
    dest=out/'release_summary.json';assert not dest.exists(),'preserve evidence'
    project=out/'candidate/project';manifest=read(project/'source_manifest.json');files=manifest['files']
    assert len(files)==194 and all(sha(project/n)==h for n,h in files.items())
    raw=subprocess.check_output(['git','show',REV+':rtl/ln8_opt/kwt_layer_banked.sv'],cwd=ROOT)
    assert hashlib.sha256(raw).hexdigest()==sha(ROOT/'rtl/ln8_opt/kwt_layer_banked.sv')==files[CORE]
    baseline=ROOT/'evidence/pv16_opt_20261114/final_candidate/cold0'
    parent=read(baseline/'summary.json');parent_files=parent['source_bindings']['files']
    assert parent['passed'] and parent_files.keys()==files.keys()
    assert [n for n in files if files[n]!=parent_files[n] and n!=BENCH]==[CORE]
    evidence={}
    def soc(name,cases=(0,),tasks=1,point=0,crc=False,stall=False):
        folder=out/name;s=read(folder/'summary.json');assert s['passed'] and s['variant']=='ln8' and s['two_state'] and s['timed_SV']
        assert s['compiler_versions']==parent['compiler_versions'],'tool mismatch'
        bound=s['source_bindings']['files'];assert bound.keys()==files.keys()
        assert all(bound[n]==files[n] for n in files if n!=BENCH)
        assert s['total_codes']==len(cases)*tasks*6336 and [r['case'] for r in s['cases']]==list(cases)
        for r in s['cases']:
            assert r['passed'] and r['tasks']==tasks and r['recovery']==bool(point) and r['reset_point']==point
            assert r['CRC_rejection_full_recovery']==crc and bool(r.get('LN_stalls',False))==stall
            d=folder/('case_%02d'%r['case']);assert sha(d/'run.log')==r['log_sha256']
            command=read(d/'command.json');exe=Path(command[0]);assert sha(exe)==s['model_sha256']
            assert read(exe.parent/'sources.json')==s['source_bindings']
            p=Path(next(v.split('=',1)[1] for v in command if v.startswith('+FIXTURES='))).parent
            receipt=read(p/'source_manifest.json')
            assert receipt['files']==bound and sha(p/'source_manifest.json')==s['source_bindings']['source_manifest_sha256']
            assert all(sha(p/n)==h for n,h in bound.items()),'tested snapshot drift'
            log=(d/'run.log').read_text()
            assert log.count('params=189328 input_words=3168 output_words=1584 host_words=192508')==tasks
            if point:assert 'SOC_GATE_RESET_IN_FLIGHT point=%d'%point in log
            if crc:assert 'PASS LOCAL_PREFETCH_CRC_REJECT params=65872 packets=5 outputs=0' in log
            if stall:assert 'PASS LOCAL_LN_STALL mac_cycles=17 held_requant_cycles=11' in log
            for i,profile in enumerate(r['profiles']):
                assert (d/('matrix_task_%02d.hex'%i)).read_text().split()==(p/('fixtures/expected_%03d.hex'%r['case'])).read_text().split()
                assert profile[0]==i and profile[3]==2027232+(28 if stall else 0)
                assert profile[5]==1239000
                if i==0:assert profile[1:3]==[2695113+(28 if stall else 0),2695118+(28 if stall else 0)]
        evidence[name]=dict(summary_sha256=sha(folder/'summary.json'),model_sha256=s['model_sha256'],bench_sha256=bound[BENCH],cases=s['cases'],codes=s['total_codes'])
        return s
    cold=soc('candidate/cold0');full=soc('full12',cases=tuple(range(12)));warm=soc('consecutive',tasks=2)
    soc('crc_recovery',crc=True)
    for name,point in [('ln_gather_reset',4),('ln_later_row_reset',5),('ln_tail_reset',6),('ln_pair_write_reset',7)]:soc(name,point=point)
    soc('targeted/stall',stall=True)
    assert warm['cases'][0]['profiles'][1]==[1,2695104,2695107,2027232,7615408,1239000]
    def phases(p):return {int(k):int(v) for k,v in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',p.read_text())}
    old,new=phases(baseline/'case_00/run.log'),phases(out/'candidate/cold0/case_00/run.log')
    assert {k for k in old if old[k]!=new[k]}=={40,41,42,74}
    assert [new[k] for k in [40,41,42,74]]==[19968,19968,312,2064]
    assert sum(old.values())-sum(new.values())==113664
    inventory=read(out/'inventory/summary.json')
    assert inventory['passed'] and inventory['declared_register_bits']==33003 and inventory['private_SRAM_macros']==20 and inventory['multiplier_operator_instances']==144
    assert all(files[n]==h for n,h in inventory['source_sha256'].items())
    b=parent['cases'][0]['profiles'][0];c=cold['cases'][0]['profiles'][0]
    assert b==[0,2729235,2729240,2140896,7615408,1239000]
    assert c==[0,2695113,2695118,2027232,7615408,1239000]
    r=dict(passed=True,branch='codex/ln8-opt-20261114',parent_commit=PARENT,production_source_commit=REV,
        production_SHA256=files[CORE],changed_production_files_relative_PV16=[CORE],evidence=evidence,
        inherited_baseline=dict(source='evidence/pv16_opt_20261114/final_candidate/cold0',summary_SHA256=sha(baseline/'summary.json'),new_baseline_rerun_this_round=False),
        cold_case0=dict(baseline=b,candidate=c,columns=['task','legacy_first_response_cycles','first_request_cycles','compute_cycles','private_read16','private_write16'],
            task_cycles_saved=34122,compute_cycles_saved=113664,noncompute_wait_increase_cycles=79542,
            latency_reduction_percent=100*34122/2729240,private_read_write_delta=[0,0]),
        phase_counts_baseline=old,phase_counts_candidate=new,
        declared_accelerator_register_bits_both=33003,nonconstant_MUL_AST_operators_both=144,PE_array='8x16 unchanged',math_lanes=4,
        SRAM_macros_expected_full_SoC=100,private_macros=20,private_bytes=163840,
        conditional150MHz=dict(frequency_signed_off=False,candidate_tasks_s=150000000/2695118,candidate_ms_task=2695118/150000,
            goal_tasks_s=120,goal_budget_cycles=1250000,goal_achieved=False),
        numeric_contract='INTEGER_NUMERICS_V1, S16 first input/S8 internal/W8; no arithmetic or parameter change',
        accuracy=dict(inherited_validation_samples=4445,FP_correct=4348,integer_correct=4345,drop_pp=300/4445,new_full_network_RTL_codes=76032,new_4445_RTL_or_official600_evaluation=False),
        checks=dict(actual_E203_timed_two_state_SoC=True,FPGA_SOURCE_clock_bypass=True,SRAM_contract_models=True,
            KWT_SIM_write_before_read_and_bank_ownership=True,KWT_SIM_LN_batch_source_consumer_shadow=True,
            same_object_two_cold_tasks=True,CRC_and_full_recovery=True,LN_reset_points=[4,5,6,7],gather_stall_cycles=17,held_tail_result_cycles=11),
        four_state_full_SoC_or_gate=False,area_mm2=None,power_mW=None,energy_uJ=None,physical_signoff=False,
        risks=['eight-row dynamic cache selects may increase combinational area/load/delay despite unchanged storage capacity',
               'most compute saving is absorbed by unchanged supply schedule','full-corner reset timing and vendor/gate X remain unverified'],
        owner_queue_candidate_mixed=False,interfaces_or_CPU_or_macro_binding_changed=False)
    dest.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({k:r[k] for k in ['passed','production_source_commit','cold_case0','conditional150MHz']},indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);ap.add_argument('--collect',action='store_true');a=ap.parse_args();out=a.output.resolve()
    if not a.collect:reproduce(out)
    collect(out)
