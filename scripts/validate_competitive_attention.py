"""Qualify QK/PV actual operands and results against independent fixtures."""
import argparse
import json
import sys
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
sys.path.insert(0,str(ROOT))
from integer_model.competitive_attention import Attention16


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['smoke','all'],default='smoke');args=ap.parse_args()
    out=args.output.resolve();assert not out.exists();out.mkdir(parents=True)
    candidate=ROOT/'testdata/accuracy_point1_20261104/input16_only'
    for name,digest in json.loads((candidate/'manifest.json').read_text()).items():assert sha(candidate/name)==digest,name
    p=dict(np.load(candidate/'run/params/parameters.npz'));pm=json.loads((candidate/'run/params/manifest.json').read_text())
    path=candidate/'runtime_input16.py';ns={'__file__':str(path),'__name__':'fixture_reference'};exec(compile(path.read_text(),str(path),'exec'),ns)
    fixture=ROOT/'testdata/integer_v1/fixture';labels=np.load(fixture/'labels.npy');features=np.load(fixture/'encoder_input.npy',mmap_mode='r')
    sample=int(np.flatnonzero(labels==0)[0]);x=np.clip(np.rint(features[sample:sample+1].astype(np.float64)/pm['decode_scales']['encoder_input']),-32767,32767).astype(np.int16)
    stages={};ns['Encoder'](p,lambda name,value,clip:stages.update({name:value.copy()}))(x)
    cases=[];start=time.time()
    for layer in range(12 if args.stage=='all' else 1):
        prefix=f'layer_{layer:02d}/';key=f'l{layer:02d}'
        for op in ['qk','pv']:
            model=Attention16(p['exp_lut'])
            if op=='qk':
                actual,metrics=model.run_qk(stages[prefix+'q_projection'][0],stages[prefix+'k_projection'][0]);expected=stages[prefix+'attention_score_raw'][0]
            else:
                actual,metrics=model.run_pv(stages[prefix+'attention_softmax'][0],stages[prefix+'v_projection'][0],p[key+'_ctx_m'],p[key+'_ctx_s']);expected=stages[prefix+'attention_context'][0]
            assert np.array_equal(actual,expected),(layer,op,int(np.count_nonzero(actual!=expected)))
            assert metrics['register_4KiB_pass'] and max(metrics['scratch_bank_peak_bytes'])<=8192
            cases.append(dict(layer=layer,operation=op,codes=actual.size,**metrics));(out/'partial.json').write_text(json.dumps(cases,indent=2))
            print(f'ATTENTION layer={layer} {op} codes={actual.size} cycles={metrics["kernel_cycles_excluding_common"]} reg={metrics["total_register_peak_bytes"]} elapsed={time.time()-start:.1f}s',flush=True)
    report=dict(passed=True,kernel_profiles=len(cases),output_codes=sum(c['codes'] for c in cases),mismatches=0,cases=cases,
        max_register_peak_bytes=max(c['total_register_peak_bytes'] for c in cases),max_scratch_peak_bytes=max(c['scratch_peak_bytes'] for c in cases),
        full_task_executed=False,complete_IO_model=False,new_RTL_implemented=False,all_competition_targets_met=False)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),*[ROOT/'integer_model'/s for s in ['competitive_attention.py','competitive_nonlinear.py','competitive_hashed_banks.py','competitive_tile16_pipeline.py','competitive_tile16.py','event_arithmetic.py']],candidate/'manifest.json',candidate/'run/params/parameters.npz']
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2));print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))


if __name__=='__main__':main()
