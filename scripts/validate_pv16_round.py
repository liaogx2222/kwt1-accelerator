"""Reproduce or strictly collect the full, source-bound PV16 local campaign.

Run from this worktree. --collect never launches a simulator or edits inputs.
Commercial synthesis, vendor/gate simulation and PPA are deliberately separate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REV = 'bc364d068c3f9d73b340a33136a998fd4ecdd05b'
PARENT_REV = '120316fe907a850c3f81939ed178fcb177af1449'
CORE = 'rtl/v2/kwt_layer_banked.sv'
BENCH = 'flow/tb_soc_metrics.sv'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def load(p):
    return json.loads(p.read_text())

def run(script, *args):
    subprocess.run([sys.executable, str(ROOT/'scripts'/script), *map(str, args)], cwd=ROOT, check=True)

def reproduce(out):
    assert not out.exists(), 'use a fresh output directory; never overwrite evidence'
    bp, cp = [out/n/'project' for n in ['final_baseline', 'final_candidate']]
    for project, variant in [(bp, 'baseline'), (cp, 'pv16')]:
        run('prepare_pv16_local.py', '--variant', variant, '--output', project)
        run('check_pv16_soc.py', '--project', project, '--output', project.parent/'cold0', '--cases', '0', '--jobs', 1)
    base_model = bp.parent/'cold0/model/sim.exe'
    model = cp.parent/'cold0/model/sim.exe'
    jobs = [('full12', ['--cases', ','.join(map(str, range(12))), '--jobs', '4']),
            ('consecutive', ['--tasks', '2']), ('crc_recovery', ['--crc']),
            ('pv_mid_reset', ['--recovery', '--reset-point', '1']),
            ('pv_tail_reset', ['--recovery', '--reset-point', '2']),
            ('pv_rq_reset', ['--recovery', '--reset-point', '3']),
            ('stall_observed/run', ['--stall'])]
    for name, flags in jobs:
        run('check_pv16_soc.py', '--project', cp, '--model', model, '--output', out/name, *flags)
    run('check_pv16_soc.py', '--project', bp, '--model', base_model, '--output', out/'baseline_consecutive', '--tasks', '2')
    run('check_pv16_mac.py', '--project', cp, '--output', out/'mac_four_state_v2')
    run('check_pv16_consumers.py', '--project', cp, '--output', out/'consumer_boundaries_v2')
    run('prove_pv16_single_pass.py', '--output', out/'software_proof')
    for project, name in [(bp, 'baseline_inventory'), (cp, 'candidate_inventory')]:
        run('inventory_pv16.py', '--project', project, '--output', out/name)

def collect(out):
    dest = out/'release_summary.json'
    assert not dest.exists(), 'preserve existing summary'
    bp, cp = [out/n/'project' for n in ['final_baseline', 'final_candidate']]
    bm, cm = [load(p/'source_manifest.json') for p in [bp, cp]]
    for project, manifest in [(bp, bm), (cp, cm)]:
        assert len(manifest['files']) == 194
        assert {n: sha(project/n) for n in manifest['files']} == manifest['files'], 'source drift'
    assert bm['files'].keys() == cm['files'].keys()
    assert [n for n in bm['files'] if bm['files'][n] != cm['files'][n]] == [CORE]
    blob = subprocess.check_output(['git', 'show', SOURCE_REV+':rtl/pv16_opt/kwt_layer_banked.sv'], cwd=ROOT)
    assert hashlib.sha256(blob).hexdigest() == cm['files'][CORE] == sha(ROOT/'rtl/pv16_opt/kwt_layer_banked.sv')
    evidence = {}
    def soc(name, variant, tasks=1, cases=(0,), recovery=False, point=0, crc=False, stall=False):
        folder = out/name
        s = load(folder/'summary.json')
        assert s['passed'] and s['variant'] == variant and s['two_state'] and s['timed_SV']
        expected = bm if variant == 'baseline' else cm
        files = s['source_bindings']['files']
        assert files.keys() == expected['files'].keys()
        # A corrected force/release testbench is allowed; every production
        # source/firmware/fixture/contract binding must still be identical.
        assert all(files[n] == expected['files'][n] for n in files if n != BENCH)
        assert s['total_codes'] == len(cases)*tasks*6336
        assert [r['case'] for r in s['cases']] == list(cases)
        for r in s['cases']:
            assert r['passed'] and r['tasks'] == tasks and r['recovery'] == recovery
            assert r['reset_point'] == point and r['CRC_rejection_full_recovery'] == crc and r['PV_stalls'] == stall
            d = folder/('case_%02d'%r['case'])
            assert sha(d/'run.log') == r['log_sha256']
            command = load(d/'command.json')
            exe = Path(command[0])
            assert sha(exe) == s['model_sha256'], 'model changed after simulation'
            assert load(exe.parent/'sources.json') == s['source_bindings'], 'model/source receipt mismatch'
            log = (d/'run.log').read_text()
            assert log.count('params=189328 input_words=3168 output_words=1584 host_words=192508') == tasks
            for i in range(tasks):
                assert (d/('matrix_task_%02d.hex'%i)).read_text().split() == (cp/('fixtures/expected_%03d.hex'%r['case'])).read_text().split()
            if recovery: assert 'SOC_GATE_RESET_IN_FLIGHT point=%d'%point in log
            if crc: assert 'PASS LOCAL_PREFETCH_CRC_REJECT params=65872 packets=5 outputs=0' in log
            if stall: assert 'PASS LOCAL_PV_STALL mac_cycles=17 held_requant_cycles=11' in log
        evidence[name] = dict(summary_sha256=sha(folder/'summary.json'), model_sha256=s['model_sha256'],
                              bench_sha256=files[BENCH], codes=s['total_codes'], cases=s['cases'])
        return s
    b = soc('final_baseline/cold0', 'baseline')['cases'][0]['profiles'][0]
    c = soc('final_candidate/cold0', 'pv16')['cases'][0]['profiles'][0]
    full = soc('full12', 'pv16', cases=tuple(range(12)))
    bw = soc('baseline_consecutive', 'baseline', tasks=2)
    cw = soc('consecutive', 'pv16', tasks=2)
    soc('crc_recovery', 'pv16', crc=True)
    for name, point in [('pv_mid_reset',1), ('pv_tail_reset',2), ('pv_rq_reset',3)]:
        soc(name, 'pv16', recovery=True, point=point)
    soc('stall_observed/run', 'pv16', stall=True)
    assert b == [0,2783869,2783874,2204544,8109616,1239000]
    assert c == [0,2729235,2729240,2140896,7615408,1239000]
    assert all(r['profiles'][0][1:4] == c[1:4] for r in full['cases'])
    assert bw['cases'][0]['profiles'][1] == [1,2783860,2783863,2204544,8109616,1239000]
    assert cw['cases'][0]['profiles'][1] == [1,2729226,2729229,2140896,7615408,1239000]
    def phases(name):
        return {int(k):int(v) for k,v in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)', (out/name/'case_00/run.log').read_text())}
    old, new = phases('final_baseline/cold0'), phases('final_candidate/cold0')
    assert {k for k in old if old[k] != new[k]} == {27,28,29,30}
    assert all(old[k] == 2*new[k] for k in [27,28,29,30])
    assert sum(old.values())-sum(new.values()) == 63648
    iv = load(out/'mac_four_state_v2/summary.json')
    assert iv['passed'] and iv['four_state'] and 'checks=4030464 stalls=6144 inflight_resets=16' in iv['result']
    for name, h in iv['source_sha256'].items(): assert sha(Path(name)) == h
    assert cm['files']['rtl/v2/kwt_mac_array.sv'] in iv['source_sha256'].values()
    consumers=load(out/'consumer_boundaries_v2/summary.json')
    assert consumers['passed'] and consumers['four_state']
    assert consumers['math_results']==4152 and consumers['iterative_vectors']==821
    assert consumers['actual_SHORT_CONST_DIV']==1 and consumers['actual_RADIX4_CONST']==1
    for name,h in consumers['source_sha256'].items(): assert sha(Path(name))==h
    for name in ['rtl/micro/mul_pipe.sv','rtl/micro/rne_pipe.sv','rtl/v2/kwt_math.sv','rtl/v2/kwt_iterative.sv']:
        assert cm['files'][name] in consumers['source_sha256'].values()
    proof_path = out/'software_proof/proof.json'
    if not proof_path.exists(): proof_path = ROOT/'testdata/sysbus_contract_20261113/pv16_feasibility/proof.json'
    proof = load(proof_path)
    assert proof['passed'] and proof['exhaustive_product_pairs'] == 16777216 and proof['full_tile_outputs'] == 524288
    inv_b, inv_c = [load(out/n/'summary.json') for n in ['baseline_inventory','candidate_inventory']]
    for inv, manifest in [(inv_b,bm), (inv_c,cm)]:
        assert inv['passed'] and inv['private_SRAM_macros'] == 20
        assert inv['multiplier_operator_instances'] == 144
        assert all(h == manifest['files'][n] for n,h in inv['source_sha256'].items())
    assert inv_b['declared_register_bits'] == 33004 and inv_c['declared_register_bits'] == 33003
    versions = {}
    for label, cmd in [('python',[sys.executable,'--version']),
                       ('verilator',[ROOT.parent/'keyword-transformer/tools/rtl_v1_python/verilator/bin/verilator_bin.exe','--version']),
                       ('zig',[ROOT.parent/'keyword-transformer/tools/rtl_v1_python/ziglang/zig.exe','version']),
                       ('iverilog',[Path('C:/iverilog/bin/iverilog.exe'),'-V'])]:
        p = subprocess.run(list(map(str,cmd)),capture_output=True,text=True)
        versions[label] = dict(returncode=p.returncode,output=p.stdout+p.stderr)
    (out/'tool_versions.json').write_text(json.dumps(versions,indent=2)+'\n')
    result = dict(passed=True,branch='codex/pv16-opt-20261113',parent_commit=PARENT_REV,production_source_commit=SOURCE_REV,
        SYSBUS_integration_parent='2cf2dfa',S16_arithmetic_parent='595724b88858b142a407f6a5c4761945252d523b',
        changed_production_files=[CORE],production_SHA256=cm['files'][CORE],evidence=evidence,
        software_proof_SHA256=sha(proof_path),PE_four_state_summary_SHA256=sha(out/'mac_four_state_v2/summary.json'),
        consumer_boundary_summary_SHA256=sha(out/'consumer_boundaries_v2/summary.json'),
        cold_task_case0=dict(baseline=b,candidate=c,columns=['task_index','legacy_first_response_cycles','first_request_cycles','compute_cycles','private_read16','private_write16'],
            cycles_saved=b[2]-c[2],compute_cycles_saved=b[3]-c[3],private_read16_saved=b[4]-c[4],private_write16_delta=c[5]-b[5],
            latency_reduction_percent=100*(b[2]-c[2])/b[2],noncompute_wait_increase_cycles=(c[2]-c[3])-(b[2]-b[3])),
        phase_counts_baseline=old,phase_counts_candidate=new,
        conditional_150MHz=dict(frequency_is_signed_off=False,baseline_tasks_s=150000000/b[2],candidate_tasks_s=150000000/c[2],
            candidate_ms_task=c[2]/150000,goal_tasks_s=120,goal_budget_cycles=1250000,goal_achieved=False),
        declared_accelerator_register_bits=dict(baseline=33004,candidate=33003,delta=-1,bytes_ceiling_both=4126),
        arithmetic_resources=dict(PE_array='8x16 unchanged',math_lanes=4,nonconstant_MUL_AST_operators_both=144,
            SRAM_macros_expected_full_SoC=100,private_macros=20,private_bytes=163840,shared_macros=64,TCM_macros=16),
        accuracy=dict(inherited_S16_validation_samples=4445,FP_correct=4348,integer_correct=4345,drop_pp=0.06749156355455568,
            new_full_network_RTL_codes=76032,new_4445_RTL_or_official600_accuracy_evaluation=False,numeric_or_parameters_changed=False),
        scope=dict(full_SoC='timed two-state RTL, FPGA_SOURCE clock bypass and SRAM contract models',
            four_state='PE and unchanged math/iterative units only; not full SoC or gate',vendor_libraries=False,STA=False,
            area_mm2=None,power_mW=None,energy_uJ=None,physical_signoff=False),
        known_failed_attempts=['mac_four_state/tool_discovery_failure.log','pv_stall/case_00/run.log: force/release testbench timeout',
            'consumer_boundaries/compile.log: first native compile returned nonzero with empty output, no numerical verdict'],
        diagnostic_note='stall_fixed completed normally and passed; later attempted process lookup found it already absent, so no process was terminated',
        server_needed=['resynthesize changed accelerator and relink complete SYSBUS SoC','all-corner setup/hold/recovery/removal plus untested paths',
            'four-state vendor SRAM RET1N and mapped reset/backpressure/recovery','same-configuration full SoC area, task activity, power and energy'])
    dest.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['passed','production_source_commit','cold_task_case0','conditional_150MHz']},indent=2))

if __name__ == '__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);ap.add_argument('--collect',action='store_true');a=ap.parse_args()
    output=a.output.resolve()
    if not a.collect: reproduce(output)
    collect(output)
