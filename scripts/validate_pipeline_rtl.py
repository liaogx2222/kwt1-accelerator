"""Exact elastic handshake replay, independent bigint expected values."""
import argparse,hashlib,json,random,subprocess,sys
import numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from integer_model.pipeline_contract import ElasticPipeline,multiply,rounding,MASK,PIPELINE_STORAGE_BYTES
from validate_arithmetic_rtl import oracle

def fixed_RQ():
    from integer_model.runtime import Encoder,shift_rne,rne
    p=dict(np.load(ROOT/'testdata/integer_v1/params/parameters.npz'));meta=json.loads((ROOT/'testdata/integer_v1/params/manifest.json').read_text())
    x=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r')[187:188]
    x=np.clip(np.rint(x.astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
    taps={};Encoder(p,lambda n,v,c:taps.update({n:v.copy()}))(x);rows=[]
    for layer in range(12):
        key=f'l{layer:02d}';prefix=f'layer_{layer:02d}/'
        for short,long in [('q','q_projection'),('k','k_projection'),('v','v_projection'),('o','attention_output_projection'),('fc1','ffn_dense1_output'),('fc2','ffn_dense2_output')]:
            values=taps[prefix+long+'/accumulator'][0,0]
            for c in range(8):rows.append((1,int(values[c])&MASK,int(p[key+'_'+short+'_m'][c]),int(p[key+'_'+short+'_s'][c]),8))
        score=taps[prefix+'attention_score_raw'][0,0];diff=score-score.max()
        for c in range(8):rows.append((1,int(diff[c])&MASK,int(p[key+'_score_m'].item()),int(p[key+'_score_s'].item()),0))
        for j in (1,2):
            lk=key+f'_ln{j}';r=taps[prefix+f'residual{j}_sum'][0,0].astype(np.int64)
            su=int(r.sum());v=64*int((r*r).sum())-su*su
            import math
            inv=int(rne(1<<40,math.isqrt((v<<16)+int(p[lk+'_eps']))))
            z=shift_rne((64*r-su)*inv,18);aff=shift_rne(z*p[lk+'_g'],14)+p[lk+'_b']
            for c in range(8):rows.append((1,int(aff[c])&MASK,int(p[lk+'_m']),int(p[lk+'_s']),8))
    return rows

def vectors(mode,out):
    rng=random.Random(20261021);pipe=ElasticPipeline(mode);rows=[];held=None;tag=0;accepted=responses=canceled=stalls=0;burst=0;longest=0
    # Reuse all previously frozen mul/RNE boundary vectors as a request queue.
    frozen=ROOT/'testdata/r1r2/release/rtl/vectors.txt'
    legacy=[]
    for line in frozen.read_text().splitlines():
        op,a,b,s,q,r,e=line.split();op=int(op)
        if mode=='mul' and op in (0,1):legacy.append((int(op==0),int(a,16),int(b,16),int(s),0))
        elif mode=='rne' and op==2:legacy.append((1,int(a,16),0,int(s),0))
    legacy_count=len(legacy);fixed=fixed_RQ() if mode=='rq' else []
    legacy+=fixed
    index=0
    for t in range(6500):
        reset=t in (0,1,2400,2401,4700)
        sink=True if t<1200 or t>6300 else rng.randrange(7)>1
        if reset:
            canceled+=sum(x is not None for x in pipe.slots);held=None
        if not reset and held is None and t<6200 and (t<1200 or rng.randrange(9)>0):
            if index<len(legacy):sgn,a,b,shift,sat=legacy[index];index+=1
            else:
                sgn=1 if mode!='mul' else rng.randrange(2)
                a=rng.randrange(-(1<<31),1<<31)&MASK if sgn else rng.getrandbits(32)
                b=rng.randrange(-(1<<31),1<<31)&MASK if sgn else rng.getrandbits(32)
                shift=rng.choice([-128,-64,-1,0,1,2,14,18,31,36,40,46,63,64,127]);sat=rng.choice([0,8,16])
                if mode=='rne':a=rng.getrandbits(64)
            if mode=='mul':result,error=multiply(a,b,sgn)
            elif mode=='rne':result,error=rounding(a,shift,sat)
            else:
                product,error=multiply(a,b,sgn);result,error=rounding(product,shift,sat,error)
            held=(sgn,a,b,shift,sat,tag,result,int(error));tag+=1
        request=held
        ready,response=pipe.cycle(reset,request,sink)
        item=held or (0,0,0,0,0,0,0,0);sgn,a,b,shift,sat,tt,_,_=item
        rows.append(f'{int(not reset)} {int(held is not None)} {sgn} {a:016x} {b:016x} {shift} {sat} {tt} {int(sink)} {int(ready)} {int(response is not None)} {(response[6] if response else 0):016x} {response[7] if response else 0} {response[5] if response else 0}\n')
        if ready and held is not None:accepted+=1;held=None;burst+=1;longest=max(longest,burst)
        else:
            if held:stalls+=1
            burst=0
        if response is not None and sink:responses+=1
    assert not any(pipe.slots) and held is None and accepted==responses+canceled
    assert longest>=256
    path=out/f'{mode}.txt';path.write_text(''.join(rows),encoding='ascii')
    return dict(cycles=len(rows),accepted=accepted,responses=responses,reset_canceled=canceled,request_stalls=stalls,
                consecutive_accepts=longest,legacy_vectors=legacy_count,fixed_profile_RQ_vectors=len(fixed),vector_sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--quick',action='store_true');a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    bin=Path('E:/project/FPGAcompetition/RISCV_CPU/tools/iverilog/bin');iv=str(bin/'iverilog.exe');vv=str(bin/'vvp.exe')
    binary=a.output/'pipeline.vvp';logs=[]
    def run(cmd):
        r=subprocess.run(cmd,capture_output=True,text=True);logs.append(dict(command=cmd,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
        (a.output/'tool_log.json').write_text(json.dumps(logs,indent=2),encoding='utf-8')
        if r.returncode:raise RuntimeError(r.stdout+r.stderr)
        return r.stdout
    run([iv,'-g2012','-s','tb_pipeline','-o',str(binary),*[str(ROOT/'rtl/micro'/n) for n in ['mul_pipe.sv','rne_pipe.sv','rq_pipe.sv','tb_pipeline.sv']]])
    stats={}
    for i,mode in enumerate(['mul','rne','rq']):
        stats[mode]=vectors(mode,a.output)
        result=run([vv,str(binary),'+mode='+str(i),'+vectors='+str((a.output/f'{mode}.txt').resolve()).replace('\\','/')]);assert 'PASS' in result;print(result,flush=True)
    iterative=[]
    # Same-op prefix explicitly checks 64/32 initiation intervals without gaps.
    for op in (3,4):
        for i in range(16):
            x=(1<<63)+i;d=12345;q,r,e=oracle(op,x,d,0);iterative.append((op,x,d,q,r,e,64 if op==3 else 32))
    for line in (ROOT/'testdata/r1r2/release/rtl/vectors.txt').read_text().splitlines():
        op,x,y,s,q,r,e=line.split();op=int(op)
        if op not in (3,4):continue
        iterative.append((op,int(x,16),int(y,16),int(q,16),int(r,16),int(e),2 if int(e) else (64 if op==3 else 32)))
    path=a.output/'iterative.txt';path.write_text(''.join(f'{op} {x:016x} {y:016x} {q:016x} {r:016x} {e} {lat}\n' for op,x,y,q,r,e,lat in iterative),encoding='ascii')
    binary=a.output/'iterative.vvp'
    run([iv,'-g2012','-s','tb_iterative_cycles','-o',str(binary),str(ROOT/'rtl/micro/wide_arith.sv'),str(ROOT/'rtl/micro/tb_iterative_cycles.sv')])
    iterative_result=run([vv,str(binary),'+vectors='+str(path.resolve()).replace('\\','/')]);assert 'PASS iterative' in iterative_result;print(iterative_result,flush=True)
    if not a.quick:
        run([sys.executable,str(ROOT/'scripts/validate_arithmetic_rtl.py'),'--output',str(a.output/'legacy')])
    result=dict(passed=True,resources={'mul':dict(latency=3,II=1),'rne':dict(latency=1,II=1),'rq_chain':dict(latency=4,II=1),
                                      'divider':dict(latency=64,II=64),'sqrt':dict(latency=32,II=32)},
                reset='cancels all slots, never produces stale tag',pipelines=stats,RQ_physical_pipeline_bytes=PIPELINE_STORAGE_BYTES,
                iterative_vectors=len(iterative),iterative_result=iterative_result,legacy_1818_retested=not a.quick,scope='logic and cycle contract only; no library PPA')
    (a.output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
if __name__=='__main__':main()
