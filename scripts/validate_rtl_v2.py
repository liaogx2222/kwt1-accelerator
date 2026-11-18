"""R17 implementation: actual RTL, bounded provider, independent configurations."""
import argparse,hashlib,json,os,subprocess,sys,time,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from rtl_v1_validation import run,hashes,BIN
from validate_layer_rtl import prepare,hexwords
from validate_kwt1_r1 import edge_input,boundary_oracle
from validate_kwt1_r2 import artifacts
from integer_model.runtime import Encoder
import numpy as np
VR=ROOT/'tools/rtl_v1_python/verilator';ZIG=ROOT/'tools/rtl_v1_python/ziglang/zig.exe'
SOURCES=[ROOT/'rtl/micro'/n for n in ['mul_pipe.sv','rne_pipe.sv']]+[ROOT/'rtl/v2'/n for n in ['kwt_sram_sp.sv','kwt_mac8x8.sv','kwt_iterative.sv','kwt_math.sv','kwt_packet_loader.sv','kwt_layer_banked.sv','kwt1_accel.sv']]
def build(out,top='kwt1_accel',single=1,version='v2',cpp='sim_accel.cpp'):
    out.mkdir(parents=True,exist_ok=True);os.environ['VERILATOR_ROOT']=str(VR);os.environ['ZIG_GLOBAL_CACHE_DIR']=str(ROOT/'tools/zig-cache')
    sources=[ROOT/'rtl'/version/p.name if p.parent==ROOT/'rtl/v2' else p for p in SOURCES]
    actual_top=top
    if top=='kwt1_mmio':sources.extend([ROOT/'rtl'/version/'kwt1_mmio.sv',ROOT/'rtl/v2/kwt1_observed.sv']);actual_top='kwt1_observed'
    main=ROOT/'rtl/v2'/cpp;extra=[ROOT/'rtl/v2/driver/kwt1.c',ROOT/'rtl/v2/driver/kwt1.h'] if cpp=='sim_provider.cpp' else []
    bound=hashes([*sources,main,*extra,ROOT/'rtl'/version/'generated/kwt_profile.svh'])
    stamp=dict(hashes=bound,top=top,single=single,version=version)
    if (out/'stamp.json').exists() and (out/'sim.exe').exists() and json.loads((out/'stamp.json').read_text())==stamp:return out/'sim.exe'
    defines=['-DKWT_SIM']+(['-DPIPELINED'] if version=='v2' else []);params=['-GSINGLE_LAYER='+str(single)] if top=='kwt1_accel' else []
    run([VR/'bin/verilator_bin.exe','--cc','--no-timing','--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC',*defines,'-I'+str(ROOT/'rtl'/version/'generated'),'--top-module',actual_top,'--prefix','V'+top,*params,'--Mdir',out,*sources],out)
    extra=[ROOT/'rtl/v2/driver/kwt1.c'] if cpp=='sim_provider.cpp' else []
    run([ZIG,'c++','-x','c++','-std=c++17','-O1','-I'+str(VR/'include'),'-I'+str(VR/'include/vltstd'),'-I'+str(out),'-o',out/'sim.exe',main,*extra,*out.glob('*.cpp'),VR/'include/verilated.cpp',VR/'include/verilated_threads.cpp'],out)
    (out/'source_hashes.json').write_text(json.dumps(bound,indent=2));(out/'stamp.json').write_text(json.dumps(stamp,indent=2));return out/'sim.exe'
def layer(out,quick):
    out.mkdir(parents=True,exist_ok=True);cases=prepare(out,quick)
    if not quick:
        _,p=artifacts();x=edge_input()
        for lid in range(12):
            i=len(cases);hexwords(out/f'input_{i:03d}.hex',x.tobytes());hexwords(out/f'expected_{i:03d}.hex',boundary_oracle(p,lid,x)['layernorm2_output'].tobytes());cases.append(dict(case=i,profile=lid,boundary=True))
        (out/'cases.txt').write_text(''.join(f'{c["case"]} {c["profile"]}\n' for c in cases));(out/'cases.json').write_text(json.dumps(cases,indent=2))
    exe=build(out/'build');result=run([exe,out,1],out);assert f'PASS cases={len(cases)}' in result
    shutil.copyfile(out/'build/source_hashes.json',out/'source_hashes.json')
    for c in cases:assert (out/f'observed_{c["case"]:03d}.hex').read_text()==(out/f'expected_{c["case"]:03d}.hex').read_text()
    (out/'summary.json').write_text(json.dumps(dict(passed=True,cases=cases,result=result),indent=2))
def full_fixtures(out,selected):
    out.mkdir(parents=True,exist_ok=True);packets,p=artifacts()
    for name,data in packets.items():hexwords(out/(name+'.hex'),data)
    labels=np.load(ROOT/'testdata/integer_v1/fixture/labels.npy');f=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r');saved=np.load(ROOT/'testdata/integer_v1/validation/encoder_output_int8.npy',mmap_mode='r')
    manifest=json.loads((ROOT/'testdata/integer_v1/params/manifest.json').read_text());names=json.loads((ROOT/'testdata/integer_v1/fixture/manifest.json').read_text())['label_names'];cases=[]
    for label in selected:
        sample=int(np.flatnonzero(labels==label)[0]);x=np.clip(np.rint(f[sample].astype(np.float64)/manifest['decode_scales']['encoder_input']),-127,127).astype(np.int8);y=Encoder(p)(x[None])[0];assert np.array_equal(y,saved[sample])
        hexwords(out/f'input_{label:03d}.hex',x.tobytes());hexwords(out/f'expected_{label:03d}.hex',y.tobytes());cases.append(dict(case=label,label=label,label_name=names[label],sample=sample,cold_packets=13))
    (out/'cases.txt').write_text(''.join(f'{c["case"]} 0\n' for c in cases));(out/'cases.json').write_text(json.dumps(cases,indent=2));return cases
def ledger(path,expected_launches):
    groups={}
    for line in path.read_text().splitlines():
        kind,*values=line.split();r=list(map(int,values));groups.setdefault(r[0],{}).setdefault(kind,[]).append(r[1:])
    for task,g in groups.items():
        t=g['T'][0];cyc,comp,rd,wr,issue,retire,mac,valid=t
        assert sum(r[1] for r in g['S'])==cyc and sum(r[1] for r in g['S'] if r[0]<256)==comp
        assert sum(r[2] for r in g['S'])==rd and sum(r[3] for r in g['S'])==wr
        assert sum(r[4] for r in g['S'])==issue and sum(r[5] for r in g['S'])==retire
        assert sum(r[1] for r in g['P'])==comp and sum(r[1] for r in g['B'])==comp
        assert sum(r[1] for r in g['O'])==mac==expected_launches and sum(r[2] for r in g['O'])==valid==80974080
    return groups
def provider(out,version,mode,quick=False,faults=False):
    out.mkdir(parents=True,exist_ok=True);selected=[0] if quick else ([0,4] if version=='v1' else list(range(12)));cases=full_fixtures(out,selected)
    exe=build(out.parent/('build_provider_'+version),'kwt1_mmio',0,version,'sim_provider.cpp')
    shutil.copyfile(exe.parent/'source_hashes.json',out/'source_hashes.json')
    cfg=dict(mode=mode,version=version,cpu_cycles_per_transaction=4 if mode=='system' else 0,supply_cycles_per_word=6 if mode=='system' else 0,supply_latency=1024 if mode=='system' else 0,input_supply_bytes=6336,core_pause='mod11/mod17' if mode=='stress' else 'none',memory_pause='mod7' if mode=='stress' else 'none',response_hold='5 cycles every 17 transactions' if mode=='stress' else 'none',final_response_hold=20,phase='restarted per cold task',timing_start='external: before input source-to-shared arrival, software abort and first provider request; RTL: first frame/input accept',timing_end='external: C driver returns after output stores and done read; RTL: final output bus response acknowledgement',is_E203_instruction_timing=False)
    (out/'config.json').write_text(json.dumps(cfg,indent=2));result=run([exe,out,mode,cfg['cpu_cycles_per_transaction'],cfg['supply_cycles_per_word'],cfg['supply_latency'],*(['faults'] if faults else []),'+metrics='+(out/'ledger.txt').as_posix()],out)
    assert f'PASS PROVIDER cases={len(cases)} codes={len(cases)*6336}' in result
    for c in cases:assert (out/f'provider_observed_{c["case"]:03d}.hex').read_text()==(out/f'expected_{c["case"]:03d}.hex').read_text()
    groups=ledger(out/'ledger.txt',6470592 if version=='v1' else 1335360)
    metrics=[list(map(int,line.split())) for line in (out/'provider_metrics.txt').read_text().splitlines()]
    assert len(metrics)==len(cases) and all(r[8]==13 and r[9]==61728 for r in metrics)
    (out/'ledger.json').write_text(json.dumps(groups,indent=2));(out/'summary.json').write_text(json.dumps(dict(passed=True,cases=cases,config=cfg,metrics=metrics,result=result,ledger_tasks=len(groups)),indent=2))

def unit(out,netlist=None):
    out.mkdir(parents=True,exist_ok=True)
    # Frozen independent integer vectors; additional paired/II=1 tests are in TB.
    for name in ['math.txt','iter.txt']:shutil.copyfile(ROOT/'testdata/rtl_v1/release/unit'/name,out/name)
    sources=([netlist] if netlist else SOURCES[:2]+[ROOT/'rtl/v2/kwt_math.sv'])+[ROOT/'rtl/v2'/n for n in ['kwt_sram_sp.sv','kwt_mac8x8.sv','kwt_iterative.sv','tb_units.sv']]
    (out/'source_hashes.json').write_text(json.dumps(hashes(sources),indent=2))
    if netlist:
        # Gate-level event simulation is expensive in the bundled old Icarus.
        # Use the same timed SV scoreboard with native Verilator for the netlist.
        os.environ['VERILATOR_ROOT']=str(VR);os.environ['ZIG_GLOBAL_CACHE_DIR']=str(ROOT/'tools/zig-cache')
        model=out/'build';model.mkdir(exist_ok=True)
        run([VR/'bin/verilator_bin.exe','--cc','--main','--timing','--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC','--top-module','tb_units','--Mdir',model,*sources],out)
        run([ZIG,'c++','-x','c++','-std=c++20','-DVL_TIME_CONTEXT','-O1','-I'+str(VR/'include'),'-I'+str(VR/'include/vltstd'),'-I'+str(model),'-o',model/'sim.exe',*model.glob('*.cpp'),VR/'include/verilated.cpp',VR/'include/verilated_threads.cpp',VR/'include/verilated_timing.cpp'],out)
        result=run([model/'sim.exe','+root='+out.as_posix()],out)
    else:
        run([BIN/'iverilog.exe','-g2012','-DKWT_SIM','-s','tb_units','-o',out/'unit.vvp',*sources],out)
        result=run([BIN/'vvp.exe',out/'unit.vvp','+root='+out.as_posix()],out)
    assert 'PASS math=2592 iterative=640' in result
    (out/'summary.json').write_text(json.dumps(dict(passed=True,result=result,post_synthesis=bool(netlist)),indent=2))

def stress(out):
    out.mkdir(parents=True,exist_ok=True);prepare(out,True);exe=build(out.parent/'layer/build')
    shutil.copyfile(exe.parent/'source_hashes.json',out/'source_hashes.json')
    result=run([exe,out,1,'stress'],out)
    assert 'STRESS PASS rejected=7 packet_resets=3 input_resets=1 execution_resets=8' in result and 'PASS cases=1 codes=6336' in result
    assert (out/'observed_000.hex').read_text()==(out/'expected_000.hex').read_text()
    (out/'summary.json').write_text(json.dumps(dict(passed=True,result=result,rejected=7,reset_scenarios=12),indent=2))

def cross(out):
    out.mkdir(parents=True,exist_ok=True);prepare(out,True);exe=build(out.parent/'layer/build')
    sources=[*SOURCES,ROOT/'rtl/v2/tb_accel.sv',ROOT/'rtl/v2/generated/kwt_profile.svh']
    (out/'source_hashes.json').write_text(json.dumps(hashes(sources),indent=2))
    run([BIN/'iverilog.exe','-g2012','-DKWT_SIM','-DCROSS_SMOKE','-I',ROOT/'rtl/v2/generated','-s','tb_accel','-o',out/'cross.vvp',*SOURCES,ROOT/'rtl/v2/tb_accel.sv'],out)
    result=run([BIN/'vvp.exe',out/'cross.vvp','+root='+out.as_posix(),'+trace='+(out/'icarus_trace.txt').as_posix()],out)
    assert 'PASS CROSS Attention Softmax PV residual LN row=0 codes=64' in result
    native=run([exe,out,1,'+trace='+(out/'native_trace.txt').as_posix()],out);assert 'PASS cases=1 codes=6336' in native
    from rtl_v1_trace_compare import compare
    compared=compare(out/'icarus_trace.txt',out/'native_trace.txt')
    assert all(v['first_difference'] is None and min(v['records'])>19008 for v in compared.values())
    (out/'summary.json').write_text(json.dumps(dict(passed=True,result=result,comparison=compared),indent=2))

def synth(out,post_only=False):
    out.mkdir(parents=True,exist_ok=True)
    for name in ([] if post_only else ['generic','math']):
        script=(ROOT/f'rtl/v2/synth_{name}.ys').read_text().replace('testdata/rtl_v2/synth',out.relative_to(ROOT).as_posix())
        (out/(name+'.ys')).write_text(script)
        run([sys.executable,ROOT/'scripts/run_yosys_v2.py','-Q','-q','-l',(out/(name+'.log')).relative_to(ROOT).as_posix(),'-s',(out/(name+'.ys')).relative_to(ROOT).as_posix()],out)
    unit(out/'post_math',out/'math_generic.v')
    (out/'source_hashes.json').write_text(json.dumps(hashes([*SOURCES,ROOT/'rtl/v2/kwt1_mmio.sv',ROOT/'rtl/v2/kwt_tech_sram_blackbox.sv',ROOT/'rtl/v2/generated/kwt_profile.svh',ROOT/'rtl/v2/synth_generic.ys',ROOT/'rtl/v2/synth_math.ys',ROOT/'scripts/run_yosys_v2.py']),indent=2))
    (out/'summary.json').write_text(json.dumps(dict(passed=True,flow='Yosys generic logic, external SRAM blackboxes, no target library'),indent=2))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',default='all',choices=['all','baseline','layer','provider','unit','stress','cross','synth','postmath','check']);ap.add_argument('--output',type=Path,default=ROOT/'testdata/rtl_v2/release');ap.add_argument('--quick',action='store_true');ap.add_argument('--mode',default='always',choices=['always','stress','system']);ap.add_argument('--version',default='v2',choices=['v1','v2']);ap.add_argument('--faults',action='store_true');a=ap.parse_args();a.output=a.output.resolve()
    if a.stage=='all' and a.quick:raise ValueError('--quick is for individual development stages')
    if a.stage!='check' and (a.output/'verification.json').exists():raise ValueError('released output exists; use a fresh --output')
    if a.stage=='layer':layer(a.output/'layer',a.quick)
    elif a.stage=='provider':provider(a.output/(a.version+'_'+a.mode),a.version,a.mode,a.quick,a.faults)
    elif a.stage=='unit':unit(a.output/'unit')
    elif a.stage=='stress':stress(a.output/'stress')
    elif a.stage=='cross':cross(a.output/'cross')
    elif a.stage=='synth':synth(a.output/'synth')
    elif a.stage=='postmath':synth(a.output/'synth',True)
    elif a.stage=='baseline':
        for mode in ['always','stress']:provider(a.output/('v1_'+mode),'v1',mode,False,False)
    elif a.stage=='check':
        from check_rtl_v2 import check
        check(a.output)
    elif a.stage=='all':
        unit(a.output/'unit');layer(a.output/'layer',False);stress(a.output/'stress');cross(a.output/'cross')
        for version in ['v1','v2']:
            for mode in (['always','stress'] if version=='v1' else ['always','stress','system']):provider(a.output/(version+'_'+mode),version,mode,False,version=='v2' and mode=='stress')
        synth(a.output/'synth')
        from check_rtl_v2 import check
        check(a.output)
    else:raise NotImplementedError(a.stage)
if __name__=='__main__':main()
