"""Deterministic independent integer vectors for the functional RTL prototype."""
import argparse
import hashlib
import json
import math
import random
import shutil
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MASK=(1<<64)-1


def oracle(op,a,b,s):
    signed=lambda x:x-(1<<64) if x>>63 else x
    if op==0:
        a,b=signed(a),signed(b)
        if not -(1<<31)<=a<(1<<31) or not -(1<<31)<=b<(1<<31):return 0,0,1
        return a*b&MASK,0,0
    if op==1:return (a*b,0,0) if max(a,b)<1<<32 else (0,0,1)
    if op==2:
        a=signed(a)
        if a==-(1<<63):return 0,0,1
        if s>=0:
            q,r=divmod(abs(a),1<<s);q+=int(2*r>(1<<s) or (2*r==(1<<s) and q%2))
        else:q=abs(a)<<-s
        if q>(1<<63)-1:return 0,0,1
        return (-q if a<0 else q)&MASK,0,0
    if op==3:return (*divmod(a,b),0) if b else (0,0,1)
    if op==4:
        q=math.isqrt(a);return q,a-q*q,0
    return 0,0,1


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'testdata/r1r2/rtl')
    ap.add_argument('--iverilog');ap.add_argument('--vvp');a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    rng=random.Random(20261020);rows=[]
    def add(op,x,y=0,s=0):rows.append((op,x&MASK,y&MASK,s,*oracle(op,x&MASK,y&MASK,s)))
    for x in [-(1<<31),-1,0,1,(1<<31)-1]:
        for y in [-(1<<31),-1,0,1,(1<<31)-1]:add(0,x,y)
    for x in [0,1,(1<<31),0xffffffff]:
        for y in [0,1,(1<<31),0xffffffff]:add(1,x,y)
    add(0,1<<32,1);add(1,1<<32,1)
    for s in [-128,-65,-64,-63,-1,0,1,2,15,31,62,63,64,127]:
        for x in [-(1<<63),-(1<<63)+1,-7,-5,-3,-1,0,1,3,5,7,(1<<63)-1]:add(2,x,s=s)
    for s in range(1,32):
        for q in [0,1,2,3,127]:
            for sign in [-1,1]:add(2,sign*((q<<s)+(1<<(s-1))),s=s)
    for x in [0,1,2,3,4,(1<<32)-1,1<<32,(1<<63),MASK]:
        for d in [0,1,2,3,(1<<32)-1,1<<32,(1<<63),MASK]:add(3,x,d)
    for r in [0,1,2,3,65535,65536,(1<<31),(1<<32)-1]:
        for delta in [-1,0,1]:
            if 0<=r*r+delta<=MASK:add(4,r*r+delta)
    add(4,MASK);add(7,1)
    for _ in range(1200):
        op=rng.randrange(5)
        if op==0:add(op,rng.randrange(-(1<<31),1<<31),rng.randrange(-(1<<31),1<<31))
        elif op==1:add(op,rng.getrandbits(32),rng.getrandbits(32))
        elif op==2:add(op,rng.randrange(-(1<<63)+1,1<<63),s=rng.randrange(-8,80))
        else:add(op,rng.getrandbits(64),rng.getrandbits(64))
    vectors=a.output/'vectors.txt';vectors.write_text(''.join(f'{op} {x:016x} {y:016x} {s} {q:016x} {r:016x} {e}\n' for op,x,y,s,q,r,e in rows),encoding='ascii')
    fallback=Path('E:/project/FPGAcompetition/RISCV_CPU/tools/iverilog/bin')
    iv=a.iverilog or shutil.which('iverilog') or str(fallback/'iverilog.exe')
    vv=a.vvp or shutil.which('vvp') or str(fallback/'vvp.exe')
    binary=a.output/'wide_arith.vvp'
    commands=[[iv,'-g2012','-s','tb_wide_arith','-o',str(binary),str(ROOT/'rtl/micro/wide_arith.sv'),str(ROOT/'rtl/micro/tb_wide_arith.sv')],
              [vv,str(binary),'+vectors='+str(vectors.resolve()).replace('\\','/')]]
    logs=[]
    for cmd in commands:
        run=subprocess.run(cmd,capture_output=True,text=True);logs.append({'command':cmd,'returncode':run.returncode,'stdout':run.stdout,'stderr':run.stderr})
        (a.output/'tool_log.json').write_text(json.dumps(logs,indent=2),encoding='utf-8')
        if run.returncode:raise RuntimeError(run.stdout+run.stderr)
    assert f'PASS vectors={len(rows)} ' in logs[-1]['stdout']
    result={'passed':True,'vectors':len(rows),'seed':20261020,'reset_tests':['mid_divide','held_response'],
        'tool_version':subprocess.run([iv,'-V'],capture_output=True,text=True).stdout.splitlines()[0],
        'vector_sha256':hashlib.sha256(vectors.read_bytes()).hexdigest(),
        'result':logs[-1]['stdout'],'scope':'functional only; one outstanding; not II=1 or library area/timing'}
    (a.output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
