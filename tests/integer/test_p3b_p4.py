"""Independent exact-tail, packet identity, and per-cycle SRAM trace audit."""
import collections
import gzip
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from diagnose_kwt1_ln_full import Tail
from integer_model.hw_abi import unpack


def main():
    base=ROOT/'testdata';out=base/'p4b/banks_v3';rng=np.random.default_rng(20261020)
    for n in [1,2,99,100,101,2048,10000]:
        x=np.abs(rng.normal(size=n));tail=Tail(n)
        for block in np.array_split(x,min(13,n)):tail.add(block)
        assert abs(tail.result()-np.percentile(x,99))<1e-12
    meta=json.loads((base/'integer_v1/params/manifest.json').read_text())
    a,b=base/'p4a/hw_params',base/'p4a/hw_params_verified'
    pm=json.loads((b/'manifest.json').read_text());original=dict(np.load(base/'integer_v1/params/parameters.npz'))
    p={}
    for packet in pm['packets']:
        name=packet['file'];data=(b/name).read_bytes();assert data==(a/name).read_bytes()
        assert hashlib.sha256(data).hexdigest()==packet['sha256']
        layer=None if name=='common.bin' else int(name[6:8])
        p.update(unpack(data,pm['profile_sha256'],meta['array_schema'],layer))
    assert p.keys()==original.keys() and all(p[k].tobytes()==original[k].tobytes() for k in p)
    model=json.loads((out/'cycle_model.json').read_text());memory={};counts=collections.Counter();issues=0;cycles=0;maxbytes=0;pending=collections.Counter()
    stages={};last_qk=last_pv=-1;first_fc1=None;first_final_write=None
    with gzip.open(out/'bank_trace.jsonl.gz','rt',encoding='utf-8') as f:
        for line in f:
            row=json.loads(line);t=row['cycle'];assert t==cycles
            pending.pop(t,None)
            used=set();read=[];ops=row['ports'];maxbytes=max(maxbytes,2*len(ops))
            stages[row['stage']]=stages.get(row['stage'],0)+1
            for bank,addr,mode,value in ops:
                assert bank not in used;used.add(bank)
                assert 0<=addr<(8192 if bank.startswith('W') else 4096)
                key=(bank,addr);counts[(bank,mode)]+=1
                if mode=='r':read.append(memory.get(key,0xA5A5))
                else:memory[key]=value
            assert read==row.get('read_data_available_next_cycle',[])
            if row.get('arithmetic'):
                item=row['arithmetic'];assert item['unit']=='mul32' and item['retire_at']==t+4
                pending[t+4]+=1;issues+=1
            if row['stage']=='qk':last_qk=t
            if row['stage']=='pv':last_pv=t
            if row['stage']=='fc1' and first_fc1 is None:first_fc1=t
            if row['stage']=='residual_ln2' and any(op[0].startswith('A') and op[2]=='w' for op in ops) and first_final_write is None:first_final_write=t
            cycles+=1
    assert not pending
    assert cycles==model['trace_cycles'] and maxbytes==16
    assert stages==model['stage_total_cycles']
    expected=sum(n for name,n in model['wide_arithmetic_calls'].items() if 'reciprocal' not in name and name!='isqrt64')
    assert issues==expected
    assert first_fc1>max(last_qk,last_pv) and first_final_write>last_qk
    # Algebraically equivalent U64 normalization intermediate, including 2**63.
    em=np.concatenate([np.array([1 << 20],np.uint64),rng.integers(0,1 << 20,10000,dtype=np.uint64)])
    rr=np.concatenate([np.array([1 << 27],np.uint64),rng.integers(1,1 << 27,10000,dtype=np.uint64)])
    product=em*rr;intermediate=product << np.uint64(16);alt=intermediate-product
    assert int(intermediate[0])==1 << 63
    assert all(int(x)==65535*int(e)*int(r) for x,e,r in zip(alt,em,rr))
    result={'passed':True,'exact_p99_streaming_partitions':7,'ABI_roundtrip_arrays':len(p),'packet_bytes_unchanged_after_stricter_validation':True,
        'trace_cycles_replayed':cycles,'single_port_conflicts':0,'read_data_mismatches':0,'shared_multiplier_issues':issues,
        'all_multiplier_results_retired':True,'lifetime_checks':['K/V consumed before hidden writes','Q consumed before final Y writes'],
        'softmax_U64_reordering_cases':len(alt),'U64_intermediate_2pow63_tested':True,'max_request_bytes_per_cycle':maxbytes}
    (out/'independent_audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
