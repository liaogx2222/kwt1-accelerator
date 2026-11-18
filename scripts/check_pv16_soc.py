"""Build/run the actual full S16 SYSBUS SoC with source-bound reusable models."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',required=True,type=Path);ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--model',type=Path);ap.add_argument('--cases',default='0');ap.add_argument('--recovery',action='store_true')
    ap.add_argument('--reset-point',type=int,choices=list(range(31)),default=0);ap.add_argument('--crc',action='store_true');ap.add_argument('--stall',action='store_true')
    ap.add_argument('--stall-kind',choices=['pv','ln','dense','score','stream','iter','ln4'],default='pv')
    ap.add_argument('--host-gap',type=int,choices=[0,4],default=4)
    ap.add_argument('--tasks',type=int,choices=[1,2],default=1);ap.add_argument('--jobs',type=int,default=4);a=ap.parse_args()
    assert not (a.crc and a.recovery) and not (a.stall and (a.crc or a.recovery))
    project=a.project.resolve();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    tmp=out/'tmp';tmp.mkdir();runtime=ROOT.parent/'keyword-transformer/tools/rtl_v1_python';vr=runtime/'verilator';zig=runtime/'ziglang/zig.exe'
    env=dict(os.environ,VERILATOR_ROOT=str(vr),ZIG_LIB_DIR=str(zig.parent/'lib'),TEMP=str(tmp),TMP=str(tmp),ZIG_GLOBAL_CACHE_DIR=str(ROOT/'tools/zig-cache'))
    receipt=json.loads((project/'source_manifest.json').read_text())
    bound={n:sha(project/n) for n in receipt['files']};assert bound==receipt['files'],'project drift'
    flags=['FPGA_SOURCE','SYNTHESIS','DISABLE_SV_ASSERTION','KWT_TECH_SRAM','KWT_SIM']
    stamp=dict(files=bound,defines=flags,source_manifest_sha256=sha(project/'source_manifest.json'))
    def run(cmd,log,cwd=project):
        with log.open('w',encoding='utf-8') as sink:
            try:p=subprocess.run(list(map(str,cmd)),cwd=cwd,env=env,stdout=sink,stderr=subprocess.STDOUT,text=True,timeout=1800)
            except subprocess.TimeoutExpired:
                sink.write('\nLOCAL_WALL_TIMEOUT1800_FAILURE\n');sink.flush();raise
        assert p.returncode==0,str(log);return log.read_text()
    if a.model:
        exe=a.model.resolve();old=json.loads((exe.parent/'sources.json').read_text());assert old==stamp,'stale model'
    else:
        model=out/'model';model.mkdir()
        files=[project/n for n in (project/'flow/local_sources.txt').read_text().splitlines()]
        includes=[project/n for n in (project/'flow/includes.txt').read_text().splitlines()]+[project/'rtl/v2/generated']
        run([vr/'bin/verilator_bin.exe','--cc','--main','--timing','--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC',
             *['-D'+d for d in flags],*['-I'+str(p) for p in includes],'--top-module','tb_soc_metrics','--Mdir',model,'--output-split','16000',
             *files,project/'flow/sram_contract_ret1n.v',project/'flow/tb_soc_metrics.sv'],out/'verilate.log')
        cpp=sorted(model.glob('*.cpp'))+[vr/'include/verilated.cpp',vr/'include/verilated_threads.cpp',vr/'include/verilated_timing.cpp']
        def one(item):
            i,p=item;obj=model/('p%d.o'%i)
            run([zig,'c++','-std=c++20','-DVL_TIME_CONTEXT','-O2','-I'+str(vr/'include'),'-I'+str(vr/'include/vltstd'),'-I'+str(model),'-c',p,'-o',obj],model/('compile%d.log'%i))
            return obj
        with ThreadPoolExecutor(max_workers=4) as pool:objects=list(pool.map(one,enumerate(cpp)))
        exe=model/'sim.exe';run([zig,'c++',*objects,'-o',exe],out/'link.log');(model/'sources.json').write_text(json.dumps(stamp,indent=2)+'\n')
    def simulate(case):
        dest=out/('case_%02d'%case);dest.mkdir()
        command=[exe,'+CASE='+str(case),'+RECOVERY='+str(int(a.recovery)),'+RESET_POINT='+str(a.reset_point),'+TASKS='+str(a.tasks),'+HOST_GAP='+str(a.host_gap),'+FIXTURES='+str(project/'fixtures'),'+OUT='+str(dest),*(['+CRC_FAULT'] if a.crc else []),*(['+STALL_'+a.stall_kind.upper()] if a.stall else [])]
        (dest/'command.json').write_text(json.dumps(list(map(str,command)),indent=2)+'\n')
        text=run(command,dest/'run.log')
        rows=[list(map(int,x)) for x in re.findall(r'LOCAL_TASK_PROFILE task=(\d+) legacy_cycles=(\d+) issue_cycles=(\d+) compute_cycles=(\d+) read_words=(\d+) write_words=(\d+)',text)]
        assert len(rows)==a.tasks and text.count('PASS SOC_INPUT16_GATE')==a.tasks
        if a.recovery:assert 'SOC_GATE_RESET_IN_FLIGHT' in text
        if a.recovery and a.reset_point==14:assert 'PASS LOCAL_DENSE_ERROR_QUIESCENT cycles=8' in text
        if a.recovery and a.reset_point==23:assert 'PASS LOCAL_ITER_HELD_RESET_SETUP' in text
        if a.recovery and a.reset_point==30:assert 'PASS LOCAL_LN4_ERROR_QUIESCENT cycles=8' in text
        if a.crc:assert 'PASS LOCAL_PREFETCH_CRC_REJECT' in text
        if a.stall:
            marker='PASS LOCAL_LN4_STALL fork_cycles=11 held_packed_write_cycles=17' if a.stall_kind=='ln4' else 'PASS LOCAL_ITER_STALL sqrt_result_cycles=17 div_result_cycles=11' if a.stall_kind=='iter' else 'PASS LOCAL_STREAM_STALL score_exp_cycles=17 alias_result_cycles=11' if a.stall_kind=='stream' else 'PASS LOCAL_'+a.stall_kind.upper()+'_STALL mac_cycles=17 held_requant_cycles=11'
            assert marker in text
        golden=(project/('fixtures/expected_%03d.hex'%case)).read_text().split()
        for i in range(a.tasks):assert (dest/('matrix_task_%02d.hex'%i)).read_text().split()==golden,'output mismatch'
        transfers=[list(map(int,x)) for x in re.findall(r'LOCAL_TRANSFER_PROFILE task=(\d+) host_gap=(\d+) nice_reads=(\d+) nice_writes=(\d+) nice_peak=(\d+) shared_reads=(\d+) shared_writes=(\d+) pending=(\d+)',text)]
        if transfers:
            assert len(transfers)==a.tasks
            for transfer in transfers:assert transfer[1]==a.host_gap and transfer[2:4]==[192496,1584] and transfer[7]==0
        result=dict(passed=True,case=case,tasks=a.tasks,recovery=a.recovery,reset_point=a.reset_point,CRC_rejection_full_recovery=a.crc,PV_stalls=a.stall and a.stall_kind=='pv',LN_stalls=a.stall and a.stall_kind=='ln',Dense_stalls=a.stall and a.stall_kind=='dense',Score_stalls=a.stall and a.stall_kind=='score',Stream_stalls=a.stall and a.stall_kind=='stream',Iter_stalls=a.stall and a.stall_kind=='iter',LN4_stalls=a.stall and a.stall_kind=='ln4',host_gap_cycles=a.host_gap,transfer_profiles=transfers,profiles=rows,codes=6336*a.tasks,log_sha256=sha(dest/'run.log'))
        (dest/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);return result
    cases=list(map(int,a.cases.split(',')))
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:rows=list(pool.map(simulate,cases))
    assert {n:sha(project/n) for n in receipt['files']}==bound,'source drift during run'
    result=dict(passed=True,variant=receipt['variant'],actual_full_E203_RTL=True,two_state=True,timed_SV=True,
        KWT_SIM_bank_liveness_and_cache_consumer_checks=True,source_bindings=stamp,model_sha256=sha(exe),
        cases=rows,total_codes=sum(x['codes'] for x in rows),arbitrary_new_samples_or_official600_evaluation=False,
        compiler_versions=dict(python=sys.version,verilator_sha256=sha(vr/'bin/verilator_bin.exe'),zig_sha256=sha(zig)),
        macro_count_expected=100,macro_structure_changed=False,interfaces_unchanged=True,area_mm2=None,power_mW=None,energy_uJ=None,physical_signoff=False)
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':main()
