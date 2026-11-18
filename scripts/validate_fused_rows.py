"""Single-factor kernel screening and full-core replay of bounded graph fusion."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
from integer_model.competitive_fused_rows import FusedRowsCore


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['screen','core'],default='screen');ap.add_argument('--fusion',choices=['none','ln','softmax','both'],default='both');ap.add_argument('--buffers',type=int,choices=[1,2],default=2);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    x,p,_=component.fixture();ref=component.reference_stages(x,p);saved={};cases=[];start=time.time()
    if a.stage=='screen':
        for fusion in ['none','ln','softmax','both']:
            for op in ['ln1','ln2','softmax']:
                model=FusedRowsCore(p['exp_lut'],fusion=fusion);prefix='layer_00/';key='l00'
                if op.startswith('ln'):
                    j=int(op[-1]);source=ref['encoder_input' if j==1 else prefix+'layernorm1_output'][0];branch=ref[prefix+('attention_output_projection' if j==1 else 'ffn_dense2_output')][0]
                    actual,m=model.run_norm(source,branch,p,key,j)
                else:actual,m=model.run_softmax(ref[prefix+'attention_score_raw'][0],p,key)
                assert np.array_equal(actual,ref[component.expected_key(0,op)][0]);saved[f'{fusion}_{op}']=actual;cases.append(dict(operation=op,**m))
                print(f'SCREEN {fusion} {op} cycles={m["cycles"]} reg={m["total_register_peak_bytes"]}',flush=True)
        report=dict(passed=True,stage='screen',cases=cases,independent_output_codes=sum(v.size for v in saved.values()),mismatches=0,scope='first profile single factors, over-budget candidates reported and excluded separately')
    else:
        chunks={};model=FusedRowsCore(p['exp_lut'],fusion=a.fusion,accumulator_buffers=a.buffers)
        def observe(layer,op,value,offset=None):
            expected=ref[component.expected_key(layer,op)][0];name=f'l{layer:02d}_{op}'
            if offset is None:assert np.array_equal(value,expected);saved[name]=value.copy()
            else:assert np.array_equal(value,expected[offset:offset+len(value)]);chunks.setdefault(name,[]).append(value.copy())
            if op=='ln2':print(f'FUSED {a.fusion} layer={layer} cycles={model.b.cycle}',flush=True)
        actual,m=model.run(x[0],p,observe);assert np.array_equal(actual,ref['layer_11/layernorm2_output'][0])
        for name,parts in chunks.items():saved[name]=np.concatenate(parts,axis=0)
        codes=0
        for layer in range(12):
            for op in ['q','k','v','qk','softmax','pv','o','ln1','fc1','gelu','fc2','ln2']:
                value=saved[f'l{layer:02d}_{op}'];assert np.array_equal(value,ref[component.expected_key(layer,op)][0]);codes+=value.size
        assert codes==1451736
        report=dict(passed=True,stage='core',fusion=a.fusion,accumulator_buffers=a.buffers,metrics=m,independent_output_codes=codes,mismatches=0,new_RTL=False,complete_IO_model=False)
    np.savez_compressed(out/'observed.npz',**saved);report['runtime_seconds']=time.time()-start
    (out/'verification.json').write_text(json.dumps(report,indent=2));sources=[Path(__file__),ROOT/'integer_model/competitive_fused_rows.py',ROOT/'integer_model/competitive_core_tradeoff.py',ROOT/'integer_model/competitive_resident_core.py',Path(component.__file__),component.BASE/'run/params/parameters.npz']
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2));(out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2));print(json.dumps(dict(passed=True,codes=report['independent_output_codes'],runtime_seconds=report['runtime_seconds']),indent=2))


if __name__=='__main__':main()
