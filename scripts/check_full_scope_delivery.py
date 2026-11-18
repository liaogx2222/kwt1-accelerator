"""Independent output, schedule, SRAM and complete-metric scope checks."""
import argparse
import ast
import csv
import io
import json
import os
import re
import subprocess
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
import validate_competitive_resident_core as original


FOLDERS=['fusion_screen_v2','window_derivation','window32_screen','window64_screen','window128_screen','core_ln_fused','core_window128_ln','sram_cacti','metered_dual','metered_single','metrics']


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();base=ROOT/'testdata/full_scope_20261105';bound={};evidence=sources=0
    def bind(path):bound[os.path.relpath(path,ROOT).replace('\\','/')]=sha(path)
    def check(folder):
        nonlocal evidence,sources
        for f,h in json.loads((folder/'manifest.json').read_text()).items():assert sha(folder/f)==h,(folder.name,f);evidence+=1
        for f,h in json.loads((folder/'source_bindings.json').read_text()).items():assert sha(ROOT/f)==h,(folder.name,f);sources+=1
    if (out/'verification.json').exists():
        check(out)
        for name in FOLDERS:check(base/name)
        print((out/'verification.json').read_text());return
    out.mkdir(parents=True,exist_ok=True);reports={}
    for name in FOLDERS:
        check(base/name);r=json.loads((base/name/'verification.json').read_text());assert r['passed'];reports[name]=r;bind(base/name/'manifest.json');bind(base/name/'source_bindings.json')
    previous=ROOT/'testdata/resident_core_20261105/delivery'
    for f,h in json.loads((previous/'manifest.json').read_text()).items():assert sha(previous/f)==h; evidence+=1
    for f,h in json.loads((previous/'source_bindings.json').read_text()).items():
        p=out/'previous_navigation'/Path(f).name if f in ['../docs/architecture/README.md','../docs/architecture/IMPLEMENTATION_ROADMAP.md'] else ROOT/f
        assert sha(p)==h,f;sources+=1
    bind(previous/'manifest.json');bind(previous/'source_bindings.json')
    x,indices=original.inputs(12);p=dict(np.load(component.BASE/'run/params/parameters.npz'));ref0=component.reference_stages(x[:1],p);codes=0
    def replay(saved,ref):
        count=0
        for layer in range(12):
            for op in ['q','k','v','qk','softmax','pv','o','ln1','fc1','gelu','fc2','ln2']:
                v=saved[f'l{layer:02d}_{op}'];assert np.array_equal(v,ref[component.expected_key(layer,op)][0]);count+=v.size
        assert count==1451736;return count
    old=json.loads((ROOT/'testdata/resident_core_20261105/core_two_cold/verification.json').read_text())['cases']
    expected_requests=json.loads((ROOT/'testdata/resident_core_20261105/unit_audit/verification.json').read_text())['unit_requests']
    for name in ['core_ln_fused','core_window128_ln']:
        r=reports[name];codes+=replay(dict(np.load(base/name/'observed.npz')),ref0);assert r['metrics']['operations']==old[0]['operations']
    assert reports['core_ln_fused']['metrics']['cycles']==2039060 and reports['core_window128_ln']['metrics']['cycles']==2023616
    for name in ['metered_dual','metered_single']:
        r=reports[name]
        for i,m in enumerate(r['cases']):
            ref=ref0 if m['label']==0 else component.reference_stages(x[m['label']:m['label']+1],p)
            codes+=replay(dict(np.load(base/name/f'class{m["label"]:02d}_observed.npz')),ref)
            assert sum(m['phase_cycles'].values())==m['cycles'];assert sum(v['cycles'] for v in m['phases'])+3200+1256+1600==m['cycles']
            assert m['transfers']==[dict(label='final_task_writeback',cycles=1600,halfwords=3200,logical_bytes=6336)]
            assert m['compactions']==[dict(layer=0,cycles=1600,halfwords=3200,source_bases=[1600]*4,dest_bases=[0]*4)]
            assert m['operations']==old[0]['operations'] and m['total_register_peak_bytes']<=4096 and m['intermediate_external_activation_bytes']==0
            assert m['unit_requests']==expected_requests
            assert len(m['bank_accesses'])==20 and sum(v['r'] for v in m['bank_accesses'].values())==m['SRAM_reads'] and sum(v['w'] for v in m['bank_accesses'].values())==m['SRAM_writes']
            intervals=m['iterative_intervals'];assert len(intervals)==5940 and all(a['end']<=b['start'] for a,b in zip(intervals,intervals[1:]))
            if name=='metered_dual':assert old[i]['cycles']-m['cycles']==16620 and m['SRAM_reads']==old[i]['SRAM_reads'] and m['SRAM_writes']==old[i]['SRAM_writes']
        assert r['same_model_object'] and r['explicit_model_cold_reset_between_tasks']
    assert reports['metered_single']['cases'][0]['cycles']==2186822 and reports['metered_single']['cases'][0]['total_register_peak_bytes']==3142
    for name in ['fusion_screen_v2','window32_screen','window64_screen','window128_screen']:
        saved=dict(np.load(base/name/'observed.npz'))
        for key,v in saved.items():
            op=key.split('_')[-1];assert np.array_equal(v,ref0[component.expected_key(0,op)][0]);codes+=v.size
    screen=reports['fusion_screen_v2']['cases'];get=lambda mode,op:next(r for r in screen if r['fusion']==mode and r['operation']==op)
    assert get('softmax','softmax')['cycles']>get('none','softmax')['cycles']
    assert all(r['total_register_peak_bytes']<=4096 for name in ['window32_screen','window64_screen','window128_screen'] for r in reports[name]['cases'])
    sram=reports['sram_cacti'];values={}
    for depth in [128,1024,4096]:
        folder=base/'sram_cacti'/f'{depth}x16';rows=list(csv.reader(io.StringIO((folder/'cacti.cfg.out').read_text())));v=[a.strip() for a in rows[-1]];cfg=(folder/'cacti.cfg').read_text()
        assert '-cache type "ram"' in cfg and '-Add ECC - "false"' in cfg and '-read-write port 1' in cfg and '-operating temperature (K) 300' in cfg
        m=sram['models'][f'{depth}x16'];assert (float(v[10]),float(v[7]),float(v[8]),float(v[9]))==(m['area_mm2'],m['read_energy_nJ'],m['write_energy_nJ'],m['leakage_mW']);values[depth]=m
    area=16*values[1024]['area_mm2']+4*values[4096]['area_mm2'];assert abs(area-.2573684)<1e-12
    metrics=json.loads((base/'metrics/metrics.json').read_text(encoding='utf-8'));assert not metrics['complete_scoring_PPA_available'];assert metrics['accuracy']['drop_pp']<=.1
    for row in metrics['candidates']:
        assert all(row[k] is None for k in ['throughput_tasks_per_second','SoC_average_power_mW','complete_counted_area_mm2','SoC_energy_uJ_per_task'])
        assert row['missing_for_complete_area'] and row['missing_for_complete_power'] and row['missing_for_complete_throughput']
        assert row['component_estimates']['subtotal_is_not_complete_area'] and row['fixed_platform_area']['excluded_from_scoring_budget']
        expected=reports['metered_single' if row['candidate']=='compact' else 'metered_dual']['cases'];sec=sum(m['cycles'] for m in expected)/150000000
        energy_nJ=sum(c['r']*values[4096 if bank.startswith('S') else 1024]['read_energy_nJ']+c['w']*values[4096 if bank.startswith('S') else 1024]['write_energy_nJ'] for m in expected for bank,c in m['bank_accesses'].items())
        assert abs(energy_nJ*1e-6/sec-row['component_estimates']['private_SRAM_dynamic_mW'])<1e-12
    docroot=ROOT.parent/'docs/architecture';links=0
    for name in ['FULL_SCOPE_PPA_AND_SCHEDULING_20261105.md','README.md','IMPLEMENTATION_ROADMAP.md']:
        doc=docroot/name
        for target in re.findall(r'\]\(([^)]+)\)',doc.read_text(encoding='utf-8')):
            if target.startswith(('http:','https:','mailto:','#')):continue
            dest=(doc.parent/target.split('#')[0].strip('<>')).resolve();assert dest.exists() or dest==out/'verification.json',(name,target);links+=1
        bind(doc)
    files=[Path(__file__)]+[ROOT/'scripts'/n for n in ['validate_fused_rows.py','prepare_graph_windows.py','validate_graph_windows.py','validate_full_scope_core.py','model_reference_srams.py','build_full_scope_metrics.py']]+[ROOT/'integer_model'/n for n in ['competitive_fused_rows.py','competitive_graph_windows.py']]
    for path in files:ast.parse(path.read_text());bind(path)
    for path in (ROOT/'third_party/cacti_reference/tech_params').glob('*.dat'):bind(path)
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT.parent/'e203_hbirdv2',text=True).strip()
    patch=subprocess.check_output(['git','diff','--numstat','--','kws_streaming/data/input_data.py'],cwd=ROOT,text=True).split();assert patch[:2]==['3','3']
    result=dict(passed=True,evidence_hashes=evidence,source_hashes=sources,document_links=links,python_sources=len(files),independent_saved_stage_codes=codes,mismatches=0,
        cycle_end_includes_final_1600_writeback=True,scalar_operations_unchanged=True,private_SRAM_access_counts_unchanged=True,shared_iterative_intervals_checked=3*5940,
        balanced_cycles=[m['cycles'] for m in reports['metered_dual']['cases']],compact_cycles=2186822,model_peak_register_bytes=dict(compact=3142,balanced=3242),
        private_SRAM_analytical_area_mm2=area,required_full_metrics_reported=True,missing_metrics_not_zero=True,complete_scoring_area_not_claimed=True,
        full_SoC_power_measured=False,new_RTL=False,complete_CPU_packet_IO=False,CPU_repository_clean=True,user_patch_preserved=True)
    (out/'verification.json').write_text(json.dumps(result,indent=2));(out/'source_bindings.json').write_text(json.dumps(bound,indent=2));(out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and p.name!='manifest.json'},indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
