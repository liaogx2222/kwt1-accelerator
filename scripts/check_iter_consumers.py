"""Existing independent math vectors plus PV-range RNE and iterative corners."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
MASK=(1<<64)-1

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def rounded(value, shift, sat):
    bad=value==-(1<<63);m=abs(value)
    if shift<0:q=m<<-shift;bad|=q>(1<<63)-1
    elif shift==0:q=m
    elif shift<64:
        q,r=divmod(m,1<<shift);q+=int(2*r>(1<<shift) or (2*r==(1<<shift) and q%2))
    else:q=0
    if sat:q=min(q,(1<<(sat-1))-1)
    return (0 if bad else (-q if value<0 else q))&MASK,int(bad)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--project',required=True,type=Path);ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
    p=a.project.resolve();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    original=ROOT.parent/'keyword-transformer/testdata/rtl_v1/release/unit'
    vectors=(original/'math.txt').read_text();base_count=len(vectors.splitlines());assert base_count==2400
    extra=[]
    for value in [-830459520,-32768,-7,-5,-3,-1,0,1,3,5,7,32767,830459520]:
        for mult in [0,1,127,32767,2147483647]:
            for shift in [-3,0,1,15,31,47,63,64]:
                for sat in [0,8,16]:
                    q,e=rounded(value*mult,shift,sat)
                    extra.append(f'3 {value&MASK:016x} {mult:016x} {shift&255:02x} {sat:02x} {q:016x} {e:x}\n')
    (out/'math.txt').write_text(vectors+''.join(extra))
    it=(original/'iter.txt').read_text();rows=[];rng=random.Random(20261114)
    for value in [1<<40,1<<47]:
        divisors=[0,1,2,3,4,7,65535,65536,(1<<32)-1,1<<32,value-1,value,value+1,1<<63,MASK]
        divisors += [rng.getrandbits(64) for _ in range(64)]
        for divisor in divisors:
            q,r=divmod(value,divisor) if divisor else (0,0)
            latency=1 if not divisor else 21 if value==1<<40 else 24
            rows.append(f'0 {value:016x} {divisor:016x} {q:016x} {r:016x} {int(not divisor):x} {latency}\n')
    for root in [0,1,2,3,65535,65536,1<<31,(1<<32)-1]:
        for delta in [-1,0,1]:
            value=root*root+delta
            if 0<=value<=MASK:
                q=math.isqrt(value);rows.append(f'1 {value:016x} 0000000000000000 {q:016x} {value-q*q:016x} 0 32\n')
    final_rows=[]
    for line in (it+''.join(rows)).splitlines():
        c=line.split();sm,aa,bb=int(c[0]),int(c[1],16),int(c[2],16)
        c[-1]=str(16 if sm else 1 if bb==0 else 11 if aa==1<<40 else 12 if aa==1<<47 else 64)
        final_rows.append(' '.join(c)+'\n')
    (out/'iter.txt').write_text(''.join(final_rows))
    tb=(ROOT/'rtl/v2/tb_units.sv').read_text()
    begin=tb.index(' reg load=');end=tb.index(' reg [4095:0]',begin);tb=tb[:begin]+tb[end:]
    begin=tb.index('  // Synchronous SRAM');end=tb.index('  // Homogeneous request',begin);tb=tb[:begin]+tb[end:]
    tb=tb.replace(';en=0;load=0;checking=0',';checking=0')
    tb=tb.replace('kwt_iterative it(', 'kwt_iterative #(.SHORT_CONST_DIV(1),.RADIX4_CONST(1),.RADIX16_CONST(1),.DOUBLE_SQRT(1)) it(')
    tb=tb.replace('taken==2400','taken=='+str(base_count+len(extra)))
    tb=tb.replace('[0:4095]', '[0:8191]')
    tb=tb.replace('PASS math=%0d iterative=%0d PE=64 SRAM=1 resets=5','PASS CONSUMERS math=%0d iterative=%0d resets=5')
    bench=out/'tb_consumers.sv';bench.write_text(tb)
    files=[p/n for n in ['rtl/micro/mul_pipe.sv','rtl/micro/rne_pipe.sv','rtl/v2/kwt_math.sv','rtl/v2/kwt_iterative.sv']]+[bench]
    iv=Path('C:/iverilog/bin/iverilog.exe');vv=iv.with_name('vvp.exe');exe=out/'sim.vvp'
    commands=[[iv,'-g2012','-s','tb_units','-o',exe,*files],[vv,exe,'+root='+out.as_posix()]]
    for cmd,name in zip(commands,['compile.log','run.log']):
        q=subprocess.run(list(map(str,cmd)),cwd=ROOT,capture_output=True,text=True)
        (out/name).write_text('returncode='+str(q.returncode)+'\n'+q.stdout+q.stderr);assert q.returncode==0,str(out/name)
    count=base_count+len(extra)+192;iter_count=len((out/'iter.txt').read_text().splitlines())
    assert f'PASS CONSUMERS math={count} iterative={iter_count} resets=5' in (out/'run.log').read_text()
    result=dict(passed=True,four_state=True,math_results=count,extra_PV_RNE_vectors=len(extra),iterative_vectors=iter_count,
        actual_SHORT_CONST_DIV=1,actual_RADIX4_CONST=1,actual_RADIX16_CONST=1,actual_DOUBLE_SQRT=1,reset_groups=5,held_results=True,
        source_sha256={str(x):sha(x) for x in files},original_vectors_sha256={str(original/n):sha(original/n) for n in ['math.txt','iter.txt']},
        vector_sha256={n:sha(out/n) for n in ['math.txt','iter.txt']},tool_sha256={str(x):sha(x) for x in [iv,vv]},
        commands=[[str(x) for x in cmd] for cmd in commands],scope='actual unchanged RNE and fast exact iterative consumer dependencies; not whole SoC/gate')
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print((out/'run.log').read_text())
