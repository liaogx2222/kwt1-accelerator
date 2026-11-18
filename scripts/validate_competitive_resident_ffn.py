"""Resident/in-place FFN versus identical schedule with materialized hidden."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
from integer_model.competitive_resident_ffn import ResidentFFN
from integer_model.runtime import Encoder


def fixtures(scope):
    x,p,sample=component.fixture();st=component.reference_stages(x,p)
    items=[(f'l{i:02d}',f'l{i:02d}',st[f'layer_{i:02d}/layernorm1_output'][0]) for i in range(12 if scope=='all' else 1)]
    if scope=='all':
        folder=ROOT/'testdata/integer_v1/fixture';labels=np.load(folder/'labels.npy');features=np.load(folder/'encoder_input.npy',mmap_mode='r')
        pm=json.loads((component.BASE/'run/params/manifest.json').read_text())
        indices=[int(np.flatnonzero(labels==label)[0]) for label in range(1,12)]
        quant=np.clip(np.rint(features[indices].astype(np.float64)/pm['decode_scales']['encoder_input']),-32767,32767).astype(np.int16)
        extra=component.reference_stages(quant,p)['layer_00/layernorm1_output']
        items.extend((f'class{label:02d}_l00','l00',extra[label-1]) for label in range(1,12))
        rng=np.random.default_rng(20261105)
        items.extend([('edge_zero','l00',np.zeros((99,64),np.int8)),('edge_max','l00',np.full((99,64),127,np.int8)),
            ('edge_alternating','l00',np.where(np.indices((99,64)).sum(axis=0)%2,127,-127).astype(np.int8)),
            ('edge_random','l00',rng.integers(-127,128,(99,64),dtype=np.int8))])
    return items,p


def golden(x,p,key):
    e=Encoder(p);first=e.dense(x[None],key+'_fc1','fc1')[0]
    gelu=p[key+'_gelu_lut'][first.astype(np.int16)+128]
    second=e.dense(gelu[None],key+'_fc2','fc2')[0]
    return dict(fc1=first,gelu=gelu,fc2=second)


def check(out):
    for name,digest in json.loads((out/'manifest.json').read_text()).items():assert sha(out/name)==digest,name
    for name,digest in json.loads((out/'source_bindings.json').read_text()).items():assert sha(ROOT/name)==digest,name
    r=json.loads((out/'verification.json').read_text());items,p=fixtures(r['scope']);saved=dict(np.load(out/'observed.npz'));operands=dict(np.load(out/'operands.npz'));codes=0
    for name,key,x in items:
        assert np.array_equal(operands[name],x);expected=golden(x,p,key)
        for mode in ['resident','materialized']:
            for op,value in expected.items():assert np.array_equal(saved[name+'_'+mode+'_'+op],value),(name,mode,op);codes+=value.size
    for row in r['cases']:
        a,b=row['resident'],row['materialized']
        assert b['cycles']-a['cycles']==25600
        assert a['operations']==b['operations'] and a['retained_residual_unchanged']
        assert a['intermediate_external_logical_bytes']==0 and b['intermediate_external_logical_bytes']==101376
        assert b['SRAM_reads']-a['SRAM_reads']==25600 and b['SRAM_writes']-a['SRAM_writes']==25600
        for metrics in [a,b]:
            assert metrics['register_4KiB_pass'] and metrics['scratch_peak_bytes']==32000 and metrics['scratch_bank_peak_bytes']==[8000]*4
            assert metrics['consumed_hidden_halfwords']==12800 and len(metrics['guard_tests'])==6
            assert metrics['cycles']==sum(metrics['phase_cycles'].values())
            shrink=next(s for s in metrics['allocation_log'] if s['label']=='after_FC2_shrink')
            assert sum(sum(t['sizes'])*2 for t in shrink['live'])==12800
            assert shrink['free']==[[[1600,4096]]]*4
            assert metrics['allocation_log'][-1]['free']==[[[0,4096]]]*4
    assert codes==r['independent_output_codes'];print(json.dumps(dict(passed=True,profiles=len(items),independent_output_codes=codes,mismatches=0,FFN_resident=True,full_encoder_resident=False,new_RTL=False),indent=2))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--scope',choices=['smoke','all'],default='all');ap.add_argument('--stage',choices=['run','check'],default='check');args=ap.parse_args();out=args.output.resolve()
    if args.stage=='check':check(out);return
    assert not out.exists();out.mkdir(parents=True);items,p=fixtures(args.scope);rows=[];saved={};operands={};codes=0;start=time.time()
    for name,key,x in items:
        expected=golden(x,p,key);operands[name]=x;row=dict(name=name,key=key)
        for mode in ['resident','materialized']:
            def observe(op,values):
                assert np.array_equal(values,expected[op]),(name,mode,op)
                saved[name+'_'+mode+'_'+op]=values.copy()
            model=ResidentFFN(p['exp_lut'],materialize=mode=='materialized');actual,metrics=model.run(x,p,key,observe)
            assert np.array_equal(actual,expected['fc2']);assert metrics['register_4KiB_pass'],metrics['peak_live_allocations']
            codes+=sum(v.size for v in expected.values());row[mode]=metrics
            print(f'FFN {name} {mode} cycles={metrics["cycles"]} reg={metrics["total_register_peak_bytes"]} elapsed={time.time()-start:.1f}s',flush=True)
        rows.append(row);(out/'partial.json').write_text(json.dumps(rows,indent=2))
    np.savez_compressed(out/'observed.npz',**saved);np.savez_compressed(out/'operands.npz',**operands)
    report=dict(passed=True,scope=args.scope,cases=rows,independent_output_codes=codes,mismatches=0,FFN_resident=True,full_encoder_resident=False,
        complete_IO_model=False,new_RTL=False,all_competition_targets_met=False,controller_RTL_proved=False,runtime_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),ROOT/'integer_model/competitive_resident_ffn.py',ROOT/'integer_model/competitive_resident_attention.py',Path(component.__file__),*[ROOT/'integer_model'/n for n in component.SOURCE_NAMES],component.BASE/'manifest.json',component.BASE/'run/params/parameters.npz',component.BASE/'run/params/manifest.json',ROOT/'testdata/integer_v1/fixture/encoder_input.npy',ROOT/'testdata/integer_v1/fixture/labels.npy']
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2));check(out)


if __name__=='__main__':main()
