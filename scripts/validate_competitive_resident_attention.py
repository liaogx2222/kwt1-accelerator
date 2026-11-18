"""Paired, same-window resident attention with saved operands and outputs."""
import argparse
import json
import sys
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
sys.path.insert(0,str(ROOT))
from integer_model.competitive_resident_attention import ResidentAttention
from integer_model.runtime import Encoder,rq


def cases(scope):
    x,p,sample=component.fixture();stages=component.reference_stages(x,p);items=[]
    for layer in range(12 if scope=='all' else 1):
        prefix=f'layer_{layer:02d}/';previous='encoder_input' if layer==0 else f'layer_{layer-1:02d}/layernorm2_output'
        items.append((f'l{layer:02d}',layer,stages[prefix+'q_projection'][0],stages[prefix+'k_projection'][0],stages[prefix+'v_projection'][0],stages[previous][0]))
    if scope=='all':
        z=np.zeros((99,64),np.int8);maximum=np.full((99,64),127,np.int8)
        alternating=np.where(np.indices((99,64)).sum(axis=0)%2,127,-127).astype(np.int8)
        random=np.random.default_rng(20261104)
        items.extend([
            ('edge_zero',0,z,z,z,np.zeros((99,64),np.int16)),
            ('edge_uniform_max',0,maximum,maximum,maximum,np.full((99,64),32767,np.int16)),
            ('edge_alternating',0,alternating,-alternating,alternating,np.where(np.indices((99,64)).sum(axis=0)%2,32767,-32767).astype(np.int16)),
            ('edge_random',0,*[random.integers(-127,128,(99,64),dtype=np.int8) for _ in range(3)],random.integers(-32767,32768,(99,64),dtype=np.int16))])
    return items,p,sample


def golden(q,k,v,p,key):
    score=q.astype(np.int32)@k.astype(np.int32).T
    probability=Encoder(p).softmax(score[None],key+'_score','independent_probability')[0]
    context=np.clip(rq(probability.astype(np.int32)@v.astype(np.int32),p[key+'_ctx_m'],p[key+'_ctx_s']),-127,127).astype(np.int8)
    return dict(qk=score,softmax=probability,pv=context)


def check(out):
    for name,digest in json.loads((out/'manifest.json').read_text()).items():assert sha(out/name)==digest,name
    for name,digest in json.loads((out/'source_bindings.json').read_text()).items():assert sha(ROOT/name)==digest,name
    r=json.loads((out/'verification.json').read_text());inputs=dict(np.load(out/'operands.npz'));observed=dict(np.load(out/'observed.npz'))
    items,p,sample=cases(r['scope']);codes=0
    for name,layer,*arrays in items:
        for kind,value in zip(['q','k','v','branch'],arrays):assert np.array_equal(inputs[name+'_'+kind],value)
        expected=golden(*arrays[:3],p,f'l{layer:02d}')
        for mode in ['resident','materialized']:
            for op,goal in expected.items():
                actual=observed[name+'_'+mode+'_'+op];assert np.array_equal(actual,goal),(name,mode,op);codes+=goal.size
    for row in r['cases']:
        a,b=row['resident'],row['materialized']
        assert a['register_4KiB_pass'] and b['register_4KiB_pass']
        assert max(a['scratch_bank_peak_bytes'])<=8192 and a['scratch_peak_bytes']==b['scratch_peak_bytes']
        assert b['cycles']-a['cycles']==29700
        assert a['intermediate_external_logical_bytes']==0 and b['intermediate_external_logical_bytes']==117612
        assert b['SRAM_reads']-a['SRAM_reads']==29700 and b['SRAM_writes']-a['SRAM_writes']==29700
        assert a['retained_residual_unchanged'] and len(a['guard_tests'])==5
        assert a['cycles']==sum(a['phase_cycles'].values()) and b['cycles']==sum(b['phase_cycles'].values())
    assert codes==r['independent_output_codes']
    print(json.dumps(dict(passed=True,cases=len(r['cases']),independent_output_codes=codes,mismatches=0,
        resident_intermediate_external_bytes=0,paired_cycle_reduction_per_case=29700,full_encoder_resident=False,new_RTL=False),indent=2))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['run','check'],default='check');ap.add_argument('--scope',choices=['smoke','all'],default='all');args=ap.parse_args();out=args.output.resolve()
    if args.stage=='check':check(out);return
    assert not out.exists();out.mkdir(parents=True);items,p,sample=cases(args.scope);rows=[];operands={};observed={};start=time.time();codes=0
    for name,layer,q,k,v,branch in items:
        for kind,value in zip(['q','k','v','branch'],[q,k,v,branch]):operands[name+'_'+kind]=value
        expected=golden(q,k,v,p,f'l{layer:02d}');row=dict(name=name,layer=layer)
        for mode in ['resident','materialized']:
            chunks={op:[] for op in expected}
            def observe(op,start,values):chunks[op].append(values.copy())
            model=ResidentAttention(p['exp_lut'],materialize=mode=='materialized')
            actual,metrics=model.run(q,k,v,branch,p,f'l{layer:02d}',observe)
            assert np.array_equal(actual,expected['pv'])
            for op in expected:
                result=np.concatenate(chunks[op],axis=0);assert np.array_equal(result,expected[op]),(name,mode,op)
                observed[name+'_'+mode+'_'+op]=result;codes+=result.size
            assert metrics['register_4KiB_pass'],metrics['peak_live_allocations']
            row[mode]=metrics
            print(f'RESIDENT {name} {mode} cycles={metrics["cycles"]} scratch={metrics["scratch_peak_bytes"]} reg={metrics["total_register_peak_bytes"]} elapsed={time.time()-start:.1f}s',flush=True)
        rows.append(row);(out/'partial.json').write_text(json.dumps(rows,indent=2))
    np.savez_compressed(out/'operands.npz',**operands);np.savez_compressed(out/'observed.npz',**observed)
    report=dict(passed=True,scope=args.scope,cases=rows,source_sample=sample,independent_output_codes=codes,mismatches=0,
        full_encoder_resident=False,complete_IO_model=False,new_RTL=False,all_competition_targets_met=False,
        register_control_budget_bytes=512,register_metadata_bytes=42,controller_RTL_proved=False,
        runtime_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),ROOT/'integer_model/competitive_resident_attention.py',Path(component.__file__),*[ROOT/'integer_model'/name for name in component.SOURCE_NAMES],component.BASE/'manifest.json',component.BASE/'run/params/parameters.npz']
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2));check(out)


if __name__=='__main__':main()
