"""Saved-stage replay for whole resident core, same object two cold tasks."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
from integer_model.competitive_resident_core import ResidentCore


def inputs(count):
    folder=ROOT/'testdata/integer_v1/fixture';labels=np.load(folder/'labels.npy');features=np.load(folder/'encoder_input.npy',mmap_mode='r')
    pm=json.loads((component.BASE/'run/params/manifest.json').read_text());indices=[int(np.flatnonzero(labels==label)[0]) for label in range(count)]
    return np.clip(np.rint(features[indices].astype(np.float64)/pm['decode_scales']['encoder_input']),-32767,32767).astype(np.int16),indices


def check(out):
    for name,digest in json.loads((out/'manifest.json').read_text()).items():assert sha(out/name)==digest,name
    for name,digest in json.loads((out/'source_bindings.json').read_text()).items():assert sha(ROOT/name)==digest,name
    r=json.loads((out/'verification.json').read_text());x,_=inputs(r['tasks']);p=dict(np.load(component.BASE/'run/params/parameters.npz'));saved=dict(np.load(out/'observed.npz'));codes=0
    for task in range(r['tasks']):
        ref=component.reference_stages(x[task:task+1],p)
        for layer in range(12):
            for op in ['q','k','v','qk','softmax','pv','o','ln1','fc1','gelu','fc2','ln2']:
                actual=saved[f't{task}_l{layer:02d}_{op}'];assert np.array_equal(actual,ref[component.expected_key(layer,op)][0]);codes+=actual.size
        m=r['cases'][task];assert m['core_12layer_resident'] and m['intermediate_external_activation_bytes']==0
        assert m['common_load_count']==1 and m['register_4KiB_pass'] and max(m['scratch_bank_peak_bytes'])<=8192
        assert m['compactions']==[dict(layer=0,cycles=1600,halfwords=3200,source_bases=[1600]*4,dest_bases=[0]*4)]
        intervals=m['iterative_intervals'];assert len(intervals)==5940
        assert all(a['end']<=b['start'] for a,b in zip(intervals,intervals[1:]))
    assert codes==r['independent_output_codes'];print(json.dumps(dict(passed=True,tasks=r['tasks'],independent_output_codes=codes,mismatches=0,cycles=[m['cycles'] for m in r['cases']],core_resident=True,complete_IO_model=False,new_RTL=False),indent=2))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['run','check'],default='check');ap.add_argument('--tasks',type=int,choices=[1,2],default=2);args=ap.parse_args();out=args.output.resolve()
    if args.stage=='check':check(out);return
    assert not out.exists();out.mkdir(parents=True);x,indices=inputs(args.tasks);p=dict(np.load(component.BASE/'run/params/parameters.npz'));cases=[];saved={};start=time.time()
    model=ResidentCore(p['exp_lut']);identity=id(model)
    for task in range(args.tasks):
        if task:model.reset()
        assert id(model)==identity;ref=component.reference_stages(x[task:task+1],p);chunks={};intervals=[];original=model.e.issue
        def issue(*a,**k):
            result=original(*a,**k);unit=k.get('unit',a[4] if len(a)>4 else 'alu')
            if unit in ['div','sqrt']:intervals.append(dict(unit=unit,start=result.ready-model.e.lat[unit],end=result.ready))
            return result
        model.e.issue=issue
        def observe(layer,op,value,offset=None):
            label=f'l{layer:02d}_{op}';goal=ref[component.expected_key(layer,op)][0]
            if offset is None:
                assert np.array_equal(value,goal),(task,layer,op);saved[f't{task}_'+label]=value.copy()
            else:
                assert np.array_equal(value,goal[offset:offset+len(value)]),(task,layer,op,offset)
                chunks.setdefault(label,[]).append(value.copy())
            if op=='ln2':print(f'CORE task={task} layer={layer} cycle={model.b.cycle} elapsed={time.time()-start:.1f}s',flush=True)
        actual,metrics=model.run(x[task],p,observe);assert np.array_equal(actual,ref['layer_11/layernorm2_output'][0])
        for name,parts in chunks.items():saved[f't{task}_'+name]=np.concatenate(parts,axis=0)
        assert metrics['register_4KiB_pass'],metrics['peak_live_allocations']
        metrics['iterative_intervals']=sorted(intervals,key=lambda r:r['start']);cases.append(metrics)
        (out/'partial.json').write_text(json.dumps(cases,indent=2))
    np.savez_compressed(out/'observed.npz',**saved)
    report=dict(passed=True,tasks=args.tasks,source_indices=indices,cases=cases,independent_output_codes=1451736*args.tasks,mismatches=0,same_model_object=True,
        model_reset_between_cold_tasks=True,RTL_reset_proved=False,core_resident=True,complete_IO_model=False,new_RTL=False,all_competition_targets_met=False,runtime_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),Path(component.__file__),*[ROOT/'integer_model'/n for n in component.SOURCE_NAMES],*[ROOT/'integer_model'/n for n in ['competitive_resident_attention.py','competitive_softmax_pipeline.py','competitive_norm_pipeline.py','competitive_resident_ffn.py','competitive_resident_core.py']],component.BASE/'manifest.json',component.BASE/'run/params/parameters.npz']
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2));check(out)


if __name__=='__main__':main()
