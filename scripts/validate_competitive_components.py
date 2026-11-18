"""Unified qualification with saved outputs and an independent CPU graph replay.

144 kernels cover all layer profiles, but dependencies between kernels are
golden fixtures. This does NOT execute a connected twelve-layer accelerator.
"""
import argparse
import json
import platform
import sys
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
sys.path.insert(0,str(ROOT))
from integer_model.runtime import Encoder,rq
from integer_model.competitive_hashed_banks import HashedPipelinedTile16
from integer_model.competitive_nonlinear import VectorNonlinear
from integer_model.competitive_attention import Attention16


BASE=ROOT/'testdata/accuracy_point1_20261104/input16_only'
SOURCE_NAMES=['competitive_tile16.py','competitive_tile16_pipeline.py','competitive_hashed_banks.py','competitive_nonlinear.py','competitive_attention.py','event_arithmetic.py','runtime.py']


def reference_stages(x,p):
    stages={'encoder_input':x.copy()}
    e=Encoder(p,lambda name,value,clip:stages.update({name:value.copy()}))
    # This explicit graph uses the unchanged CPU operator implementation,
    # independently of the S16 derivative used by earlier qualification.
    for layer in range(12):
        key=f'l{layer:02d}';name=f'layer_{layer:02d}/'
        q,k,v=[e.dense(x,key+'_'+kind,name+kind+'_projection') for kind in ['q','k','v']]
        score=q.astype(np.int32)@np.swapaxes(k.astype(np.int32),-1,-2)
        stages[name+'attention_score_raw']=score
        probability=e.softmax(score,key+'_score',name+'attention_softmax')
        context=np.clip(rq(probability.astype(np.int32)@v.astype(np.int32),p[key+'_ctx_m'],p[key+'_ctx_s']),-127,127).astype(np.int8)
        stages[name+'attention_context']=context
        projected=e.dense(context,key+'_o',name+'attention_output_projection')
        residual=e.residual(x,projected,key+'_r1',name+'residual1_sum')
        norm=e.layernorm(residual,key+'_ln1',name+'layernorm1_output')
        hidden=e.dense(norm,key+'_fc1',name+'ffn_dense1_output')
        gelu=p[key+'_gelu_lut'][hidden.astype(np.int16)+128];stages[name+'gelu_output']=gelu
        second=e.dense(gelu,key+'_fc2',name+'ffn_dense2_output')
        residual=e.residual(norm,second,key+'_r2',name+'residual2_sum')
        x=e.layernorm(residual,key+'_ln2',name+'layernorm2_output')
    return stages


def fixture():
    for name,digest in json.loads((BASE/'manifest.json').read_text()).items():assert sha(BASE/name)==digest,name
    p=dict(np.load(BASE/'run/params/parameters.npz'));pm=json.loads((BASE/'run/params/manifest.json').read_text())
    folder=ROOT/'testdata/integer_v1/fixture';labels=np.load(folder/'labels.npy');features=np.load(folder/'encoder_input.npy',mmap_mode='r')
    sample=int(np.flatnonzero(labels==0)[0]);x=np.clip(np.rint(features[sample:sample+1].astype(np.float64)/pm['decode_scales']['encoder_input']),-32767,32767).astype(np.int16)
    return x,p,sample


def expected_key(layer,op):
    name=f'layer_{layer:02d}/'
    return name+dict(q='q_projection',k='k_projection',v='v_projection',o='attention_output_projection',fc1='ffn_dense1_output',fc2='ffn_dense2_output',ln1='layernorm1_output',ln2='layernorm2_output',softmax='attention_softmax',gelu='gelu_output',qk='attention_score_raw',pv='attention_context')[op]


def execute(layer,op,stages,p):
    prefix=f'layer_{layer:02d}/';key=f'l{layer:02d}'
    previous='encoder_input' if layer==0 else f'layer_{layer-1:02d}/layernorm2_output'
    if op in ['q','k','v','o','fc1','fc2']:
        source=previous if op in ['q','k','v'] else prefix+dict(o='attention_context',fc1='layernorm1_output',fc2='gelu_output')[op]
        model=HashedPipelinedTile16(p['exp_lut']);k=key+'_'+op
        actual,metrics=model.run(stages[source][0],p[k+'_w'],p[k+'_b'],p[k+'_m'],p[k+'_s'])
    elif op in ['ln1','ln2']:
        model=VectorNonlinear(p['exp_lut']);j=int(op[-1]);source=previous if j==1 else prefix+'layernorm1_output'
        branch=prefix+('attention_output_projection' if j==1 else 'ffn_dense2_output')
        actual,metrics=model.run_norm(stages[source][0],stages[branch][0],p,key,j)
    elif op=='softmax':
        model=VectorNonlinear(p['exp_lut']);actual,metrics=model.run_softmax(stages[prefix+'attention_score_raw'][0],p,key)
    elif op=='gelu':
        model=VectorNonlinear(p['exp_lut']);actual,metrics=model.run_gelu(stages[prefix+'ffn_dense1_output'][0],p[key+'_gelu_lut'])
    elif op=='qk':
        model=Attention16(p['exp_lut']);actual,metrics=model.run_qk(stages[prefix+'q_projection'][0],stages[prefix+'k_projection'][0])
    else:
        model=Attention16(p['exp_lut']);actual,metrics=model.run_pv(stages[prefix+'attention_softmax'][0],stages[prefix+'v_projection'][0],p[key+'_ctx_m'],p[key+'_ctx_s'])
    metrics['SRAM_reads']=sum(v for (bank,mode),v in model.b.counts.items() if mode=='r')
    metrics['SRAM_writes']=sum(v for (bank,mode),v in model.b.counts.items() if mode=='w')
    metrics['phase_cycles']={f'{a}/{b}':v for (a,b),v in model.b.stage_cycles.items()}
    assert sum(metrics['phase_cycles'].values())==metrics['cycles']
    return actual,metrics


def aggregate(cases):
    by_op={}
    for row in cases:
        dest=by_op.setdefault(row['operation'],dict(kernel_profiles=0,output_codes=0,cycles_excluding_common_sum=0,SRAM_reads=0,SRAM_writes=0))
        dest['kernel_profiles']+=1;dest['output_codes']+=row['output_codes'];dest['cycles_excluding_common_sum']+=row['kernel_cycles_excluding_common']
        for field in ['SRAM_reads','SRAM_writes']:dest[field]+=row[field]
    return dict(by_operation=by_op,standalone_cycle_sum_excluding_common=sum(r['kernel_cycles_excluding_common'] for r in cases),
        standalone_cycle_sum_including_repeated_common=sum(r['cycles'] for r in cases),
        max_register_peak_bytes=max(r['total_register_peak_bytes'] for r in cases),max_scratch_peak_bytes=max(r['scratch_peak_bytes'] for r in cases),
        output_codes=sum(r['output_codes'] for r in cases),kernel_profiles=len(cases))


def check(out):
    for name,digest in json.loads((out/'manifest.json').read_text()).items():assert sha(out/name)==digest,name
    for name,digest in json.loads((out/'source_bindings.json').read_text()).items():assert sha(ROOT/name)==digest,name
    report=json.loads((out/'verification.json').read_text());x,p,sample=fixture();stages=reference_stages(x,p)
    saved=dict(np.load(out/'observed_outputs.npz'));codes=0
    for row in report['cases']:
        label=row['id'];actual=saved[label];expected=stages[expected_key(row['layer'],row['operation'])][0]
        assert np.array_equal(actual,expected),label;codes+=actual.size
        assert row['register_4KiB_pass'] and max(row['scratch_bank_peak_bytes'])<=8192
        assert row['private_SRAM_bytes']==65536
        assert row['cycles']==sum(row['phase_cycles'].values())
    assert set(saved)=={r['id'] for r in report['cases']}
    assert report['aggregate']==aggregate(report['cases']) and codes==report['aggregate']['output_codes']
    assert report['source_sample']==sample and report['full_task_executed'] is False
    print(json.dumps(dict(passed=True,independent_replayed_output_codes=codes,mismatches=0,full_task_executed=False,all_targets_met=False),indent=2))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['run','check'],default='check');ap.add_argument('--scope',choices=['smoke','all'],default='all');args=ap.parse_args();out=args.output.resolve()
    if args.stage=='check':check(out);return
    assert not out.exists();out.mkdir(parents=True);x,p,sample=fixture();stages=reference_stages(x,p)
    cases=[];outputs={};start=time.time()
    for layer in range(12 if args.scope=='all' else 1):
        for op in ['q','k','v','qk','softmax','pv','o','ln1','fc1','gelu','fc2','ln2']:
            actual,metrics=execute(layer,op,stages,p);assert np.array_equal(actual,stages[expected_key(layer,op)][0]),(layer,op)
            label=f'l{layer:02d}_{op}';outputs[label]=actual.copy();cases.append(dict(id=label,layer=layer,operation=op,output_codes=actual.size,**metrics))
            assert metrics['register_4KiB_pass']
            print(f'COMPONENT {label} codes={actual.size} cycles={metrics["kernel_cycles_excluding_common"]} elapsed={time.time()-start:.1f}s',flush=True)
    np.savez_compressed(out/'observed_outputs.npz',**outputs)
    report=dict(passed=True,scope=args.scope,source_sample=sample,mismatches=0,cases=cases,aggregate=aggregate(cases),
        full_task_executed=False,inter_kernel_dependencies='golden fixtures; actual kernel outputs are saved and independently replayed, not fed to the next kernel',
        complete_IO_model=False,new_RTL_implemented=False,all_competition_targets_met=False,
        declared_static_controller_bytes=512,exp_cache_metadata_bytes=42,controller_RTL_proved=False,
        python_version=platform.python_version(),numpy_version=np.__version__,runtime_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),*[ROOT/'integer_model'/s for s in SOURCE_NAMES],BASE/'manifest.json',BASE/'run/params/parameters.npz',BASE/'run/params/manifest.json',ROOT/'testdata/integer_v1/fixture/encoder_input.npy',ROOT/'testdata/integer_v1/fixture/labels.npy']
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2));check(out)


if __name__=='__main__':main()
