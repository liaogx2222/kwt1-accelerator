"""12 profiles: residual/LN and Softmax edges; failure injection and lifetimes."""
import gzip
import json
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from integer_model.event_arithmetic import Engine
from integer_model.executable_layer import ExecutableLayer
from integer_model.runtime import Encoder
from audit_r1_events import audit


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'testdata/r1r2/boundaries')
    out=parser.parse_args().output;out.mkdir(parents=True,exist_ok=True)
    engine=Engine(trace=out/'unit_events.gz');a=engine.source(3);b=engine.source(5)
    result=engine.issue('mul',[a,b],unit='mul',advance=False)
    try:engine.read(result,wait=False)
    except RuntimeError:early=True
    else:raise AssertionError('early use accepted')
    assert engine.consume(result)==15
    for c in [a,b,result]:engine.drop(c)
    life=engine.close();assert audit(out/'unit_events.gz')['passed']
    records=[json.loads(s) for s in gzip.open(out/'unit_events.gz','rt')]
    bad=[dict(r) for r in records]
    for r in bad:
        if r['type']=='complete':r['result']+=1;break
    with gzip.open(out/'wrong_result.gz','wt') as f:
        for r in bad:f.write(json.dumps(r)+'\n')
    try:audit(out/'wrong_result.gz')
    except AssertionError:wrong=True
    else:raise AssertionError('wrong result accepted')
    bad=[dict(r) for r in records]
    for r in bad:
        if r['type']=='consume':r['at']=0;break
    with gzip.open(out/'early_use.gz','wt') as f:
        for r in bad:f.write(json.dumps(r)+'\n')
    try:audit(out/'early_use.gz')
    except AssertionError:early_trace=True
    else:raise AssertionError('early consumer accepted')
    slow=Engine(mul_latency=9);a=slow.source(-17);b=slow.source(31);c=slow.issue('mul',[a,b],unit='mul');assert slow.consume(c)==-527 and slow.now>=9
    for x in [a,b,c]:slow.drop(x)
    slow.close()
    fault=Engine(trace=out/'actual_corruption.gz',corrupt=lambda meta:meta['op']=='mul')
    a=fault.source(3);b=fault.source(5);c=fault.issue('mul',[a,b],unit='mul');assert fault.consume(c)==16
    for x in [a,b,c]:fault.drop(x)
    fault.close()
    try:audit(out/'actual_corruption.gz')
    except AssertionError:actual_fault=True
    else:raise AssertionError('injected retirement corruption accepted')
    params=dict(np.load(ROOT/'testdata/integer_v1/params/parameters.npz'));oracle=Encoder(params);rows=[]
    cases=[np.zeros(64,np.int8),np.full(64,127,np.int8),np.full(64,-127,np.int8),np.array([127,-127]*32,np.int8),np.array([127]*63+[-127],np.int8),np.array([1]*63+[2],np.int8)]
    for i in range(12):
        model=ExecutableLayer(params,out/f'bank_{i:02d}.gz',i);model.load(np.zeros((99,64),np.int8))
        peak=0
        for j in [1,2]:
            for case in cases:
                aa=np.stack([case,case]);bb=aa.copy();model.write_tensor(aa,'A',0,'token');model.write_tensor(bb,'A',1664,'token')
                model.norm(j,0,2,832)
                rr=oracle.residual(aa,bb,f'l{i:02d}_r{j}','check');expected=oracle.layernorm(rr,f'l{i:02d}_ln{j}','check')
                assert np.array_equal(model.peek('A',832,'token',64)[:2],expected)
        ln_cases=[np.zeros(64,np.int16),np.full(64,32767,np.int16),np.full(64,-32767,np.int16),
                  np.array([32767,-32767]*32,np.int16),np.array([32767]*63+[32766],np.int16),
                  np.array([32767]+[-32767]*63,np.int16)]
        for j in [1,2]:
            for case in ln_cases:
                rr=np.stack([case,case]);model.phase('ln_direct_boundary')
                for row in range(2):
                    for ch in range(64):model.b.tick([('C0',2880+row*64+ch,'w',int(rr[row,ch])&65535)],tag='LN_boundary_input')
                model.ln_rows(j,0,2,832)
                expected=oracle.layernorm(rr,f'l{i:02d}_ln{j}','check')
                assert np.array_equal(model.peek('A',832,'token',64)[:2],expected)
        sm=model.fetch(f'l{i:02d}_score_m');ss=model.fetch(f'l{i:02d}_score_s')
        scores=[np.zeros(99,np.int32),np.array([1032256]+[-1032256]*98,np.int32),np.array([1032256,1032256]+[-1032256]*97,np.int32),np.arange(-49,50,dtype=np.int32)*10000]
        for x in scores:
            got=model.score_row(x,sm,ss);expected=oracle.softmax(x[None,None,:],f'l{i:02d}_score','check')[0,0]
            assert np.array_equal(model.e.consume(got),expected);model.e.drop(got)
        model.e.drop(sm);model.e.drop(ss);model.b.trace.close();live=model.e.close()
        rows.append({'layer':i,'residual_LN_boundary_codes':len(cases)*2*2*64,'direct_S16_LN_boundary_codes':len(ln_cases)*2*2*64,'Softmax_boundary_codes':len(scores)*99,'peak_bytes':live['peak_bytes']})
        print('boundary profile',i,'pass',flush=True)
    summary={'passed':True,'early_use_guard':early,'wrong_result_audit_detected':wrong,'actual_retirement_fault_detected':actual_fault,'early_trace_detected':early_trace,'delay_9cycles_stalls_correctly':True,'profiles':rows,'peak_bytes':max(r['peak_bytes'] for r in rows)}
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
