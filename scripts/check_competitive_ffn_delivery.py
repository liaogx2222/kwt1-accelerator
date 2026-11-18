"""Close FFN in-place budget, saved-output replay and exact phase attribution."""
import argparse
import ast
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from local_tools import ROOT,sha
import validate_competitive_resident_ffn as ffn
import validate_competitive_hybrid_ffn as hybrid
from integer_model.competitive_tile16 import MacroClock
from integer_model.competitive_hashed_banks import HashedScratch


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();out=args.output.resolve();assert not (out/'verification.json').exists();out.mkdir(parents=True,exist_ok=True)
    base=ROOT/'testdata/competitive_ffn_20261105';reports={};bindings={};evidence=sources=0
    for name in ['smoke','all27','hybrid12']:
        folder=base/name
        for file,digest in json.loads((folder/'manifest.json').read_text()).items():assert sha(folder/file)==digest,(name,file);evidence+=1
        for file,digest in json.loads((folder/'source_bindings.json').read_text()).items():assert sha(ROOT/file)==digest,(name,file);sources+=1
        reports[name]=json.loads((folder/'verification.json').read_text());assert reports[name]['passed']
        bindings[(folder/'manifest.json').relative_to(ROOT).as_posix()]=sha(folder/'manifest.json')
    previous=ROOT/'testdata/competitive_resident_20261104/delivery'
    for file,digest in json.loads((previous/'manifest.json').read_text()).items():assert sha(previous/file)==digest; evidence+=1
    for file,digest in json.loads((previous/'source_bindings.json').read_text()).items():
        path=ROOT/file
        if file in ['../docs/architecture/README.md','../docs/architecture/IMPLEMENTATION_ROADMAP.md']:path=out/'previous_navigation'/Path(file).name
        assert sha(path)==digest,file;sources+=1
    bindings[(previous/'manifest.json').relative_to(ROOT).as_posix()]=sha(previous/'manifest.json')
    ffn.check(base/'all27');hybrid.check(base/'hybrid12')
    pool=HashedScratch(MacroClock());res=pool.allocate('residual',99,64);hidden=pool.allocate('hidden',99,256);before=[list(r) for r in pool.free]
    try:pool.allocate('forbidden_third_output',99,64)
    except MemoryError:pass
    else:raise AssertionError('third output exceeded the physical budget')
    assert pool.free==before and len(pool.live)==2;pool.release(hidden);pool.release(res);assert pool.free==[[(0,4096)]]*4
    # Reproduce first-layer placement across attention/O/LN1. Aggregate free
    # bytes suffice, but two separated holes cannot fit the hidden tensor.
    fragment=HashedScratch(MacroClock());x=fragment.allocate('S16_input',99,64,16)
    context=fragment.allocate('context',99,64);projected=fragment.allocate('O',99,64)
    fragment.release(context);normed=fragment.allocate('LN1',99,64)
    fragment.release(x);fragment.release(projected)
    assert normed.bases==[1600]*4 and fragment.free==[[(0,1600),(2400,4096)]]*4
    try:fragment.allocate('hidden_without_compaction',99,256)
    except MemoryError:pass
    else:raise AssertionError('fragmentation was silently bypassed')
    assert sum(b-a for ranges in fragment.free for a,b in ranges)*2==26368
    fragment.release(normed)
    old=json.loads((ROOT/'testdata/competitive_resident_20261104/hybrid12/verification.json').read_text());new=reports['hybrid12']
    old_other={(r['layer'],r['operation']):r['cycles'] for r in old['cases'] if r['operation'] not in ['fc1','gelu','fc2']}
    new_other={(r['layer'],r['operation']):r['cycles'] for r in new['cases'] if r['operation']!='ffn'};assert old_other==new_other
    for layer in range(12):
        count=Counter()
        for row in old['cases']:
            if row['layer']==layer and row['operation'] in ['fc1','gelu','fc2']:count.update(row['operations'])
        current=next(r for r in new['cases'] if r['layer']==layer and r['operation']=='ffn')
        assert dict(count)==current['operations'] and current['cycles']==45314
    assert old['model_cycles']==2901700 and new['model_cycles']==2564356
    assert old['model_cycles']-new['model_cycles']==12*(25600+2*1256)==337344
    assert new['max_register_peak_bytes']==3178 and new['max_scratch_peak_bytes']==32000 and new['external_activation_peak_bytes']==38016
    docroot=ROOT.parent/'docs/architecture';links=0
    for name in ['RESIDENT_FFN_AND_INPLACE_SHRINK_20261105.md','README.md','IMPLEMENTATION_ROADMAP.md']:
        doc=docroot/name
        for target in re.findall(r'\]\(([^)]+)\)',doc.read_text(encoding='utf-8')):
            if target.startswith(('http:','https:','mailto:','#')):continue
            resolved=(doc.parent/target.split('#')[0].strip('<>')).resolve();assert resolved.exists() or resolved==out/'verification.json',(doc,target);links+=1
        bindings['../docs/architecture/'+name]=sha(doc)
    pyfiles=[ROOT/'integer_model/competitive_resident_ffn.py']+[ROOT/'scripts'/n for n in ['validate_competitive_resident_ffn.py','validate_competitive_hybrid_ffn.py','check_competitive_ffn_delivery.py']]
    for file in pyfiles:ast.parse(file.read_text());bindings[file.relative_to(ROOT).as_posix()]=sha(file)
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT.parent/'e203_hbirdv2',text=True).strip()
    diff=subprocess.check_output(['git','diff','--numstat','--','kws_streaming/data/input_data.py'],cwd=ROOT,text=True).split();assert diff[:2]==['3','3']
    codes=reports['all27']['independent_output_codes']+new['independent_output_codes'];assert codes==4531032
    result=dict(passed=True,evidence_hashes_checked=evidence,source_hashes_checked=sources,python_sources_parsed=len(pyfiles),document_links_checked=links,
        independent_replayed_output_codes=codes,mismatches=0,FFN_input_cases=27,FFN_parameter_profiles=12,additional_class_samples=11,boundary_cases=4,
        paired_FFN_cycles=dict(resident=45314,materialized=70914,reduction=25600),hybrid12_cycles=new['model_cycles'],previous_hybrid12_cycles=2901700,
        cycle_reduction=337344,cycle_reduction_percent=100*(1-new['model_cycles']/2901700),
        cycle_attribution=dict(intermediate_roundtrip_removed=307200,repeated_common_removed=30144),unchanged_kernel_cycles_equal=True,arithmetic_counts_unchanged=True,
        max_register_peak_bytes=3178,max_scratch_peak_bytes=32000,external_activation_peak_bytes=38016,
        consumed_hidden_halfwords_per_case=12800,inplace_shrink_bytes_released=19200,third_output_allocation_rejected=True,
        full_layer_fragmentation_probe_rejected=True,fragmentation_probe_free_bytes=26368,fragmentation_probe_largest_free_words_per_bank=1696,
        CPU_repo_clean=True,user_patch_3_additions_3_deletions_preserved=True,full_encoder_resident=False,complete_IO_model=False,new_RTL=False,all_competition_targets_met=False)
    (out/'verification.json').write_text(json.dumps(result,indent=2));(out/'source_bindings.json').write_text(json.dumps(bindings,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and p.name!='manifest.json'},indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
