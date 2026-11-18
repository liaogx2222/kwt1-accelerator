"""Close new resident/pipeline evidence without rewriting previous releases."""
import argparse
import ast
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from local_tools import ROOT,sha
import validate_competitive_resident_attention as attention
import validate_competitive_norm_pipeline as norm
import validate_competitive_hybrid as hybrid


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();out=args.output.resolve();assert not (out/'verification.json').exists();out.mkdir(parents=True,exist_ok=True)
    base=ROOT/'testdata/competitive_resident_20261104';names=['smoke','all16','softmax_smoke','softmax_all16','norm_smoke','norm_all28','hybrid12','iterative_audit']
    evidence=sources=0;bindings={};reports={}
    for name in names:
        folder=base/name
        for f,digest in json.loads((folder/'manifest.json').read_text()).items():assert sha(folder/f)==digest,(name,f);evidence+=1
        for f,digest in json.loads((folder/'source_bindings.json').read_text()).items():assert sha(ROOT/f)==digest,(name,f);sources+=1
        reports[name]=json.loads((folder/'verification.json').read_text());assert reports[name]['passed']
        bindings[(folder/'manifest.json').relative_to(ROOT).as_posix()]=sha(folder/'manifest.json')
    previous=ROOT/'testdata/competitive_tile16_20261104/delivery'
    for f,digest in json.loads((previous/'manifest.json').read_text()).items():assert sha(previous/f)==digest; evidence+=1
    for f,digest in json.loads((previous/'source_bindings.json').read_text()).items():
        path=ROOT/f
        if f in ['../docs/architecture/README.md','../docs/architecture/IMPLEMENTATION_ROADMAP.md']:path=out/'previous_navigation'/Path(f).name
        assert sha(path)==digest,f;sources+=1
    bindings[(previous/'manifest.json').relative_to(ROOT).as_posix()]=sha(previous/'manifest.json')
    attention.check(base/'all16');attention.check(base/'softmax_all16');norm.check(base/'norm_all28');hybrid.check(base/'hybrid12')
    interval_count=0
    for case in reports['iterative_audit']['cases']:
        intervals=case['intervals'];interval_count+=len(intervals)
        assert all(row['end']-row['start']==(32 if row['unit']=='sqrt' else 64) for row in intervals)
        assert all(a['end']<=b['start'] for a,b in zip(intervals,intervals[1:]))
    assert interval_count==495
    serial=reports['all16']['cases'];pipelined=reports['softmax_all16']['cases']
    for a,b in zip(serial,pipelined):
        assert a['name']==b['name']
        for mode in ['resident','materialized']:
            assert a[mode]['cycles']-b[mode]['cycles']==6174
            assert a[mode]['operations']==b[mode]['operations']
            for field in ['SRAM_reads','SRAM_writes','scratch_peak_bytes']:assert a[mode][field]==b[mode][field]
            assert b[mode]['extra_arithmetic_units']==0
    norms=reports['norm_all28']['cases']
    assert all(r['serial']['cycles']-r['pipeline']['cycles']==7595 for r in norms)
    old=json.loads((ROOT/'testdata/competitive_tile16_20261104/connected_materialized/verification.json').read_text())
    current=reports['hybrid12'];assert current['model_cycles']==2901700
    attention_sum=sum(r['resident']['cycles'] for r in pipelined if r['name'].startswith('l'))
    assert attention_sum==930592 and old['aggregate']['standalone_cycle_sum_including_repeated_common']==3534948
    assert 3534948-current['model_cycles']==(1381560-attention_sum)+24*7595
    def tags(rows):
        result=Counter()
        for row in rows:
            for name,value in row['phase_cycles'].items():result[name.split('/')[-1]]+=value
        return result
    old_tags=tags([r for r in old['cases'] if r['operation'] in ['qk','softmax','pv']])
    new_tags=tags([r['materialized'] for r in serial if r['name'].startswith('l')])
    merge=dict(common_cache=old_tags['compressed_exp_32bit_beat']-new_tags['compressed_exp_32bit_beat'],
        coefficient_load=old_tags['shared_coefficient_32bit_word']-new_tags['shared_coefficient_32bit_word'],
        additional_retained_branch_input=old_tags['host_tensor_32bit_beat']-new_tags['host_tensor_32bit_beat'],
        additional_scalar_parameter_load=old_tags['parameter_32bit_load']-new_tags['parameter_32bit_load'],
        additional_per_query_RQ_drain=old_tags['PV_RQ_drain']-new_tags['resident_query_RQ_drain'])
    assert merge==dict(common_cache=30144,coefficient_load=16128,additional_retained_branch_input=-20800,additional_scalar_parameter_load=-24,additional_per_query_RQ_drain=-4968)
    assert sum(merge.values())==20480
    docroot=ROOT.parent/'docs/architecture';links=0
    for filename in ['RESIDENT_ATTENTION_AND_NL_PIPELINE_20261104.md','README.md','IMPLEMENTATION_ROADMAP.md']:
        doc=docroot/filename
        for target in re.findall(r'\]\(([^)]+)\)',doc.read_text(encoding='utf-8')):
            if target.startswith(('http:','https:','mailto:','#')):continue
            resolved=(doc.parent/target.split('#')[0].strip('<>')).resolve()
            assert resolved.exists() or resolved==out/'verification.json',(doc,target);links+=1
        bindings['../docs/architecture/'+filename]=sha(doc)
    pyfiles=[ROOT/'integer_model'/n for n in ['competitive_resident_attention.py','competitive_softmax_pipeline.py','competitive_norm_pipeline.py']]+[ROOT/'scripts'/n for n in ['validate_competitive_resident_attention.py','validate_competitive_softmax_pipeline.py','validate_competitive_norm_pipeline.py','validate_competitive_hybrid.py','audit_competitive_iterative.py','check_competitive_resident_delivery.py']]
    for file in pyfiles:ast.parse(file.read_text());bindings[file.relative_to(ROOT).as_posix()]=sha(file)
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT.parent/'e203_hbirdv2',text=True).strip()
    diff=subprocess.check_output(['git','diff','--numstat','--','kws_streaming/data/input_data.py'],cwd=ROOT,text=True).split();assert diff[:2]==['3','3']
    independent=sum(reports[n]['independent_output_codes'] for n in ['all16','softmax_all16','norm_all28','hybrid12'])
    result=dict(passed=True,evidence_hashes_checked=evidence,source_hashes_checked=sources,python_sources_parsed=len(pyfiles),document_links_checked=links,
        independent_replayed_output_codes=independent,mismatches=0,
        paired_intermediate_materialization_saving_per_case=29700,two_row_Softmax_saving_per_case=6174,two_row_LN_saving_per_case=7595,
        hybrid12_cycles=current['model_cycles'],previous_materialized12_cycles=3534948,
        cycle_reduction_percent=100*(1-current['model_cycles']/3534948),attention12_cycles=attention_sum,
        cache_and_phase_merge_cycle_delta=merge,
        max_register_peak_bytes=current['max_register_peak_bytes'],max_scratch_peak_bytes=current['max_scratch_peak_bytes'],
        external_activation_peak_bytes=current['external_activation_peak_bytes'],extra_arithmetic_units=0,shared_iterative_intervals_checked=interval_count,shared_iterative_overlaps=0,
        CPU_repo_clean=True,user_patch_3_additions_3_deletions_preserved=True,
        full_encoder_resident=False,new_RTL=False,all_competition_targets_met=False)
    (out/'verification.json').write_text(json.dumps(result,indent=2));(out/'source_bindings.json').write_text(json.dumps(bindings,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and p.name!='manifest.json'},indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
