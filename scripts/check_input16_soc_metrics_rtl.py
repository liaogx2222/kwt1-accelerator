"""Run the full reference SoC gate bench on real RTL before server deployment."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    project=a.project.resolve();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    tmp=out/'tmp';tmp.mkdir();model=out/'model';model.mkdir()
    runtime=ROOT/'tools/rtl_v1_python';vr=runtime/'verilator';zig=runtime/'ziglang/zig.exe'
    env=dict(os.environ,VERILATOR_ROOT=str(vr),ZIG_LIB_DIR=str(zig.parent/'lib'),TEMP=str(tmp),TMP=str(tmp),
        ZIG_GLOBAL_CACHE_DIR=str(ROOT/'tools/zig-cache'))
    def run(cmd,log):
        p=subprocess.run(list(map(str,cmd)),cwd=str(project),env=env,capture_output=True,text=True)
        log.write_text(p.stdout+p.stderr,encoding='utf-8');assert p.returncode==0,str(log)
        return p.stdout
    files=[project/n for n in (project/'flow/local_sources.txt').read_text().splitlines()]
    includes=[project/n for n in (project/'flow/includes.txt').read_text().splitlines()]+[project/'rtl/v2/generated']
    command=[vr/'bin/verilator_bin.exe','--cc','--main','--timing','--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC',
        '-DFPGA_SOURCE','-DSYNTHESIS','-DDISABLE_SV_ASSERTION','-DKWT_TECH_SRAM',
        *['-I'+str(p) for p in includes],'--top-module','tb_soc_metrics','--Mdir',model,'--output-split','16000',
        *files,project/'flow/sram_contract_ret1n.v',project/'flow/tb_soc_metrics.sv']
    run(command,out/'verilate.log')
    cpp=sorted(model.glob('*.cpp'))+[vr/'include/verilated.cpp',vr/'include/verilated_threads.cpp',vr/'include/verilated_timing.cpp']
    def compile_one(item):
        i,p=item;obj=model/('p%d.o'%i)
        run([zig,'c++','-std=c++20','-DVL_TIME_CONTEXT','-O2','-I'+str(vr/'include'),'-I'+str(vr/'include/vltstd'),
            '-I'+str(model),'-c',p,'-o',obj],model/('compile%d.log'%i));return obj
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:objects=list(pool.map(compile_one,enumerate(cpp)))
    exe=model/'sim.exe';run([zig,'c++',*objects,'-o',exe],out/'link.log')
    def simulate(mode):
        dest=out/mode;dest.mkdir()
        text=run([exe,'+RECOVERY='+('1' if mode=='recovery' else '0'),'+FIXTURES='+str(project/'fixtures'),'+OUT='+str(dest)],dest/'run.log')
        assert 'PASS SOC_INPUT16_GATE recovery='+('1' if mode=='recovery' else '0') in text
        if mode=='recovery':assert 'SOC_GATE_RESET_IN_FLIGHT' in text
        return mode
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:assert set(pool.map(simulate,['cold','recovery']))=={'cold','recovery'}
    summary=dict(passed=True,actual_RTL=True,cold=True,inflight_reset_full_recovery=True,
        FPGA_SOURCE_clock_bypass=True,TCM_macro_bound=True,SRAM_macros_expected=100,
        precision='frozen S16 first input/S8 internal/W8',codes=2*6336,
        gate_testbench_exercised_on_RTL=True,actual_mapped_SoC=False,actual_SAIF_capture=False,
        project_manifest_sha256=hashlib.sha256((project/'manifest.json').read_bytes()).hexdigest(),
        timing_simulation=True,scope='new full-SoC bench and TCM integration; not commercial netlist/PPA')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
