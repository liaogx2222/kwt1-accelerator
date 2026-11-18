"""Connected actual-value graph with explicitly materialized kernel boundaries.

All 144 outputs drive subsequent computation. Each kernel cold-loads operands
and parameters; its result is physically read out at <=32 bits/clock before
the next kernel starts. This is an external-materialization reference, NOT a
64KiB-resident task, an E203 simulation, or a competitive transport design.
"""
import argparse
import json
import sys
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component


class MaterializedOutput:
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.drained=[];self.output_words=0
        original=self.s.release
        def release(t):
            if t.name in ['output','norm','probability','hidden','score_query_tile','context']:self.drain(t)
            original(t)
        self.s.release=release
    def drain(self,t):
        self.b.stage='external_output_materialization';cache={}
        for plane in range(t.bits//8):
            for group in range((t.rows+7)//8):
                for col in range(t.cols):
                    locations=[t.word(row,col,plane) for row in range(group*8,min(group*8+8,t.rows),2)]
                    for begin in range(0,len(locations),2):
                        loc=locations[begin:begin+2];allocation=self.e.allocate('external_output_word_latch',len(loc)*2)
                        words=self.b.tick([(bank,addr,'r',0) for bank,addr in loc],'external_result_32bit_read')
                        cache.update(zip(loc,words));self.output_words+=len(words);self.e.release(allocation)
        values=np.empty((t.rows,t.cols),np.int64)
        for row in range(t.rows):
            for col in range(t.cols):
                value=sum(((cache[t.word(row,col,plane)]>>(8*(row%2)))&255)<<(8*plane) for plane in range(t.bits//8))
                if t.signed and value>=(1<<(t.bits-1)):value-=1<<t.bits
                values[row,col]=value
        self.drained.append(values)
    def captured(self,result):
        debug,metrics=result;actual=np.concatenate(self.drained,axis=0).astype(debug.dtype)
        assert np.array_equal(actual,debug),'Timed external readback differs from SRAM debug view'
        metrics['external_output_16bit_words']=self.output_words
        metrics['scope']='cold kernel with actual timed <=32bit/cycle output materialization; no resident inter-kernel overlap'
        return actual,metrics
    def run(self,*a,**k):return self.captured(super().run(*a,**k))
    def run_norm(self,*a,**k):return self.captured(super().run_norm(*a,**k))
    def run_softmax(self,*a,**k):return self.captured(super().run_softmax(*a,**k))
    def run_gelu(self,*a,**k):return self.captured(super().run_gelu(*a,**k))
    def run_qk(self,*a,**k):return self.captured(super().run_qk(*a,**k))
    def run_pv(self,*a,**k):return self.captured(super().run_pv(*a,**k))


class MaterializedDense(MaterializedOutput,component.HashedPipelinedTile16):pass
class MaterializedNonlinear(MaterializedOutput,component.VectorNonlinear):pass
class MaterializedAttention(MaterializedOutput,component.Attention16):pass


def schedule():
    rows=[]
    for layer in range(12):
        prefix=f'layer_{layer:02d}/';previous='encoder_input' if layer==0 else f'layer_{layer-1:02d}/layernorm2_output'
        deps=dict(q=[previous],k=[previous],v=[previous],qk=[prefix+'q_projection',prefix+'k_projection'],
            softmax=[prefix+'attention_score_raw'],pv=[prefix+'attention_softmax',prefix+'v_projection'],
            o=[prefix+'attention_context'],ln1=[previous,prefix+'attention_output_projection'],
            fc1=[prefix+'layernorm1_output'],gelu=[prefix+'ffn_dense1_output'],fc2=[prefix+'gelu_output'],
            ln2=[prefix+'layernorm1_output',prefix+'ffn_dense2_output'])
        for op in ['q','k','v','qk','softmax','pv','o','ln1','fc1','gelu','fc2','ln2']:
            rows.append(dict(layer=layer,operation=op,id=f'l{layer:02d}_{op}',key=component.expected_key(layer,op),dependencies=deps[op]))
    return rows


def check(out):
    for name,digest in json.loads((out/'manifest.json').read_text()).items():assert sha(out/name)==digest,name
    for name,digest in json.loads((out/'source_bindings.json').read_text()).items():assert sha(ROOT/name)==digest,name
    r=json.loads((out/'verification.json').read_text());x,p,sample=component.fixture();reference=component.reference_stages(x,p)
    codes=0
    for row,step in zip(r['cases'],schedule()):
        actual=np.load(out/'outputs'/f'{step["id"]}.npy');assert np.array_equal(actual,reference[step['key']][0]),step['id'];codes+=actual.size
        assert row['dependencies']==step['dependencies'] and row['register_4KiB_pass']
        assert row['cycles']==sum(row['phase_cycles'].values())
        assert row['external_output_16bit_words']*2>=actual.nbytes
    assert len(r['cases'])==144 and codes==1451736 and r['aggregate']==component.aggregate(r['cases'])
    assert r['functional_graph_connected'] and not r['resident_task_executed'] and not r['complete_IO_model']
    print(json.dumps(dict(passed=True,independent_output_codes=codes,mismatches=0,functional_graph_connected=True,
        resident_task_executed=False,complete_IO_model=False,all_competition_targets_met=False),indent=2))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['run','check'],default='check');args=ap.parse_args();out=args.output.resolve()
    if args.stage=='check':check(out);return
    assert not out.exists();(out/'outputs').mkdir(parents=True)
    component.HashedPipelinedTile16=MaterializedDense;component.VectorNonlinear=MaterializedNonlinear;component.Attention16=MaterializedAttention
    x,p,sample=component.fixture();reference=component.reference_stages(x,p)
    live={'encoder_input':x};rows=schedule();last_use={key:i for i,row in enumerate(rows) for key in row['dependencies']}
    peak=x.nbytes;cases=[];start=time.time()
    for i,step in enumerate(rows):
        assert all(dep in live for dep in step['dependencies'])
        actual,metrics=component.execute(step['layer'],step['operation'],live,p)
        # The independently computed golden graph is consulted only here,
        # after execution, and is never supplied to the candidate executor.
        assert np.array_equal(actual,reference[step['key']][0]),step['id']
        live[step['key']]=actual[None];peak=max(peak,sum(a.nbytes for a in live.values()))
        np.save(out/'outputs'/f'{step["id"]}.npy',actual)
        cases.append(dict(**step,output_codes=actual.size,**metrics))
        for key in list(live):
            if last_use.get(key,-1)<=i and key!=rows[-1]['key']:del live[key]
        print(f'CONNECTED {step["id"]} cycles={metrics["cycles"]} host_live={sum(a.nbytes for a in live.values())} elapsed={time.time()-start:.1f}s',flush=True)
    assert list(live)==[rows[-1]['key']]
    report=dict(passed=True,cases=cases,aggregate=component.aggregate(cases),source_sample=sample,
        functional_graph_connected=True,resident_task_executed=False,full_task_executed=False,
        complete_IO_model=False,packet_CRC_and_ownership_modeled=False,E203_CPU_executed=False,
        external_activation_materialization_peak_bytes=peak,parameter_backing_array_bytes=sum(a.nbytes for a in p.values()),
        parameter_transport='cold per-kernel array/coeff/cache fills already charged by the component model; not 13-package driver protocol',
        output_transport='actual synchronous SRAM reads, <=32 bits/clock, padded halfword count, no free output debug drain',
        timing='sum of serial cold kernels with repeated common fills and external activation round trips; no inter-kernel overlap',
        external_memory_latency='ideal source/sink with one 32-bit beat per clock; no E203/provider delay/CRC/final classification software',
        new_RTL_implemented=False,all_competition_targets_met=False,runtime_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),Path(component.__file__),*[ROOT/'integer_model'/s for s in component.SOURCE_NAMES],component.BASE/'manifest.json',component.BASE/'run/params/parameters.npz',component.BASE/'run/params/manifest.json']
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({s.relative_to(out).as_posix():sha(s) for s in out.rglob('*') if s.is_file()},indent=2));check(out)


if __name__=='__main__':main()
