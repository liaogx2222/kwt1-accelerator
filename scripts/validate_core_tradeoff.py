"""Exact same fixture and saved-stage replay for explicit core alternatives."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
from integer_model.competitive_core_tradeoff import TradeoffCore


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--lanes',type=int,choices=[4,8],default=4);ap.add_argument('--buffers',type=int,choices=[1,2],default=2);args=ap.parse_args();out=args.output.resolve();assert not out.exists();out.mkdir(parents=True)
    x,p,_=component.fixture();reference=component.reference_stages(x,p);saved={};chunks={};start=time.time()
    model=TradeoffCore(p['exp_lut'],lanes=args.lanes,accumulator_buffers=args.buffers)
    def observe(layer,op,value,offset=None):
        goal=reference[component.expected_key(layer,op)][0];name=f'l{layer:02d}_{op}'
        if offset is None:assert np.array_equal(value,goal);saved[name]=value.copy()
        else:assert np.array_equal(value,goal[offset:offset+len(value)]);chunks.setdefault(name,[]).append(value.copy())
        if op=='ln2':print(f'TRADEOFF lanes={args.lanes} buffers={args.buffers} layer={layer} cycle={model.b.cycle} elapsed={time.time()-start:.1f}s',flush=True)
    actual,metrics=model.run(x[0],p,observe);assert np.array_equal(actual,reference['layer_11/layernorm2_output'][0])
    for name,parts in chunks.items():saved[name]=np.concatenate(parts,axis=0)
    for layer in range(12):
        for op in ['q','k','v','qk','softmax','pv','o','ln1','fc1','gelu','fc2','ln2']:assert np.array_equal(saved[f'l{layer:02d}_{op}'],reference[component.expected_key(layer,op)][0])
    np.savez_compressed(out/'observed.npz',**saved)
    report=dict(passed=True,vector_lanes=args.lanes,accumulator_buffers=args.buffers,metrics=metrics,independent_output_codes=1451736,mismatches=0,
        scope='whole-core model alternative, same class0 fixture/profile; no CPU/packet/physical power claim',new_RTL=False,runtime_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2));sources=[Path(__file__),ROOT/'integer_model/competitive_core_tradeoff.py',ROOT/'integer_model/competitive_resident_core.py',Path(component.__file__),component.BASE/'run/params/parameters.npz']
    (out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in sources},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps(dict(passed=True,lanes=args.lanes,buffers=args.buffers,cycles=metrics['cycles'],register_peak=metrics['total_register_peak_bytes'],register_budget_pass=metrics['register_4KiB_pass'],codes=1451736),indent=2))

if __name__=='__main__':main()
