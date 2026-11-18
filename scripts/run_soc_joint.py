"""Full E203 subsystem + current accelerator: CPU loads and shared output."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
CPU=ROOT.parent/'e203_hbirdv2'
SOC=ROOT/'rtl/soc_joint'
sys.path.insert(0,str(ROOT/'firmware/soc_joint'))
from assemble import assemble

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def run(cmd, log, cwd=ROOT):
    p=subprocess.run([str(v) for v in cmd],cwd=cwd,capture_output=True,text=True)
    log.write_text(p.stdout+p.stderr,encoding='utf-8')
    if p.returncode: raise RuntimeError(str(log)+': '+p.stderr[-1400:])
    return p.stdout

def sources():
    cpu=[p for p in sorted((CPU/'rtl/e203').rglob('*.v')) if p.name not in ['sirv_mrom.v','sirv_mrom_top.v']]
    accel=[ROOT/n for n in ['rtl/micro/mul_pipe.sv','rtl/micro/rne_pipe.sv']]+[
        ROOT/'rtl/v2'/n for n in ['kwt_sram_sp.sv','kwt_mac8x8.sv','kwt_iterative.sv','kwt_math.sv','kwt_packet_loader.sv','kwt_layer_banked.sv','kwt1_accel.sv','kwt1_mmio.sv']]
    return cpu+accel+[SOC/n for n in ['sirv_mrom_top.v','kwt_soc_icb_bridge.sv','kwt_soc_shared_sram.sv','kwt_soc_joint.sv','tb_soc_joint.sv']]

def build(out, unit=False, native=False):
    vr=ROOT/'tools/rtl_v1_python/verilator'; zig=ROOT/'tools/rtl_v1_python/ziglang/zig.exe'
    os.environ['VERILATOR_ROOT']=str(vr);os.environ['ZIG_GLOBAL_CACHE_DIR']=str(ROOT/'tools/zig-cache')
    model=out/'model';model.mkdir(parents=True,exist_ok=True)
    source=([ROOT/'rtl/v2/kwt_sram_sp.sv',SOC/'kwt_soc_shared_sram.sv',SOC/'kwt_soc_icb_bridge.sv',SOC/'tb_soc_interfaces.sv'] if unit else sources())
    if native: source=[p for p in source if p.name!='tb_soc_joint.sv']+[SOC/'kwt_soc_observed.sv']
    stamp={str(p):sha(p) for p in source+[ROOT/'rtl/v2/generated/kwt_profile.svh']}
    if native:stamp[str(SOC/'sim_soc.cpp')]=sha(SOC/'sim_soc.cpp')
    exe=model/'sim.exe'
    if (model/'sources.json').exists() and json.loads((model/'sources.json').read_text())==stamp and exe.exists():return exe
    includes=sorted({p.parent for p in (CPU/'rtl/e203').rglob('*.v')})+[ROOT/'rtl/v2/generated']
    run([vr/'bin/verilator_bin.exe','--cc',*(['--no-timing'] if native else ['--main','--timing']),'--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC',
         '-DFPGA_SOURCE','-DKWT_SIM','-DDISABLE_SV_ASSERTION',*['-I'+str(p) for p in includes],
         '--top-module','kwt_soc_observed' if native else 'tb_soc_interfaces' if unit else 'tb_soc_joint','--Mdir',model,'--output-split','16000',*source],out/'verilate.log')
    cpp=sorted(model.glob('*.cpp'))+[vr/'include/verilated.cpp',vr/'include/verilated_threads.cpp']+([SOC/'sim_soc.cpp'] if native else [vr/'include/verilated_timing.cpp'])
    def one(item):
        i,p=item;obj=model/('p%d.o'%i)
        run([zig,'c++','-std=c++20','-DVL_TIME_CONTEXT','-O3' if native else '-O1','-I'+str(vr/'include'),'-I'+str(vr/'include/vltstd'),'-I'+str(model),'-c',p,'-o',obj],model/('compile%d.log'%i))
        print('COMPILED %d/%d'%(i+1,len(cpp)),flush=True)
        return obj
    with ThreadPoolExecutor(max_workers=4) as pool: objs=list(pool.map(one,enumerate(cpp)))
    run([zig,'c++',*objs,'-o',exe],out/'link.log')
    (model/'sources.json').write_text(json.dumps(stamp,indent=2))
    return exe

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--cases',default='0')
    ap.add_argument('--build-only',action='store_true')
    ap.add_argument('--unit',action='store_true')
    ap.add_argument('--native',action='store_true')
    ap.add_argument('--supply-period',type=int,default=6)
    ap.add_argument('--model',type=Path)
    ap.add_argument('--reset-ln',action='store_true')
    ap.add_argument('--crc-reject',action='store_true')
    ap.add_argument('--sram-init',choices=['a5','zero'],default='a5')
    a=ap.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if (out/'summary.json').exists():raise ValueError('preserve published evidence')
    info=assemble(ROOT/'firmware/soc_joint/task.S',out/'bootrom.hex')
    (out/'rom.json').write_text(json.dumps(info,indent=2))
    if a.model:
        exe=a.model.resolve();bound=json.loads((exe.parent/'sources.json').read_text())
        assert a.native and all(sha(Path(p))==digest for p,digest in bound.items()),'stale SoC model'
    else:exe=build(out,a.unit,a.native)
    if a.sram_init!='a5':
        bound=json.loads((exe.parent/'sources.json').read_text())
        assert a.native and any(Path(p).name=='ramsp4096x16_ret1n.v' for p in bound),'initialization variant requires RET1N contract model'
    if a.build_only:return
    if a.unit:
        text=run([exe],out/'interfaces.log',out)
        assert 'PASS SOC_INTERFACES' in text
        (out/'summary.json').write_text(json.dumps(dict(passed=True,result=text),indent=2))
        print(text);return
    fixture=ROOT/'deliverables/local_port_20261103/fixtures'
    if a.native:
        cmd=[exe,out,fixture,a.cases,a.supply_period,*(['+RESET_LN'] if a.reset_ln else []),*(['+CRC_REJECT'] if a.crc_reject else []),*(['+KWT_SRAM_INIT_ZERO'] if a.sram_init=='zero' else []),'+ROMHEX='+(out/'bootrom.hex').as_posix()]
        with (out/'native.log').open('w') as f:p=subprocess.run([str(v) for v in cmd],cwd=out,stdout=f,stderr=subprocess.STDOUT)
        text=(out/'native.log').read_text()
        if p.returncode:raise RuntimeError(str(out/'native.log'))
        for case in map(int,a.cases.split(',')):
            assert 'PASS SOC case=%d '%case in text
            assert (out/('soc_observed_%03d.hex'%case)).read_bytes()==(fixture/('expected_%03d.hex'%case)).read_bytes()
        assert not a.reset_ln or 'SOC_RESET_IN_LN' in text
        assert not a.crc_reject or 'PASS SOC_CRC_REJECT' in text
        (out/'summary.json').write_text(json.dumps(dict(passed=True,cases=list(map(int,a.cases.split(','))),
            real_cpu=True,full_subsystem=True,consecutive_without_reset=True,supply_period=a.supply_period,
            boundary='first host input/common write through CPU completion store response',ROM_bytes=info['bytes'],
            reset_ln=a.reset_ln,crc_reject=a.crc_reject,sram_initialization=a.sram_init,area_mm2=None,soc_power_mW=None,physical_signoff=False),indent=2))
        inputs=[Path(p) for p in json.loads((exe.parent/'sources.json').read_text())]+[ROOT/'firmware/soc_joint/task.S',ROOT/'firmware/soc_joint/assemble.py',exe]
        (out/'source_hashes.json').write_text(json.dumps({str(p):sha(p) for p in inputs},indent=2))
        (out/'fixture_hashes.json').write_text(json.dumps({p.name:sha(p) for p in sorted(fixture.glob('*.hex'))},indent=2))
        print(text[-2200:]);return
    for case in map(int,a.cases.split(',')):
        log=out/('case%02d.log'%case)
        cmd=[exe,'+CASE='+str(case),'+FIXTURES='+fixture.as_posix(),'+ROMHEX='+(out/'bootrom.hex').as_posix()]
        with log.open('w') as f:
            p=subprocess.run([str(v) for v in cmd],cwd=out,stdout=f,stderr=subprocess.STDOUT)
        text=log.read_text()
        if p.returncode or 'RESULT: PASS case=%03d'%case not in text:raise RuntimeError(str(log))
        print(text[-2200:],flush=True)
    (out/'summary.json').write_text(json.dumps(dict(passed=True,cases=list(map(int,a.cases.split(','))),
        output='CPU stores to shared SRAM 0xa0022000; no host output injection',
        ROM_bytes=info['bytes'],core_scope='actual e203_subsys_top including bus and peripherals',
        area_mm2=None,soc_power_mW=None,physical_signoff=False),indent=2))

if __name__=='__main__':main()
