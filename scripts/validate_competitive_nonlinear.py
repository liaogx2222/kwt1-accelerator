"""Value-driven nonlinear kernel qualification, explicitly not a full task."""
import argparse
import json
import sys
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
sys.path.insert(0,str(ROOT))
from integer_model.competitive_nonlinear import VectorNonlinear


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--stage',choices=['smoke','all'],default='smoke');args=ap.parse_args()
    out=args.output.resolve();assert not out.exists();out.mkdir(parents=True)
    candidate=ROOT/'testdata/accuracy_point1_20261104/input16_only'
    for name,digest in json.loads((candidate/'manifest.json').read_text()).items():assert sha(candidate/name)==digest,name
    p=dict(np.load(candidate/'run/params/parameters.npz'));pm=json.loads((candidate/'run/params/manifest.json').read_text())
    path=candidate/'runtime_input16.py';namespace={'__file__':str(path),'__name__':'fixture_reference'}
    exec(compile(path.read_text(),str(path),'exec'),namespace)
    fixture=ROOT/'testdata/integer_v1/fixture';labels=np.load(fixture/'labels.npy');features=np.load(fixture/'encoder_input.npy',mmap_mode='r')
    sample=int(np.flatnonzero(labels==0)[0]);x=np.clip(np.rint(features[sample:sample+1].astype(np.float64)/pm['decode_scales']['encoder_input']),-32767,32767).astype(np.int16)
    stages={};namespace['Encoder'](p,lambda name,value,clip:stages.update({name:value.copy()}))(x)
    cases=[];start=time.time();codes=0
    for layer in range(12 if args.stage=='all' else 1):
        prefix=f'layer_{layer:02d}/';key=f'l{layer:02d}'
        for op in ['ln1','ln2','softmax','gelu']:
            model=VectorNonlinear(p['exp_lut'])
            if op.startswith('ln'):
                j=int(op[-1]);source=('encoder_input' if layer==0 else f'layer_{layer-1:02d}/layernorm2_output') if j==1 else prefix+'layernorm1_output'
                branch=prefix+('attention_output_projection' if j==1 else 'ffn_dense2_output');expected=prefix+f'layernorm{j}_output'
                actual,metrics=model.run_norm(stages[source][0],stages[branch][0],p,key,j)
            elif op=='softmax':
                expected=prefix+'attention_softmax';actual,metrics=model.run_softmax(stages[prefix+'attention_score_raw'][0],p,key)
            else:
                expected=prefix+'gelu_output';actual,metrics=model.run_gelu(stages[prefix+'ffn_dense1_output'][0],p[key+'_gelu_lut'])
            goal=stages[expected][0];mismatch=int(np.count_nonzero(actual!=goal))
            if mismatch:
                np.savez(out/f'failure_{layer}_{op}.npz',actual=actual,expected=goal)
                raise AssertionError((layer,op,mismatch,int(np.max(np.abs(actual.astype(np.int64)-goal.astype(np.int64))))))
            cases.append(dict(layer=layer,operation=op,codes=actual.size,**metrics));codes+=actual.size
            (out/'partial.json').write_text(json.dumps(cases,indent=2))
            print(f'NONLINEAR layer={layer} {op} codes={actual.size} cycles={metrics["kernel_cycles_excluding_common"]} reg={metrics["total_register_peak_bytes"]} elapsed={time.time()-start:.1f}s',flush=True)
    assert all(row['register_4KiB_pass'] for row in cases),'Measured register peak exceeds 4KiB; see partial.json'
    report=dict(passed=True,stage=args.stage,kernel_profiles=len(cases),output_codes=codes,mismatches=0,cases=cases,
        max_register_peak_bytes=max(row['total_register_peak_bytes'] for row in cases),
        max_scratch_peak_bytes=max(row['scratch_peak_bytes'] for row in cases),
        scope='standalone real-value residual/LN, Softmax, GELU; inter-kernel inputs are independent golden fixtures',
        full_task_executed=False,complete_IO_model=False,new_RTL_implemented=False,all_competition_targets_met=False,
        runtime_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),*[ROOT/'integer_model'/s for s in ['competitive_nonlinear.py','competitive_hashed_banks.py','competitive_tile16_pipeline.py','competitive_tile16.py','event_arithmetic.py']],candidate/'manifest.json',candidate/'run/params/parameters.npz']
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2))
    print(json.dumps(dict(passed=True,kernel_profiles=len(cases),codes=codes,max_register=report['max_register_peak_bytes']),indent=2))


if __name__=='__main__':main()
