"""G1-G3 closure. Frozen v2 hardware/netlist; new host driver and test evidence."""
import argparse,concurrent.futures,hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from validate_rtl_v2 import VR,ZIG,SOURCES,full_fixtures,ledger
from rtl_v1_validation import hashes,run,BIN
I=ROOT/'rtl/integration'

def write(path,value):path.write_text(json.dumps(value,indent=2),encoding='utf-8')
def native(out,sources,main,driver,top='kwt1_mmio',gate=False,defines=()):
    out.mkdir(parents=True,exist_ok=True);os.environ['VERILATOR_ROOT']=str(VR);os.environ['ZIG_GLOBAL_CACHE_DIR']=str(ROOT/'tools/zig-cache')
    paths=[*sources,main,driver,driver.with_suffix('.h')];stamp=dict(source=hashes(paths),top=top,gate=gate,defines=list(defines))
    if (out/'stamp.json').exists() and json.loads((out/'stamp.json').read_text())==stamp and (out/'sim.exe').exists():return out/'sim.exe'
    run([VR/'bin/verilator_bin.exe','--cc','--no-timing','--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC','--output-split','16000','--output-split-cfuncs','500',*(['-DPIPELINED'] if not gate else []),'-I'+str(ROOT/'rtl/v2/generated'),'--top-module',top,'--prefix','Vkwt1_mmio','--Mdir',out,*sources],out)
    cpp=[main,driver,*out.glob('*.cpp'),VR/'include/verilated.cpp',VR/'include/verilated_threads.cpp'];objs=[]
    def compile_one(item):
        idx,source=item;obj=out/f'unit_{idx}.obj'
        args=[str(v) for v in [ZIG,'c++','-x','c++','-std=c++17','-O3' if gate else '-O1',*defines,'-I'+str(VR/'include'),'-I'+str(VR/'include/vltstd'),'-I'+str(out),'-c',source,'-o',obj]]
        proc=subprocess.run(args,capture_output=True,text=True)
        (out/f'compile_{idx}.log').write_text(proc.stdout+proc.stderr)
        if proc.returncode:raise RuntimeError(str(source)+'\n'+proc.stderr)
        print(f'COMPILED {idx+1}/{len(cpp)}',flush=True);return obj
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:objs=list(pool.map(compile_one,enumerate(cpp)))
    run([ZIG,'c++','-o',out/'sim.exe',*objs],out);write(out/'stamp.json',stamp);write(out/'source_hashes.json',stamp['source']);return out/'sim.exe'

def execute(exe,args,out):
    out.mkdir(parents=True,exist_ok=True);start=time.time();cmd=[str(v) for v in [exe,*args]];write(out/'command.json',cmd)
    with (out/'live.log').open('w') as log:result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
    text=(out/'live.log').read_text();print(text,flush=True)
    if result.returncode:raise RuntimeError(text)
    return dict(passed=True,elapsed=time.time()-start,result=text)

def gate(out):
    folder=out/'gate';folder.mkdir(parents=True,exist_ok=True);cases=full_fixtures(folder,[0,4])
    net=ROOT/'testdata/rtl_v2/release/synth/generic.v';exe=native(out/'build_gate',[net,I/'tech_sram_model.sv'],I/'sim_gate.cpp',ROOT/'rtl/v2/driver/kwt1.c',gate=True)
    result=execute(exe,[folder,'always',0,0,0],folder)
    assert 'PASS PROVIDER cases=2 codes=12672' in result['result'] and 'GATE RESET PASS' in result['result']
    for c in cases:assert (folder/f'provider_observed_{c["case"]:03d}.hex').read_bytes()==(folder/f'expected_{c["case"]:03d}.hex').read_bytes()
    write(folder/'summary.json',dict(**result,cases=cases,output_codes=12672,resets=['LN N_PASS in flight'],scope='entire existing generic gate netlist + 20 behavioral external macros, dynamic cold tasks and reset recovery; not formal equivalence'))
    write(folder/'source_hashes.json',json.loads((exe.parent/'source_hashes.json').read_text()))

def provider_model(out,legacy=False):
    return native(out/('build_legacy' if legacy else 'build_candidate'),[*SOURCES,ROOT/'rtl/v2/kwt1_mmio.sv',ROOT/'rtl/v2/kwt1_observed.sv'],I/'sim_provider.cpp',(ROOT/'rtl/v2/driver/kwt1.c') if legacy else I/'driver/kwt1.c',top='kwt1_observed',defines=['-DLEGACY_DRIVER'] if legacy else [])

def provider(out,name,cpu=8,beat=6,mode='system',legacy=False,selected=None,faults=False):
    folder=out/name;folder.mkdir(parents=True,exist_ok=True);cases=full_fixtures(folder,list(range(12)) if selected is None else selected);exe=provider_model(out,legacy)
    config=dict(legacy=legacy,mode=mode,cpu_extra_cycles=cpu,supply_cycles_per_word=beat,packet_latency=1024 if beat else 0,poll_backoff_cycles=0 if legacy else 64,is_E203_instruction_timing=False,input_supply_bytes=6336)
    write(folder/'config.json',config)
    result=execute(exe,[folder,mode,cpu,beat,config['packet_latency'],*(['faults'] if faults else []),'+metrics='+(folder/'ledger.txt').as_posix()],folder)
    assert f'PASS PROVIDER cases={len(cases)} codes={len(cases)*6336}' in result['result']
    groups=ledger(folder/'ledger.txt',1335360)
    assert len(groups)==len(cases)+(6 if legacy else 14)*(int(faults))
    metrics=[list(map(int,s.split())) for s in (folder/'provider_metrics.txt').read_text().splitlines()]
    assert len(metrics)==len(cases)
    for c,r in zip(cases,metrics):
        assert (folder/f'provider_observed_{c["case"]:03d}.hex').read_bytes()==(folder/f'expected_{c["case"]:03d}.hex').read_bytes()
        assert r[8:10]==[13,61728] and r[13:16]==[189328,1584,1584]
        assert r[12]==(189328 if legacy else 0),r
    write(folder/'summary.json',dict(**result,cases=cases,config=config,metrics=metrics,ledger_tasks=len(groups)))
    write(folder/'source_hashes.json',json.loads((exe.parent/'source_hashes.json').read_text()));return metrics

def drivers(out,quick=False):
    provider(out,'candidate_system',selected=[0] if quick else None)
    if not quick:
        provider(out,'candidate_always',0,0,'always');provider(out,'candidate_stress',0,0,'stress',faults=True)

def budget(out):
    rows=[]
    for cpu in [4,8,16]:
        for beat in [6,12]:
            pair={}
            for legacy in [True,False]:
                kind='legacy' if legacy else 'candidate';name=f'{kind}_cpu{cpu}_beat{beat}'
                metrics=provider(out,name,cpu,beat,legacy=legacy,selected=[0]);r=metrics[0]
                pair[kind]=dict(outer_cycles=r[6],transactions=r[7],status_reads=r[11],payload_status=r[12],param_words=r[13],idle_cycles=r[18])
            assert pair['legacy']['payload_status']==189328 and pair['candidate']['payload_status']==0
            rows.append(dict(cpu_extra_cycles=cpu,supply_cycles_per_word=beat,**pair))
    write(out/'budget.json',rows)

def protocols(out):
    folder=out/'protocols';folder.mkdir(parents=True,exist_ok=True);results={}
    for name,sources,defines in [
        ('mmio',[ROOT/'rtl/v2/kwt1_mmio.sv',I/'tb_mmio.sv'],[]),
        ('sram_behavior',[ROOT/'rtl/v2/kwt_sram_sp.sv',I/'tb_sram.sv'],[]),
        ('sram_macro_wrapper',[ROOT/'rtl/v2/kwt_sram_sp.sv',I/'tech_sram_model.sv',I/'tb_sram.sv'],['-DKWT_TECH_SRAM'])]:
        top='tb_mmio' if name=='mmio' else 'tb_sram';binary=folder/(name+'.vvp')
        run([BIN/'iverilog.exe','-g2012',*defines,'-s',top,'-o',binary,*sources],folder)
        text=run([BIN/'vvp.exe',binary],folder);assert 'PASS ' in text;results[name]=text
    run([ZIG,'c++','-x','c++','-std=c++17','-O1',I/'test_initial_bus_failure.cpp',I/'driver/kwt1.c','-o',folder/'driver_failure.exe'],folder)
    results['initial_bus_failure']=run([folder/'driver_failure.exe'],folder);assert 'PASS INITIAL BUS' in results['initial_bus_failure']
    write(folder/'summary.json',dict(passed=True,tests=results,MMIO_scope='production MMIO wrapper + controllable accelerator endpoint; full engine tested separately'))
    write(folder/'source_hashes.json',hashes([ROOT/'rtl/v2/kwt1_mmio.sv',ROOT/'rtl/v2/kwt_sram_sp.sv',I/'tech_sram_model.sv',I/'tb_mmio.sv',I/'tb_sram.sv',I/'test_initial_bus_failure.cpp',I/'driver/kwt1.c',I/'driver/kwt1.h']))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['all','software','gate','drivers','budget','protocols','check','check-software'],default='all');ap.add_argument('--quick',action='store_true');ap.add_argument('--output',type=Path,default=ROOT/'testdata/integration_v1/release');a=ap.parse_args();out=a.output.resolve()
    if a.stage=='all' and a.quick:raise ValueError('quick is development only')
    if a.stage!='check' and (out/'verification.json').exists():raise ValueError('released evidence exists; use a fresh output')
    if a.stage=='gate':gate(out)
    elif a.stage=='drivers':drivers(out,a.quick)
    elif a.stage=='budget':budget(out)
    elif a.stage=='protocols':protocols(out)
    elif a.stage=='software':protocols(out);drivers(out);budget(out)
    elif a.stage=='check':
        from check_integration import check
        check(out)
    elif a.stage=='check-software':
        from check_integration import check
        check(out,True)
    elif a.stage=='all':
        protocols(out);drivers(out);budget(out);gate(out)
        from check_integration import check
        check(out)
if __name__=='__main__':main()
