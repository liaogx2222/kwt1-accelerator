"""Actual banked RTL simulations; canonical packets are the only DUT parameters."""
import argparse,hashlib,json,subprocess,sys,time,random,math,os
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from validate_layer_rtl import prepare,hexwords
from validate_kwt1_r2 import artifacts
from integer_model.runtime import Encoder
from validate_kwt1_r1 import boundary_oracle,edge_input
BIN=Path(os.environ.get('KWT_IVERILOG_BIN','E:/project/FPGAcompetition/RISCV_CPU/tools/iverilog/bin'))
SOURCES=[ROOT/'rtl/micro'/x for x in ['mul_pipe.sv','rne_pipe.sv']]+[ROOT/'rtl/v1'/x for x in ['kwt_sram_sp.sv','kwt_mac8x8.sv','kwt_iterative.sv','kwt_math.sv','kwt_packet_loader.sv','kwt_layer_banked.sv','kwt1_accel.sv']]
def hashes(paths):return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
def bind(out,paths):(out/'source_hashes.json').write_text(json.dumps(hashes(paths),indent=2))
def run(cmd,out):
    r=subprocess.run([str(x) for x in cmd],capture_output=True,text=True)
    with (out/'tools.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(command=[str(x) for x in cmd],exit=r.returncode,stdout=r.stdout,stderr=r.stderr))+'\n')
    print(r.stdout,flush=True)
    if r.returncode:raise RuntimeError(r.stdout+r.stderr)
    return r.stdout
def units(out):
    out.mkdir(parents=True,exist_ok=True);rng=random.Random(20261022);mask=(1<<64)-1;lines=[]
    def rounded(x,s,sat):
        bad=x==-(1<<63)
        mag=abs(x)
        if s<0:
            q=mag<<(-s);bad|=q>mask//2
        elif s==0:q=mag
        elif s<64:
            q,r=divmod(mag,1<<s);q+=r>(1<<(s-1)) or (r==(1<<(s-1)) and q%2)
        else:q=0
        if sat:q=min(q,(1<<(sat-1))-1)
        return (0 if bad else (-q if x<0 else q))&mask,int(bad)
    for op in [0,1,2,3]:
        for i in range(600):
            a=rng.randrange(-(1<<31),1<<31);b=rng.randrange(-(1<<31),1<<31);s=0;sat=0
            if op==1:a=rng.getrandbits(32);b=rng.getrandbits(32)
            if op==2:
                a=rng.randrange(-(1<<63)+1,1<<63);s=rng.choice([-3,-1,0,1,2,31,32,47,63,64,70]);sat=rng.choice([0,8,16])
            if op==3:b=rng.randrange(1,1<<31);s=rng.randrange(0,64);sat=rng.choice([0,8,16])
            if i<8:
                if op==0:a=[-(1<<31),(1<<31)-1,-1,0,1,-(1<<31),(1<<31)-1,1<<40][i];b=[-(1<<31),(1<<31)-1,-1,1,0,1,-(1<<31),1][i]
                elif op==1:a=[0,1,(1<<32)-1,1<<31,(1<<32)-1,17,1<<31,1<<40][i];b=[0,(1<<32)-1,(1<<32)-1,1<<31,1,19,(1<<32)-1,1][i]
                elif op==2:a=[-(1<<63),(1<<63)-1,3,5,7,-3,-5,-7][i];s=[0,0,1,1,1,1,1,1][i];sat=0
                else:a=[3,5,7,-3,-5,-7,(1<<31)-1,1<<40][i];b=1;s=1;sat=0
            invalid=(not(-(1<<31)<=a<(1<<31) and -(1<<31)<=b<(1<<31))) if op in [0,3] else (not(0<=a<1<<32 and 0<=b<1<<32)) if op==1 else False
            if invalid:result=0;err=1
            elif op<2:result=(a*b)&mask;err=0
            else:result,err=rounded(a if op==2 else a*b,s,sat)
            lines.append(f'{op:x} {a&mask:016x} {b&mask:016x} {s&255:02x} {sat:02x} {result:016x} {err:x}\n')
    (out/'math.txt').write_text(''.join(lines));lines=[]
    for mode in [0,1]:
        for i in range(320):
            a=[0,1,2,3,4,mask,1<<63,(1<<32)-1][i] if i<8 else rng.getrandbits(64)
            b=[0,1,2,3,mask,1<<63,(1<<32)-1,17][i] if i<8 else rng.getrandbits(64)
            result=math.isqrt(a) if mode else (a//b if b else 0)
            rem=a-result*result if mode else (a%b if b else 0)
            err=int(not mode and b==0);lat=32 if mode else (1 if err else 64)
            lines.append(f'{mode:x} {a:016x} {b:016x} {result:016x} {rem:016x} {err:x} {lat}\n')
    (out/'iter.txt').write_text(''.join(lines));binary=out/'unit.vvp'
    bind(out,[*SOURCES[:6],ROOT/'rtl/v1/tb_units.sv'])
    run([BIN/'iverilog.exe','-g2012','-DKWT_SIM','-s','tb_units','-o',binary,*SOURCES[:2],*SOURCES[2:6],ROOT/'rtl/v1/tb_units.sv'],out)
    result=run([BIN/'vvp.exe',binary,'+root='+out.as_posix()],out);assert 'PASS math=2464 iterative=640' in result
    (out/'summary.json').write_text(json.dumps(dict(passed=True,result=result),indent=2))
def simulate(stage,out,quick,icarus=False):
    out.mkdir(parents=True,exist_ok=True)
    if stage=='layer':
        cases=prepare(out,quick)
        if not quick:
            _,p=artifacts();x=edge_input()
            for layer in range(12):
                index=len(cases);taps=boundary_oracle(p,layer,x);y=taps['layernorm2_output']
                hexwords(out/f'input_{index:03d}.hex',x.tobytes());hexwords(out/f'expected_{index:03d}.hex',y.tobytes());cases.append(dict(case=index,profile=layer,boundary=True))
            (out/'cases.txt').write_text(''.join(f'{c["case"]} {c["profile"]}\n' for c in cases));(out/'cases.json').write_text(json.dumps(cases,indent=2))
    else:
        packets,p=artifacts()
        for name,data in packets.items():hexwords(out/(name+'.hex'),data)
        meta=json.loads((ROOT/'testdata/integer_v1/params/manifest.json').read_text());fixture=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r')
        cases=[]
        for case,sample in enumerate([187] if quick else [187,4444]):
            x=np.clip(np.rint(fixture[sample].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
            y=Encoder(p)(x[None])[0]
            hexwords(out/f'input_{case:03d}.hex',x.tobytes());hexwords(out/f'expected_{case:03d}.hex',y.tobytes());cases.append(dict(case=case,profile=0,sample=sample))
        (out/'cases.txt').write_text(''.join(f'{c["case"]} 0\n' for c in cases))
        (out/'cases.json').write_text(json.dumps(cases,indent=2))
    if icarus:
        binary=out/'sim.vvp'
        run([BIN/'iverilog.exe','-g2012','-DKWT_SIM',*(['-DFULL_MODEL'] if stage=='full' else []),'-I',ROOT/'rtl/v1/generated','-s','tb_accel','-o',binary,*SOURCES,ROOT/'rtl/v1/tb_accel.sv'],out)
        start=time.time();result=run([BIN/'vvp.exe',binary,'+root='+out.as_posix(),'+trace='+(out/'math_trace.txt').as_posix()],out)
        assert f'PASS cases={len(cases)}' in result
        (out/'summary.json').write_text(json.dumps(dict(passed=True,cases=cases,result=result,elapsed=time.time()-start),indent=2));return
    native=out.parent/('native_'+stage);native.mkdir(parents=True,exist_ok=True)
    vr=ROOT/'tools/rtl_v1_python/verilator';zig=ROOT/'tools/rtl_v1_python/ziglang/zig.exe'
    os.environ['VERILATOR_ROOT']=str(vr);os.environ['ZIG_GLOBAL_CACHE_DIR']=str(ROOT/'tools/zig-cache')
    bind(out,[*SOURCES,ROOT/'rtl/v1/generated/kwt_profile.svh',ROOT/'rtl/v1/sim_accel.cpp'])
    run([vr/'bin/verilator_bin.exe','--cc','--no-timing','--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC','-DKWT_SIM','-I'+str(ROOT/'rtl/v1/generated'),'--top-module','kwt1_accel','-GSINGLE_LAYER='+str(int(stage=='layer')),'--Mdir',native,*SOURCES],out)
    binary=native/'sim.exe'
    run([zig,'c++','-std=c++17','-O1','-I'+str(vr/'include'),'-I'+str(vr/'include/vltstd'),'-I'+str(native),'-o',binary,ROOT/'rtl/v1/sim_accel.cpp',*native.glob('*.cpp'),vr/'include/verilated.cpp',vr/'include/verilated_threads.cpp'],out)
    start=time.time();result=run([binary,out,int(stage=='layer')],out)
    assert f'PASS cases={len(cases)}' in result
    observed=[]
    for c in cases:
        a=(out/f'observed_{c["case"]:03d}.hex').read_text().split();b=(out/f'expected_{c["case"]:03d}.hex').read_text().split();assert len(a)==1584 and a==b
        observed.append(hashlib.sha256(bytes.fromhex(''.join(a))).hexdigest())
    summary=dict(passed=True,stage=stage,quick=quick,cases=cases,output_codes=len(cases)*6336,mismatches=0,elapsed=time.time()-start,result=result,observed_hashes=observed)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
def mmio(out,fixtures):
    out.mkdir(parents=True,exist_ok=True);native=out.parent/'native_mmio';native.mkdir(parents=True,exist_ok=True)
    vr=ROOT/'tools/rtl_v1_python/verilator';zig=ROOT/'tools/rtl_v1_python/ziglang/zig.exe'
    os.environ['VERILATOR_ROOT']=str(vr);os.environ['ZIG_GLOBAL_CACHE_DIR']=str(ROOT/'tools/zig-cache')
    bind(out,[*SOURCES,ROOT/'rtl/v1/generated/kwt_profile.svh',ROOT/'rtl/v1/kwt1_mmio.sv',ROOT/'rtl/v1/sim_mmio.cpp',ROOT/'rtl/v1/driver/kwt1.h',ROOT/'rtl/v1/driver/kwt1.c'])
    run([vr/'bin/verilator_bin.exe','--cc','--no-timing','--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC','-DKWT_SIM','-I'+str(ROOT/'rtl/v1/generated'),'--top-module','kwt1_mmio','--Mdir',native,*SOURCES,ROOT/'rtl/v1/kwt1_mmio.sv'],out)
    binary=native/'sim.exe'
    run([zig,'c++','-x','c++','-std=c++17','-O1','-I'+str(vr/'include'),'-I'+str(vr/'include/vltstd'),'-I'+str(native),'-o',binary,ROOT/'rtl/v1/sim_mmio.cpp',ROOT/'rtl/v1/driver/kwt1.c',*native.glob('*.cpp'),vr/'include/verilated.cpp',vr/'include/verilated_threads.cpp'],out)
    start=time.time();result=run([binary,fixtures],out);assert 'PASS MMIO C-driver cases=2 codes=12672' in result
    for c in json.loads((fixtures/'cases.json').read_text()):
        assert (fixtures/f'mmio_observed_{c["case"]:03d}.hex').read_text()==(fixtures/f'expected_{c["case"]:03d}.hex').read_text()
    (out/'summary.json').write_text(json.dumps(dict(passed=True,result=result,cases=2,output_codes=12672,mismatches=0,elapsed=time.time()-start),indent=2))
def stress(out,fixtures):
    out.mkdir(parents=True,exist_ok=True);prepare(out,True);bind(out,[*SOURCES,ROOT/'rtl/v1/sim_accel.cpp'])
    result=run([out.parent/'native_layer/sim.exe',out,1,'stress'],out)
    assert 'STRESS PASS rejected=7 packet_resets=3 input_resets=1 execution_resets=5' in result and 'PASS cases=1 codes=6336' in result
    (out/'summary.json').write_text(json.dumps(dict(passed=True,result=result,rejected=7,reset_scenarios=9,recovery_output_codes=6336),indent=2))
def cross(out):
    out.mkdir(parents=True,exist_ok=True);prepare(out,True);binary=out/'cross.vvp'
    bind(out,[*SOURCES,ROOT/'rtl/v1/tb_accel.sv'])
    run([BIN/'iverilog.exe','-g2012','-DKWT_SIM','-DCROSS_SMOKE','-I',ROOT/'rtl/v1/generated','-s','tb_accel','-o',binary,*SOURCES,ROOT/'rtl/v1/tb_accel.sv'],out)
    result=run([BIN/'vvp.exe',binary,'+root='+out.as_posix(),'+trace='+(out/'icarus_trace.txt').as_posix()],out)
    assert 'PASS CROSS Attention Softmax PV residual LN row=0 codes=64' in result
    native=run([out.parent/'native_layer/sim.exe',out,1,'+trace='+(out/'native_trace.txt').as_posix()],out);assert 'PASS cases=1 codes=6336' in native
    from rtl_v1_trace_compare import compare
    compared=compare(out/'icarus_trace.txt',out/'native_trace.txt')
    assert all(v['first_difference'] is None and v['records'][0]>19008 for v in compared.values())
    (out/'summary.json').write_text(json.dumps(dict(passed=True,result=result,comparison=compared,scope='Icarus Q/K/V and first complete Attention/Softmax/PV/residual/LN row versus golden; operation streams agree with native simulator prefix'),indent=2))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('stage');ap.add_argument('--output',type=Path,required=True);ap.add_argument('--quick',action='store_true');ap.add_argument('--icarus',action='store_true');a=ap.parse_args()
    if a.stage=='unit':units(a.output/'unit')
    elif a.stage=='mmio':mmio(a.output/'mmio',a.output/'full')
    elif a.stage=='stress':stress(a.output/'stress',a.output/'layer')
    elif a.stage=='cross':cross(a.output/'cross')
    elif a.stage=='check':
        from check_rtl_v1 import check
        check(a.output)
    elif a.stage in ['layer','full']:simulate(a.stage,a.output/a.stage,a.quick,a.icarus)
    elif a.stage=='all':
        units(a.output/'unit')
        for stage in ['layer','full']:simulate(stage,a.output/stage,a.quick)
        mmio(a.output/'mmio',a.output/'full')
        stress(a.output/'stress',a.output/'layer')
        cross(a.output/'cross')
        from check_rtl_v1 import check
        check(a.output)
    else:raise NotImplementedError(a.stage)
if __name__=='__main__':main()
