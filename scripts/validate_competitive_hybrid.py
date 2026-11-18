"""Connected twelve-layer graph with resident attention + two-row LN.

Other kernel boundaries remain cold-load/external-materialization boundaries.
This is a mixed-residency functional/timing MODEL, not complete SoC IO/RTL.
"""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
from validate_competitive_connected import MaterializedOutput,MaterializedDense
from integer_model.competitive_softmax_pipeline import SoftmaxPipelinedAttention
from integer_model.competitive_norm_pipeline import PipelinedNorm


class MaterializedNorm(MaterializedOutput,PipelinedNorm):pass


def check(out):
    for name,digest in json.loads((out/'manifest.json').read_text()).items():assert sha(out/name)==digest,name
    for name,digest in json.loads((out/'source_bindings.json').read_text()).items():assert sha(ROOT/name)==digest,name
    x,p,sample=component.fixture();reference=component.reference_stages(x,p)
    r=json.loads((out/'verification.json').read_text());saved=dict(np.load(out/'observed.npz'));codes=0
    for layer in range(12):
        for op in ['q','k','v','qk','softmax','pv','o','ln1','fc1','gelu','fc2','ln2']:
            actual=saved[f'l{layer:02d}_{op}'];assert np.array_equal(actual,reference[component.expected_key(layer,op)][0]);codes+=actual.size
    assert codes==1451736 and len(r['cases'])==120
    for row in r['cases']:
        assert row['register_4KiB_pass'] and max(row['scratch_bank_peak_bytes'])<=8192
        assert row['cycles']==sum(row['phase_cycles'].values())
        if row['operation']=='attention':assert row['intermediate_external_logical_bytes']==0 and row['Softmax_pending_rows_max']==2
        if row['operation'] in ['ln1','ln2']:assert row['LN_pending_rows_max']==2
    assert r['model_cycles']==sum(c['cycles'] for c in r['cases'])
    assert r['max_register_peak_bytes']==max(c['total_register_peak_bytes'] for c in r['cases'])
    print(json.dumps(dict(passed=True,independent_output_codes=codes,mismatches=0,model_cycles=r['model_cycles'],functional_graph_connected=True,
        full_encoder_resident=False,complete_IO_model=False,new_RTL=False),indent=2))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['run','check'],default='check');args=ap.parse_args();out=args.output.resolve()
    if args.stage=='check':check(out);return
    assert not out.exists();out.mkdir(parents=True)
    component.HashedPipelinedTile16=MaterializedDense;component.VectorNonlinear=MaterializedNorm
    x,p,sample=component.fixture();reference=component.reference_stages(x,p)
    live={'encoder_input':x};saved={};cases=[];peak=x.nbytes;start=time.time()
    def save(layer,op,actual):
        assert np.array_equal(actual,reference[component.expected_key(layer,op)][0]),(layer,op)
        saved[f'l{layer:02d}_{op}']=actual.copy()
    for layer in range(12):
        key=f'l{layer:02d}';prefix=f'layer_{layer:02d}/';previous='encoder_input' if layer==0 else f'layer_{layer-1:02d}/layernorm2_output'
        for op in ['q','k','v','attention','o','ln1','fc1','gelu','fc2','ln2']:
            if op=='attention':
                chunks={name:[] for name in ['qk','softmax','pv']}
                def observe(name,offset,values):chunks[name].append(values.copy())
                model=SoftmaxPipelinedAttention(p['exp_lut'])
                actual,metrics=model.run(*[live[prefix+n+'_projection'][0] for n in ['q','k','v']],live[previous][0],p,key,observe)
                for name in chunks:save(layer,name,np.concatenate(chunks[name],axis=0))
                target=prefix+'attention_context'
            else:
                actual,metrics=component.execute(layer,op,live,p);save(layer,op,actual);target=component.expected_key(layer,op)
            live[target]=actual[None];peak=max(peak,sum(a.nbytes for a in live.values()))
            cases.append(dict(layer=layer,operation=op,**metrics))
            if op=='attention':
                for n in ['q','k','v']:del live[prefix+n+'_projection']
            elif op=='o':del live[prefix+'attention_context']
            elif op=='ln1':del live[previous];del live[prefix+'attention_output_projection']
            elif op=='gelu':del live[prefix+'ffn_dense1_output']
            elif op=='fc2':del live[prefix+'gelu_output']
            elif op=='ln2':del live[prefix+'layernorm1_output'];del live[prefix+'ffn_dense2_output']
            print(f'HYBRID {key}_{op} cycles={metrics["cycles"]} elapsed={time.time()-start:.1f}s',flush=True)
    assert list(live)==['layer_11/layernorm2_output'];np.savez_compressed(out/'observed.npz',**saved)
    report=dict(passed=True,cases=cases,source_sample=sample,independent_output_codes=1451736,mismatches=0,
        model_cycles=sum(c['cycles'] for c in cases),max_register_peak_bytes=max(c['total_register_peak_bytes'] for c in cases),
        max_scratch_peak_bytes=max(c['scratch_peak_bytes'] for c in cases),external_activation_peak_bytes=peak,
        functional_graph_connected=True,attention_resident=True,LN_two_row_pipeline=True,
        full_encoder_resident=False,complete_IO_model=False,packet_protocol=False,E203_CPU=False,new_RTL=False,all_competition_targets_met=False,
        scope='actual-result-driven graph; attention resident, other boundaries externally materialized with timed result readback; ideal 32bit/clock source/sink',
        runtime_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),ROOT/'scripts/validate_competitive_connected.py',Path(component.__file__),*[ROOT/'integer_model'/n for n in component.SOURCE_NAMES],*[ROOT/'integer_model'/n for n in ['competitive_resident_attention.py','competitive_softmax_pipeline.py','competitive_norm_pipeline.py']],component.BASE/'manifest.json',component.BASE/'run/params/parameters.npz']
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2));check(out)


if __name__=='__main__':main()
