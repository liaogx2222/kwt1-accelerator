"""Paired old/new residual-LN, saved outputs, independent CPU operators."""
import argparse
import json
import sys
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
sys.path.insert(0,str(ROOT))
from integer_model.competitive_nonlinear import VectorNonlinear
from integer_model.competitive_norm_pipeline import PipelinedNorm
from integer_model.runtime import Encoder


def fixtures(scope):
    x,p,sample=component.fixture();stages=component.reference_stages(x,p);items=[]
    for layer in range(12 if scope=='all' else 1):
        key=f'l{layer:02d}';prefix=f'layer_{layer:02d}/'
        for j in [1,2]:
            source=('encoder_input' if layer==0 else f'layer_{layer-1:02d}/layernorm2_output') if j==1 else prefix+'layernorm1_output'
            branch=prefix+('attention_output_projection' if j==1 else 'ffn_dense2_output')
            items.append((f'{key}_ln{j}',key,j,stages[source][0],stages[branch][0]))
    if scope=='all':
        zero=np.zeros((99,64),np.int8);a=np.where(np.indices((99,64)).sum(axis=0)%2,127,-127).astype(np.int8)
        items.extend([('edge_zero','l00',1,zero.astype(np.int16),zero),('edge_max','l00',1,np.full((99,64),32767,np.int16),np.full((99,64),127,np.int8)),
            ('edge_alternating','l00',1,(a.astype(np.int16)*258).astype(np.int16),-a),('edge_ln2','l00',2,a,-a)])
    return items,p


def golden(a,b,p,key,j):
    e=Encoder(p);res=e.residual(a[None],b[None],key+f'_r{j}','residual')
    return e.layernorm(res,key+f'_ln{j}','norm')[0]


def check(out):
    for name,digest in json.loads((out/'manifest.json').read_text()).items():assert sha(out/name)==digest,name
    for name,digest in json.loads((out/'source_bindings.json').read_text()).items():assert sha(ROOT/name)==digest,name
    r=json.loads((out/'verification.json').read_text());saved=dict(np.load(out/'observed.npz'));items,p=fixtures(r['scope']);codes=0
    for name,key,j,a,b in items:
        expected=golden(a,b,p,key,j)
        for mode in ['serial','pipeline']:assert np.array_equal(saved[name+'_'+mode],expected);codes+=expected.size
    for row in r['cases']:
        a,b=row['serial'],row['pipeline'];assert a['operations']==b['operations']
        assert b['register_4KiB_pass'] and b['LN_pending_rows_max']==2 and b['extra_arithmetic_units']==0
        assert b['cycles']<a['cycles']
    assert codes==r['independent_output_codes'];print(json.dumps(dict(passed=True,profiles=len(items),independent_output_codes=codes,mismatches=0,new_RTL=False),indent=2))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--scope',choices=['smoke','all'],default='all');ap.add_argument('--stage',choices=['run','check'],default='check');args=ap.parse_args();out=args.output.resolve()
    if args.stage=='check':check(out);return
    assert not out.exists();out.mkdir(parents=True);items,p=fixtures(args.scope);rows=[];saved={};start=time.time();codes=0
    for name,key,j,a,b in items:
        row=dict(name=name);expected=golden(a,b,p,key,j)
        for mode,cls in [('serial',VectorNonlinear),('pipeline',PipelinedNorm)]:
            model=cls(p['exp_lut']);actual,metrics=model.run_norm(a,b,p,key,j)
            assert np.array_equal(actual,expected),(name,mode);assert metrics['register_4KiB_pass'],metrics['peak_live_allocations']
            saved[name+'_'+mode]=actual;codes+=actual.size;row[mode]=metrics
            print(f'LN {name} {mode} cycles={metrics["cycles"]} reg={metrics["total_register_peak_bytes"]} elapsed={time.time()-start:.1f}s',flush=True)
        rows.append(row);(out/'partial.json').write_text(json.dumps(rows,indent=2))
    np.savez_compressed(out/'observed.npz',**saved)
    report=dict(passed=True,scope=args.scope,cases=rows,independent_output_codes=codes,mismatches=0,full_encoder_resident=False,new_RTL=False,runtime_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),ROOT/'integer_model/competitive_norm_pipeline.py',Path(component.__file__),*[ROOT/'integer_model'/name for name in component.SOURCE_NAMES],component.BASE/'manifest.json',component.BASE/'run/params/parameters.npz']
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2));check(out)


if __name__=='__main__':main()
