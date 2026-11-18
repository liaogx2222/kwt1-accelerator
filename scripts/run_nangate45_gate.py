"""Actual mapped top + same-library cells + 20 SRAM contracts, isolated evidence."""
import argparse,json,shutil,sys
from pathlib import Path
from local_tools import ROOT,sha
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from validate_integration import native,execute,I

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['build','run','all'],default='all');a=ap.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if (out/'verification.json').exists():raise ValueError('Published evidence exists; use new output')
    mapped=ROOT/'testdata/nangate45_reference/native_compat_20261104';math=ROOT/'testdata/nangate45_reference/math_linux_20261104'
    for base in [mapped,math]:
        for name,digest in json.loads((base/'manifest.json').read_text()).items():assert sha(base/name)==digest,name
    sources=[mapped/'mapped.v',math/'functional_cells.v',I/'tech_sram_model.sv']
    bindings={p.relative_to(ROOT).as_posix():sha(p) for p in [*sources,I/'sim_gate.cpp',ROOT/'rtl/v2/driver/kwt1.c',ROOT/'rtl/v2/driver/kwt1.h',Path(__file__)]}
    (out/'source_bindings.json').write_text(json.dumps(bindings,indent=2))
    exe=native(out/'model',sources,I/'sim_gate.cpp',ROOT/'rtl/v2/driver/kwt1.c',gate=True)
    if a.stage=='build':return
    folder=out/'run';folder.mkdir(exist_ok=True);old=ROOT/'testdata/integration_v1/release';frozen=old/'gate';manifest=json.loads((old/'evidence_manifest.json').read_text())['sha256']
    for p in frozen.iterdir():
        if p.name in ['cases.txt','cases.json'] or (p.suffix=='.hex' and p.name.startswith(('input_','expected_','common.bin','layer_'))):
            assert sha(p)==manifest['gate/'+p.name];shutil.copyfile(p,folder/p.name)
    result=execute(exe,[folder,'always',0,0,0],folder)
    assert 'PASS PROVIDER cases=2 codes=12672' in result['result'] and 'GATE RESET PASS LN arithmetic in-flight' in result['result']
    cases=json.loads((folder/'cases.json').read_text())
    for c in cases:assert (folder/f'provider_observed_{c["case"]:03d}.hex').read_text().split()==(folder/f'expected_{c["case"]:03d}.hex').read_text().split()
    for name,digest in bindings.items():assert sha(ROOT/name)==digest,name
    summary=dict(**result,scope='actual Nangate45 mapped kwt1_mmio + same Liberty functional cells + 20 external SRAM contracts; host driver functional test, no SDF or E203 instruction timing',cases=cases,output_codes=12672,inflight_reset='LN N_PASS state51 + full cold recovery',formal_equivalence=False,physical_signoff=False)
    (out/'verification.json').write_text(json.dumps(summary,indent=2))
    (out/'evidence_manifest.json').write_text(json.dumps(dict(sha256={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and 'model' not in p.relative_to(out).parts and p.name!='evidence_manifest.json'}),indent=2));print(json.dumps(dict(passed=True,output_codes=12672),indent=2))

if __name__=='__main__':main()
