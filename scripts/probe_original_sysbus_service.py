"""Bounded four-state service probe of original bus, not a full-task result."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--project',required=True,type=Path);ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
    p=a.project.resolve();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    receipt=json.loads((p/'source_manifest.json').read_text())
    assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==h for n,h in receipt['files'].items()),'source drift'
    names=[n for n in (p/'flow/local_sources.txt').read_text().splitlines() if n.startswith('cpu/')]
    names+=['soc/kwt_sysbus_arbiter3.sv','soc/kwt_soc_shared_sram.sv','soc/soc_sram_sp.sv','flow/sram_contract_ret1n.v']
    names += [n for n in (p/'flow/local_sources.txt').read_text().splitlines() if 'mrom' in n.lower() and n not in names]
    # Put the explicit 1ns/1ps compilation-unit directive before legacy
    # E203 files: their #1 functional flop delay has no own timescale.
    # Otherwise Icarus interprets it as one second, not one nanosecond.
    src=[ROOT/'rtl/ln8_opt/tb_original_sysbus_service.sv']+[p/n for n in names]
    includes=[p/n for n in (p/'flow/includes.txt').read_text().splitlines()]
    iv=Path('C:/iverilog/bin/iverilog.exe');vv=iv.with_name('vvp.exe');rows=[];commands=[]
    def run(cmd,log):
        commands.append(list(map(str,cmd)));r=subprocess.run(commands[-1],cwd=ROOT,capture_output=True,text=True,timeout=120)
        log.write_text('returncode='+str(r.returncode)+'\n'+r.stdout+r.stderr);assert r.returncode==0,str(log);return r.stdout
    for mode in [0,1]:
        exe=out/('mode%d.vvp'%mode)
        run([iv,'-g2012','-DFPGA_SOURCE','-DSYNTHESIS','-DDISABLE_SV_ASSERTION',*['-I'+str(x) for x in includes],
            '-s','tb_original_sysbus_service','-Ptb_original_sysbus_service.USE_ARBITER='+str(mode),'-o',exe,*src],out/('compile%d.log'%mode))
        for stall in [0,1]:
            log=out/('mode%d_stall%d.log'%(mode,stall));text=run([vv,exe,'+STALL='+str(stall)],log)
            match=re.search(r'PASS ORIGINAL_BUS arbiter=(\d+) stall=(\d+) commands=(\d+) window_cycles=(\d+) min_shared_gap=(\d+) max_shared_gap=(\d+)',text)
            assert match;row=list(map(int,match.groups()));assert row[:3]==[mode,stall,512];rows.append(row);print(text,flush=True)
    sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
    result=dict(passed=True,four_state=True,scope='standalone original-fabric protocol probe; direct mode is an ideal eager stimulus at the existing interface, never a full-SoC bypass or task throughput',
        original_decoder_changed=False,platform_ports_or_width_changed=False,rows=rows,
        columns=['current_upstream_arbiter','response_stall_pattern','commands','window_cycles','minimum_shared_accept_gap','maximum_shared_accept_gap'],
        commands=commands,source_sha256={str(x):sha(x) for x in src},tool_sha256={str(x):sha(x) for x in [iv,vv]},
        mandatory_payload_commands=2*(189328+3168)+1584,
        current_arbiter_payload_lower_bound_cycles=4*(2*(189328+3168)+1584),
        current_arbiter_ideal_upper_tasks_s_at_assumed150MHz=150000000/(4*(2*(189328+3168)+1584)),
        original_fabric_payload_only_ideal_cycles=2*(2*(189328+3168)+1584),
        task_PPA_measured=False)
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
