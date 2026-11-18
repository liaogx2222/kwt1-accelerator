"""Independent saved-result replay and scope-aware resident-core delivery audit."""
import argparse
import ast
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_resident_core as core
import validate_competitive_components as component
import validate_arithmetic16 as arithmetic
from integer_model.competitive_tile16 import MacroClock


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve()
    if (out/'verification.json').exists():
        # A sealed delivery is read-only: recursively validate its evidence
        # and source bindings, then independently replay both full cold tasks.
        folders=[out]+[ROOT/'testdata/resident_core_20261105'/n for n in ['references','toolchain','core_two_cold','unit_audit','model_single_acc','model_lanes8',
            'rtl_partition','rtl_structural','rtl_banked','rtl_shared','rtl_single','nangate_structural_v2','nangate_shared','nangate_single',
            'comparison','gate_staged_structural','gate_staged_shared','gate_staged_single']]
        for folder in folders:
            for file,digest in json.loads((folder/'manifest.json').read_text()).items():assert sha(folder/file)==digest,(folder,file)
            for file,digest in json.loads((folder/'source_bindings.json').read_text()).items():assert sha(ROOT/file)==digest,(folder,file)
        core.check(ROOT/'testdata/resident_core_20261105/core_two_cold');print(json.dumps(json.loads((out/'verification.json').read_text()),indent=2));return
    out.mkdir(parents=True,exist_ok=True);base=ROOT/'testdata/resident_core_20261105';bound={};counts=Counter();reports={}
    def bind(path):bound[os.path.relpath(path,ROOT).replace('\\','/')]=sha(path)
    folders=['references','toolchain','core_two_cold','unit_audit','model_single_acc','model_lanes8','rtl_partition','rtl_structural','rtl_banked','rtl_shared','rtl_single',
        'nangate_structural_v2','nangate_shared','nangate_single','comparison','gate_staged_structural','gate_staged_shared','gate_staged_single']
    for name in folders:
        folder=base/name
        for file,digest in json.loads((folder/'manifest.json').read_text()).items():assert sha(folder/file)==digest,(name,file);counts['evidence_hashes']+=1
        for file,digest in json.loads((folder/'source_bindings.json').read_text()).items():assert sha(ROOT/file)==digest,(name,file);counts['source_hashes']+=1
        bind(folder/'manifest.json');bind(folder/'source_bindings.json')
        if name not in ['references','comparison']:
            report=json.loads((folder/'verification.json').read_text());assert report.get('passed',report.get('mapping_passed',False)),name;reports[name]=report
    # The former delivery remains immutable. Only mutable navigation has a
    # byte-exact pre-edit snapshot; it never substitutes for a technical source.
    previous=ROOT/'testdata/competitive_ffn_20261105/delivery'
    for file,digest in json.loads((previous/'manifest.json').read_text()).items():assert sha(previous/file)==digest,file;counts['previous_evidence_hashes']+=1
    for file,digest in json.loads((previous/'source_bindings.json').read_text()).items():
        path=out/'previous_navigation'/Path(file).name if file in ['../docs/architecture/README.md','../docs/architecture/IMPLEMENTATION_ROADMAP.md'] else ROOT/file
        assert sha(path)==digest,file;counts['previous_source_hashes']+=1
    bind(previous/'manifest.json');bind(previous/'source_bindings.json')
    core.check(base/'core_two_cold');models=reports['core_two_cold']['cases'];assert [m['cycles'] for m in models]==[2040236,2047313]
    banks=MacroClock().mem;assert len(banks)==20 and sum(v.nbytes for v in banks.values())==65536
    assert Counter(len(v) for v in banks.values())=={1024:16,4096:4}
    codes=reports['core_two_cold']['independent_output_codes'];x,p,_=component.fixture();reference=component.reference_stages(x,p)
    for name in ['model_single_acc','model_lanes8']:
        saved=dict(np.load(base/name/'observed.npz'));actual_codes=0
        for layer in range(12):
            for op in ['q','k','v','qk','softmax','pv','o','ln1','fc1','gelu','fc2','ln2']:
                actual=saved[f'l{layer:02d}_{op}'];assert np.array_equal(actual,reference[component.expected_key(layer,op)][0]),(name,layer,op);actual_codes+=actual.size
        assert actual_codes==1451736;codes+=actual_codes
        m=reports[name]['metrics'];assert m['operations']==models[0]['operations'];assert m['register_4KiB_pass'] and m['private_SRAM_bytes']==65536
        assert (m['cycles'],m['total_register_peak_bytes'])==({'model_single_acc':(2203442,2832),'model_lanes8':(1839333,3402)}[name])
        assert m['intermediate_external_activation_bytes']==0 and m['common_load_count']==1
    for m in models:
        assert sum(m['phase_cycles'].values())==m['cycles'];assert m['total_register_peak_bytes']==3242 and m['scratch_peak_bytes']==32000
        assert m['scratch_bank_peak_bytes']==[8000]*4 and m['private_SRAM_bytes']==65536
        assert sum(r['cycles'] for r in m['phases'])+3200+1256+1600==m['cycles']
    differences={k:models[1]['phase_cycles'].get(k,0)-v for k,v in models[0]['phase_cycles'].items() if models[1]['phase_cycles'].get(k,0)!=v}
    assert len(differences)==1 and sum(differences.values())==7077 and next(iter(differences)).endswith('/exact_exp_cache_read'),differences
    # Derive a fresh golden vector set from the original integer operators,
    # then check every emitted hardware value, uniqueness and pass coverage.
    independent=out/'independent_vectors';independent.mkdir(exist_ok=True);profiles=arithmetic.vectors(independent);assert len(profiles)==96
    expected={n:[int(v,16) for v in (independent/'vectors'/f'{n}.hex').read_text().split()] for n in ['raw','rq','error']}
    scalar=0;hardware={}
    for name in ['rtl_partition','rtl_structural','rtl_banked','rtl_shared','rtl_single','gate_staged_structural','gate_staged_shared','gate_staged_single']:
        folder=base/name;r=reports[name];passes=r['passes'];seen=set();n=0
        for file in (independent/'vectors').glob('*.hex'):assert sha(file)==sha(folder/'vectors'/file.name),(name,file.name)
        for line in (folder/'observed.txt').read_text().splitlines():
            f=line.split();kind,task,tag=f[0],int(f[1]),int(f[2]);assert kind in ['RAW','RQ'] and 0<=task<passes
            assert 0<=tag<(6144 if kind=='RAW' else 6208);key=(kind,task,tag);assert key not in seen;seen.add(key)
            assert int(f[3],16)==expected['raw' if kind=='RAW' else 'rq'][tag],(name,key)
            if kind=='RQ':assert int(f[4])==expected['error'][tag]
            n+=4
        assert len(seen)==(6144+6208)*passes and n==r['independently_checked_scalar_codes'];scalar+=n;hardware[name]=n
        assert 'PASS cases=96' in r['summary'] and not r['full_encoder_RTL'];bind(folder/'observed.txt')
    assert len({sha(base/name/'observed.txt') for name in ['rtl_partition','rtl_structural','rtl_banked','rtl_shared']})==1
    library=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    areas={n:float(v) for n,v in re.findall(r'cell\s*\(\s*(\w+)\s*\)\s*\{.*?area\s*:\s*([\d.]+)',library.read_text(),re.S)};area_results={}
    for name in ['nangate_structural_v2','nangate_shared','nangate_single']:
        r=reports[name];net=json.loads((base/name/'mapped.json').read_text())['modules']['kwt_arithmetic16'];types=Counter(c['type'] for c in net['cells'].values())
        assert set(types)<=set(areas) and not any(t.startswith(('DLH','DLL')) for t in types)
        area=sum(areas[t]*n for t,n in types.items());assert abs(area-r['standard_cell_area_um2'])<1e-6
        assert sum(types.values())==r['standard_cells'];assert sum(n for t,n in types.items() if t.startswith(('DFF','SDFF')))==r['sequential_cells']
        stat=json.loads((base/name/'stat.json').read_text());assert abs(area-stat['modules']['\\kwt_arithmetic16']['area'])<.02
        assert r['register_D_pins']==r['setup_endpoints_analyzed']==r['sequential_cells'] and r['negative_setup_endpoints']==0
        assert not r['complete_STA_signoff'] and r['power'] is None and r['SRAM_macros']==0;area_results[name]=area/1e6
    assert reports['gate_staged_single']['accumulator_buffers']==1
    comparison=json.loads((base/'comparison/comparison.json').read_text());assert comparison['accuracy_hard_limit_drop_pp']==.1 and not comparison['energy_frontier_measured']
    assert [r['core_model_cycles'] for r in comparison['candidates']]==[2203442,2040236,1839333]
    assert [r['model_peak_register_bytes'] for r in comparison['candidates']]==[2832,3242,3402]
    for r in comparison['candidates']:assert r['full_SoC_area_mm2'] is r['power_mW'] is r['energy_uJ'] is None
    accuracy=component.BASE/'metrics.json';acc=json.loads(accuracy.read_text());assert acc['integer_correct']==4345 and acc['fp_correct']==4348 and acc['samples']==4445
    assert abs(100*(4348-4345)/4445-acc['accuracy_drop_pp'])<1e-12 and acc['accuracy_drop_pp']<=.1;bind(accuracy)
    policy=ROOT.parent/'docs/architecture/DESIGN_TRADEOFF_POLICY_20261105.json';pol=json.loads(policy.read_text());assert 'HARD' in pol['accuracy'] and pol['do_not_infer_power_from_area_or_clock_counts'];bind(policy)
    docroot=ROOT.parent/'docs/architecture'
    for name in ['RESIDENT_CORE_TRADEOFF_SYNTHESIS_20261105.md','README.md','IMPLEMENTATION_ROADMAP.md']:
        doc=docroot/name
        for target in re.findall(r'\]\(([^)]+)\)',doc.read_text(encoding='utf-8')):
            if target.startswith(('http:','https:','mailto:','#')):continue
            resolved=(doc.parent/target.split('#')[0].strip('<>')).resolve();assert resolved.exists() or resolved==out/'verification.json',(doc,target);counts['document_links']+=1
        bind(doc)
    pyfiles=[Path(__file__)]+[ROOT/'integer_model'/n for n in ['competitive_resident_core.py','competitive_core_tradeoff.py']]
    pyfiles += [ROOT/'scripts'/n for n in ['validate_competitive_resident_core.py','validate_core_tradeoff.py','audit_resident_core_units.py','compare_resident_tradeoffs.py','fetch_architecture_references.py','resume_arithmetic_gate_cpp.py','generate_serial_arithmetic_gate.py','capture_resident_toolchain.py']]
    for file in pyfiles:ast.parse(file.read_text());bind(file)
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT.parent/'e203_hbirdv2',text=True).strip()
    patch=subprocess.check_output(['git','diff','--numstat','--','kws_streaming/data/input_data.py'],cwd=ROOT,text=True).split();assert patch[:2]==['3','3']
    attempts={}
    for name in ['nangate_partition','nangate_structural','gate_structural','gate_verilator_structural','gate_verilator_shared','gate_serial_structural']:
        folder=base/name;logs=[f for f in folder.glob('*.log')];attempts[name]=dict(status='interrupted/failed attempt, excluded from pass counts',log_files=len(logs))
        assert not (folder/'verification.json').exists(),name
        for log in logs:bind(log)
    result=dict(passed=True,counts=dict(counts),python_sources_parsed=len(pyfiles),independent_model_stage_codes=codes,independent_hardware_scalar_codes=scalar,
        hardware_codes_by_folder=hardware,mismatches=0,whole_core_model_cycles=[2040236,2047313],model_alternative_cycles=[2203442,1839333],
        private_SRAM_bytes=65536,physical_macro_count_in_model=20,model_peak_register_bytes=[2832,3242,3402],model_budget_is_not_complete_RTL_signoff=True,
        real_compaction_cycles=1600,shared_iterative_intervals_checked=11880,task_cycle_difference_attribution=differences,
        mapped_partition_area_mm2=area_results,mapped_partition_functional_regressions=3,reference_reg2reg_only_STA=True,complete_STA_signoff=False,
        accuracy_drop_pp=acc['accuracy_drop_pp'],accuracy_hard_limit_pp=.1,other_metrics='tradeoff; examples not simultaneous pass gates',
        full_encoder_RTL=False,complete_CPU_packet_IO_model=False,full_SoC_area_mm2=None,power_mW=None,energy_uJ=None,
        CPU_repository_clean=True,user_patch_3_additions_3_deletions_preserved=True,excluded_attempts=attempts)
    (out/'verification.json').write_text(json.dumps(result,indent=2));(out/'source_bindings.json').write_text(json.dumps(bound,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and p.name!='manifest.json'},indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
