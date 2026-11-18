"""All 12 parameter sets, executable arithmetic and measured live storage."""
import argparse
import json
import sys
import time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integer_model.runtime import Encoder
from integer_model.executable_layer import ExecutableLayer
from integer_model.register_contract import budget


def boundary_oracle(params,layer,x):
    # External oracle only: its tensors are used by assertions, never stores.
    expected={};ref=Encoder(params,lambda n,v,c:expected.update({n:v[0].copy()}) if '/' not in n else None)
    key=f'l{layer:02d}';x=x[None]
    q,k,v=[ref.dense(x,key+'_'+s,s+'_projection') for s in ['q','k','v']]
    score=q.astype(np.int32)@np.swapaxes(k.astype(np.int32),-1,-2)
    probability=ref.softmax(score,key+'_score','attention_softmax')
    from integer_model.runtime import rq
    context=ref.emit('attention_context',rq(probability.astype(np.int32)@v.astype(np.int32),params[key+'_ctx_m'],params[key+'_ctx_s']),8)
    o=ref.dense(context,key+'_o','attention_output_projection')
    r=ref.residual(x,o,key+'_r1','residual1_sum');norm=ref.layernorm(r,key+'_ln1','layernorm1_output')
    hidden=ref.dense(norm,key+'_fc1','ffn_dense1_output')
    gelu=ref.emit('gelu_output',params[key+'_gelu_lut'][hidden.astype(np.int16)+128])
    fc2=ref.dense(gelu,key+'_fc2','ffn_dense2_output');r=ref.residual(norm,fc2,key+'_r2','residual2_sum')
    ref.layernorm(r,key+'_ln2','layernorm2_output');return expected


def edge_input():
    rows=[np.zeros(64,np.int8),np.full(64,127,np.int8),np.full(64,-127,np.int8),
          np.array([127,-127]*32,np.int8),np.array([127]*63+[126],np.int8),
          np.array([127]+[-127]*63,np.int8),np.arange(-32,32,dtype=np.int8)]
    return np.stack([rows[i%len(rows)] for i in range(99)])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'testdata/r1r2/r1')
    p.add_argument('--layers',default='0,1,2,3,4,5,6,7,8,9,10,11')
    p.add_argument('--sample',type=int,default=187)
    p.add_argument('--variant',choices=['baseline','coefficient_cache','gelu2','gelu8'],default='baseline')
    p.add_argument('--no-traces',action='store_true')
    p.add_argument('--lifetime-only',action='store_true')
    p.add_argument('--boundary-input',action='store_true')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    params=dict(np.load(ROOT/'testdata/integer_v1/params/parameters.npz'))
    meta=json.loads((ROOT/'testdata/integer_v1/params/manifest.json').read_text())
    x=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r')[a.sample:a.sample+1]
    q=np.clip(np.rint(x.astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
    taps={}
    def observer(name,val,clip):
        if name.count('/')==1:taps[name]=val[0].copy()
    Encoder(params,observer)(q)
    results=[];start=time.time()
    for i in map(int,a.layers.split(',')):
        folder=a.output/f'layer_{i:02d}';folder.mkdir(exist_ok=True)
        expected={name.split('/')[1]:val for name,val in taps.items() if name.startswith(f'layer_{i:02d}/')}
        inp=q[0] if i==0 else taps[f'layer_{i-1:02d}/layernorm2_output']
        if a.boundary_input:inp=edge_input();expected=boundary_oracle(params,i,inp)
        model=ExecutableLayer(params,folder/'bank_trace.jsonl.gz',i,None if a.no_traces else folder/'arithmetic.jsonl.gz',None if a.no_traces and not a.lifetime_only else folder/'lifetimes.jsonl.gz',
             a.variant=='coefficient_cache',2 if a.variant=='gelu2' else 8 if a.variant=='gelu8' else 1)
        if a.no_traces:model.b.enabled=False
        out=model.run(inp,expected);assert np.array_equal(out,expected['layernorm2_output'])
        np.save(folder/'output.npy',out)
        result={'layer':i,'variant':a.variant,'codes':int(out.size),'mismatches':0,'cycles':model.b.cycle,
            'core_cycles':model.b.cycle-model.local_load_cycles-model.handoff_cycles,
            'coefficient_read_bytes':model.coefficient_reads,'liveness':model.measured,'register_budget':budget(model.measured),
            'bank_reads':sum(v for (bank,mode),v in model.b.counts.items() if mode=='r'),
            'bank_writes':sum(v for (bank,mode),v in model.b.counts.items() if mode=='w')}
        (folder/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');results.append(result)
        print('R1',i,'cycles',result['core_cycles'],'peak',model.measured['peak_bytes'],'elapsed',round(time.time()-start,1),flush=True)
    summary={'variant':a.variant,'sample':a.sample,'boundary_input':a.boundary_input,'layers':results,'zero_mismatch':True,
        'register_peak_bytes':max(r['liveness']['peak_bytes'] for r in results),
        'register_total_peak_bytes':max(r['register_budget']['reserved_total_peak_bytes'] for r in results),
        'budget_4096_pass':all(r['register_budget']['passed'] for r in results),'elapsed_seconds':time.time()-start}
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__=='__main__':main()
