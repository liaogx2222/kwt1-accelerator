"""Re-link a host observer to the unchanged E203 model; count real bank edges."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);base=ROOT/'testdata/input16_rtl_20261105/trim2_e203';model=base/'model';rel=out.relative_to(ROOT).as_posix();mp=model.relative_to(ROOT).as_posix()
    assert json.loads((base/'verification.json').read_text())['passed'];manifest=json.loads((base/'manifest.json').read_text())
    for f in base.iterdir():
        if f.is_file() and (f.name in ['firmware.bin','cases.txt'] or f.name.startswith(('common.bin','layer_','input_','expected_'))):assert sha(f)==manifest[f.name];shutil.copyfile(f,out/f.name)
    source=base/'sim_input16_e203.cpp';assert sha(source)==manifest[source.name];t=source.read_text()
    def change(old,new):
        nonlocal t
        assert t.count(old)==1,(old,t.count(old));t=t.replace(old,new)
    prefix='reference_top__DOT__path__DOT__accelerator__DOT__accel__DOT__bank_';header=model/'Vreference_top___024root.h';assert all(prefix+n in header.read_text() for n in ['en','we'])
    change('#include "Vreference_top.h"','#include "Vreference_top.h"\n#include "Vreference_top___024root.h"\nstatic uint64_t bank_reads[20],bank_writes[20];')
    change('static void begin_job(){','static void begin_job(){\n for(int i=0;i<20;i++)bank_reads[i]=bank_writes[i]=0;')
    change(' if(d.retired)retired++;',f''' if(active&&rc_event==999){{
  uint32_t en=d.rootp->{prefix}en,we=d.rootp->{prefix}we;
  while(en){{unsigned bank=__builtin_ctz(en);en&=en-1;if((we>>bank)&1)bank_writes[bank]++;else bank_reads[bank]++;}}
 }}
 if(d.retired)retired++;''')
    change('  windows<<ji<<','''  std::ofstream banks(root+"/bank_accesses.txt",std::ios::app);banks<<ji;
  for(int i=0;i<20;i++)banks<<" "<<bank_reads[i]<<" "<<bank_writes[i];banks<<"\\n";
  windows<<ji<<''');(out/'observer.cpp').write_text(t)
    def run(cmd,name):
        r=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+cmd],capture_output=True,text=True);(out/(name+'.log')).write_text(r.stdout+r.stderr);assert r.returncode==0,(name,r.stdout[-1000:],r.stderr[-1500:]);return r.stdout
    objects=[model/n for n in ['Vreference_top__ALL.a','verilated.o','verilated_threads.o']];hashes={p:sha(p) for p in objects}
    run(f'g++ -std=c++17 -O2 -pthread -I{mp} -I/usr/share/verilator/include -I/usr/share/verilator/include/vltstd {rel}/observer.cpp '+ ' '.join(p.relative_to(ROOT).as_posix() for p in objects)+f' -o {rel}/observer','compile')
    text=run(f'{rel}/observer {rel} batch','simulation');assert 'PASS E203 jobs=12' in text
    assert (out/'windows.txt').read_bytes()==(base/'windows.txt').read_bytes() and (out/'cpu_metrics.txt').read_bytes()==(base/'cpu_metrics.txt').read_bytes()
    cases=[];windows=json.loads((base/'verification.json').read_text())['windows'];observed=[[int(v) for v in l.split()] for l in (out/'bank_accesses.txt').read_text().splitlines()];assert len(observed)==12
    for i,row in enumerate(observed):
        assert len(row)==41 and row[0]==i;counts=[dict(bank=j,reads=row[1+2*j],writes=row[2+2*j]) for j in range(20)];assert sum(b['reads'] for b in counts)==windows[i][8] and sum(b['writes'] for b in counts)==windows[i][9]
        assert sha(out/f'cpu_observed_job_{i:02d}.hex')==sha(base/f'cpu_observed_job_{i:02d}.hex');cases.append(counts)
    for p,h in hashes.items():assert sha(p)==h
    result=dict(passed=True,cases=cases,window='same B0/B1 as full E203',observed_cycles_and_outputs_identical=True,whole_SoC_power_measured=False,bank_edges_observed=True,scope='actual SRAM access counts, not gate/CPU/interconnect activity coverage')
    (out/'verification.json').write_text(json.dumps(result,indent=2));bound=[Path(__file__),source,header,*objects,base/'verification.json',base/'manifest.json']
    (out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in bound},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(dict(passed=True,cases=12,bank_edges_observed=True),indent=2))


if __name__=='__main__':main()
