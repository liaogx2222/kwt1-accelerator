"""Evidence/source/doc checks for this isolated architecture-model iteration."""
import argparse
import ast
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from local_tools import ROOT,sha
import validate_competitive_components as components
import validate_competitive_connected as connected


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();out=args.output.resolve();assert not (out/'verification.json').exists();out.mkdir(parents=True,exist_ok=True)
    base=ROOT/'testdata/competitive_tile16_20261104';evidence=sources=0;bindings={}
    names=['smoke','all72','pipeline_smoke','pipeline_all72_l4','pipeline_all72_l8','hashed_smoke','hashed_all72','nonlinear_smoke','nonlinear_all48','attention_smoke','attention_all24','unified_all144','connected_materialized']
    for name in names:
        folder=base/name
        for f,digest in json.loads((folder/'manifest.json').read_text()).items():assert sha(folder/f)==digest,(name,f);evidence+=1
        for f,digest in json.loads((folder/'source_bindings.json').read_text()).items():assert sha(ROOT/f)==digest,(name,f);sources+=1
        assert json.loads((folder/'verification.json').read_text())['passed']
        bindings[(folder/'manifest.json').relative_to(ROOT).as_posix()]=sha(folder/'manifest.json')
    # Preserve the previous target/accuracy/functional-source chain.
    old=ROOT/'testdata/new_targets_delivery_20261104'
    for f,digest in json.loads((old/'manifest.json').read_text()).items():assert sha(old/f)==digest; evidence+=1
    for f,digest in json.loads((old/'source_bindings.json').read_text()).items():assert sha(ROOT/f)==digest; sources+=1
    bindings[(old/'manifest.json').relative_to(ROOT).as_posix()]=sha(old/'manifest.json')
    components.check(base/'unified_all144');connected.check(base/'connected_materialized')
    results={n:json.loads((base/n/'verification.json').read_text()) for n in names}
    sums={n:sum(row['kernel_cycles_excluding_common'] for row in results[n]['cases']) for n in ['all72','pipeline_all72_l4','pipeline_all72_l8','hashed_all72']}
    assert sums==dict(all72=956580,pipeline_all72_l4=771204,pipeline_all72_l8=770088,hashed_all72=771204)
    unified=results['unified_all144'];conn=results['connected_materialized']
    assert unified['aggregate']['output_codes']==conn['aggregate']['output_codes']==1451736
    operations=Counter()
    for row in unified['cases']:operations.update(row['operations'])
    assert operations['sqrt']==2376 and operations['divmod']==7128
    # counts['divmod'] is two result elements per request, not two divisions.
    iterative=operations['sqrt']*32+(operations['divmod']//2)*64
    assert iterative==304128
    docroot=ROOT.parent/'docs/architecture';documents=[docroot/n for n in ['COMPETITIVE_COMPONENT_MODEL_20261104.md','README.md','IMPLEMENTATION_ROADMAP.md']]
    links=0
    for doc in documents:
        for target in re.findall(r'\]\(([^)]+)\)',doc.read_text(encoding='utf-8')):
            if target.startswith(('http:','https:','mailto:','#')):continue
            target=target.split('#')[0].strip('<>');resolved=(doc.parent/target).resolve()
            # The report links to this check's own output, written below.
            assert resolved.exists() or resolved==out/'verification.json',(doc,target);links+=1
        bindings['../'+doc.relative_to(ROOT.parent).as_posix()]=sha(doc)
    pyfiles=[ROOT/'integer_model'/n for n in components.SOURCE_NAMES[:6]]+[ROOT/'scripts'/n for n in ['validate_competitive_tile16.py','validate_competitive_tile16_pipeline.py','validate_competitive_hashed_banks.py','validate_competitive_nonlinear.py','validate_competitive_attention.py','validate_competitive_components.py','validate_competitive_connected.py','check_competitive_components_delivery.py']]
    for f in pyfiles:ast.parse(f.read_text());bindings[f.relative_to(ROOT).as_posix()]=sha(f)
    cpu=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT.parent/'e203_hbirdv2',text=True).strip();assert not cpu,cpu
    user=subprocess.check_output(['git','diff','--numstat','--','kws_streaming/data/input_data.py'],cwd=ROOT,text=True).split();assert user[:2]==['3','3'],user
    review=dict(passed=True,evidence_hashes_checked=evidence,source_hashes_checked=sources,
        independent_replayed_output_codes=2903472,mismatches=0,python_sources_parsed=len(pyfiles),document_links_checked=links,
        standalone_Dense_cycles=sums,Dense_l4_vs_serial_reduction_percent=100*(1-sums['pipeline_all72_l4']/sums['all72']),
        Dense_l8_vs_l4_reduction_percent=100*(1-sums['pipeline_all72_l8']/sums['pipeline_all72_l4']),
        unified=unified['aggregate'],connected_external_materialization=conn['aggregate'],
        shared_iterative_busy_clocks=iterative,shared_iterative_sqrt_requests=2376,shared_iterative_div_requests=3564,
        CPU_repo_clean=True,user_patch_3_additions_3_deletions_preserved=True,
        full_resident_task=False,new_RTL=False,all_competition_targets_met=False)
    (out/'verification.json').write_text(json.dumps(review,indent=2))
    (out/'source_bindings.json').write_text(json.dumps(bindings,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and p.name!='manifest.json'},indent=2))
    print(json.dumps({k:v for k,v in review.items() if k not in ['unified','connected_external_materialization']},indent=2))


if __name__=='__main__':main()
