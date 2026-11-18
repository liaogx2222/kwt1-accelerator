"""Capture same-window RTL activity and map the complete trim2 direct E203 reference."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from local_tools import ROOT, sha
from run_input16_e203_block import replace_once


def observe(source,header):
    specs=[]
    ports='accel_abort drop_response stream_cancel stream_accepted stream_payload mv mr ma mw mread mmask mrv mrr mrd hv hr ha hw hread hm hrv hrr hrd irq bus_rc parameter_words'.split()
    for name in ports:
        width=32 if name in 'stream_payload ma mw mrd ha hw hrd bus_rc parameter_words'.split() else 4 if name in ('mmask','hm') else 1
        specs.append((name,width,'d.'+name))
    selections=(
        r'^(?:pv|pr|pread|prv|prr|pa|pw|prd|pmask|stream_valid|stream_ready|stream_data)$',
        r'^cpu/(?:itcm_ram_cs|dtcm_ram_cs|itcm_ram_we|dtcm_ram_we|itcm_ram_dout|dtcm_ram_dout)$',
        r'^cpu/u_e203_cpu/(?:.*nice.*|.*mem_icb.*)$',
        r'^cpu/u_e203_cpu/u_e203_core/u_e203_exu/(?:rf_wbck.*|dec_rs[12].*|disp_alu_.*|alu_cmt_.*|cmt_instret_ena)$',
        r'^cpu/u_e203_cpu/u_e203_core/u_e203_ifu/[^/]+(?:valid|ready|pc_r|ir_r)$',
        r'^path/(?:av|ar|awrite|arv|arr|ae|aa|ad|ard|am)$',
        r'^path/(?:accelerator|bridge)/(?:[^/]*(?:state|busy|valid|ready|crc|addr|data|enable|count|phase)[^/]*)$',
        r'^path/accelerator/accel/(?:[^/]*(?:state|busy|valid|ready|crc|addr|data|enable|count|phase)[^/]*|bank_en|bank_we)$',
        r'^path/accelerator/accel/[^/]+/(?:[^/]*(?:state|valid|ready|phase|tag|valid|acc0|shift|cycle)[^/]*)$',
    )
    names={n for n,_,_ in specs}
    fields={}
    for width,member in re.findall(r'(?:CData|SData|IData|QData)\s*/\*(\d+):0\*/\s*(reference_top__DOT__\w+);',header):
        name=member.removeprefix('reference_top__DOT__').replace('__DOT__','/')
        fields[name]='d.rootp->'+member
        if name not in names and any(re.search(pattern,name) for pattern in selections):
            specs.append((name,int(width)+1,fields[name])); names.add(name)
    assert len(specs)>=70
    b='reference_top__DOT__path__DOT__accelerator__DOT__accel__DOT__bank_'
    assert all(b+suffix in header for suffix in ('en','we','addr'))
    support=f'''#include "Vreference_top___024root.h"
struct Activity {{uint64_t last=0,ones=0,toggles=0;}};
static Activity activity[{len(specs)}];
static uint64_t samples,bank_reads[20][2],bank_writes[20][2],itcm_access,dtcm_access;
static void sample(unsigned i,uint64_t value) {{
 auto &a=activity[i]; a.ones+=__builtin_popcountll(value);
 if(samples) a.toggles+=__builtin_popcountll(value^a.last);
 a.last=value;
}}
'''
    source=replace_once(source,'#include "verilated.h"','#include "verilated.h"\n'+support)
    blocks='\n'.join(f'  sample({i},uint64_t({expr})&{(1<<width)-1}ull);' for i,(_,width,expr) in enumerate(specs))
    sample_code=f''' if(active&&rc_event==999&&clocks>=begin_clock){{
{blocks}
  uint32_t en=d.rootp->{b}en,we=d.rootp->{b}we;
  const auto &address=d.rootp->{b}addr;
  while(en){{
   const unsigned bank=__builtin_ctz(en); en&=en-1;
   unsigned physical=0;
   if(bank<8&&(bank&1)){{const unsigned bit=12*bank+10;physical=(address[bit/32]>>(bit%32))&1u;}}
   if(we>>bank&1u)++bank_writes[bank][physical];else ++bank_reads[bank][physical];
  }}
  itcm_access+={fields['cpu/itcm_ram_cs']}; dtcm_access+={fields['cpu/dtcm_ram_cs']};
  ++samples;
 }}
 if(d.retired)retired++;'''
    source=replace_once(source,' if(d.retired)retired++;',sample_code)
    descriptions=',\n'.join(f'  {{"{name}",{width}}}' for name,width,_ in specs)
    source=replace_once(source,'  windows<<ji<<',f'''  require(samples==end_clock-begin_clock,"activity and task window differ");
  std::ofstream a(root+"/activity.txt");
  a<<"samples "<<samples<<"\\n";
  const struct {{const char *name; unsigned width;}} names[]={{
{descriptions}
  }};
  for(unsigned i=0;i<{len(specs)};++i) a<<names[i].name<<" "<<names[i].width<<" "<<activity[i].toggles<<" "<<activity[i].ones<<"\\n";
  std::ofstream banks(root+"/macros.txt");
  banks<<"TCM "<<itcm_access<<" "<<dtcm_access<<"\\n";
  for(unsigned i=0;i<20;++i)for(unsigned j=0;j<2;++j)banks<<i<<" "<<j<<" "<<bank_reads[i][j]<<" "<<bank_writes[i][j]<<"\\n";
  windows<<ji<<''')
    return source


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve(); out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105'
    base=evidence/'p2_e203_stream'
    rates=evidence/'p2_e203_stream_rate'
    original=rates/'100'
    cpu=ROOT.parent/'e203_hbirdv2'
    model=base/'model'
    rtl=ROOT/'rtl/input16_trim2'
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    cacti=ROOT/'third_party/cacti_reference'
    sram=ROOT/'testdata/full_scope_20261105/sram_cacti'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def rel(path):
        return os.path.relpath(path,ROOT).replace('\\','/')

    stream=json.loads((base/'source_bindings.json').read_text())
    for name,value in stream.items():
        assert sha(ROOT/name)==value,name
    rate_manifest=json.loads((rates/'manifest.json').read_text())
    rate_sources=[rates/'observer.cpp',rates/'window_observer.hpp',
                  *[p for p in original.iterdir() if p.suffix in ('.hex','.bin','.txt')]]
    for p in rate_sources:
        assert sha(p)==rate_manifest[p.relative_to(rates).as_posix()],p
    base_manifest=json.loads((base/'manifest.json').read_text())
    objects=[model/n for n in ('Vreference_top__ALL.a','verilated.o','verilated_threads.o','Vreference_top___024root.h')]
    object_hashes={rel(p):sha(p) for p in objects}
    for p in objects:
        recorded=base_manifest.get(p.relative_to(base).as_posix())
        if recorded is not None:
            assert object_hashes[rel(p)]==recorded,p

    def linux(command,log):
        with (out/log).open('w') as fd:
            result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                                  stdout=fd,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-5000:])

    def activity():
        run=out/'run'; run.mkdir()
        for p in rate_sources:
            if p.parent==original and (p.suffix in ('.hex','.bin') and not p.name.startswith('cpu_observed') or p.name=='cases.txt'):
                shutil.copyfile(p,run/p.name)
        shutil.copyfile(rates/'window_observer.hpp',out/'window_observer.hpp')
        observer=out/'observer.cpp'
        observer.write_text(observe((rates/'observer.cpp').read_text(),objects[-1].read_text()))
        link=' '.join(rel(p) for p in objects[:-1])
        linux(f'g++ -std=c++17 -O2 -pthread -I{rel(model)} -I/usr/share/verilator/include '
              f'-I/usr/share/verilator/include/vltstd {rel(observer)} {link} -o {rel(out/"observer")}','build.log')
        linux(f'{rel(out/"observer")} {rel(run)} batch 6','run.log')
        for name in ('windows.txt','cpu_metrics.txt','cpu_observed_job_00.hex'):
            assert (run/name).read_bytes()==(original/name).read_bytes(),name
        window=list(map(int,(run/'windows.txt').read_text().split()))
        assert window[2]-window[1]==7253988
        lines=(run/'macros.txt').read_text().splitlines()
        assert lines[0]=='TCM 0 0'
        counts=[list(map(int,line.split())) for line in lines[1:]]
        assert [sum(r[i] for r in counts) for i in (2,3)]==window[8:10]
        return window

    def mapping():
        wrapper=(base/'reference_top.sv').read_text()
        wrapper=replace_once(wrapper,'output [31:0] pc,sp,output retired,output irq', 'output [31:0] pc,output irq')
        wrapper='\n'.join(line for line in wrapper.splitlines() if not line.startswith((' assign sp=',' assign retired=')))+'\n'
        (out/'reference_top.sv').write_text(wrapper)
        ram=(cpu/'rtl/e203/general/sirv_gnrl_ram.v').read_text()
        ram='(* blackbox *) '+ram[ram.index('module sirv_gnrl_ram'):ram.index(');',ram.index('module sirv_gnrl_ram'))+2]+'\nendmodule\n'
        (out/'tcm_blackbox.v').write_text(ram)
        skips={'config.v','e203_defines.v','sirv_gnrl_ram.v','sirv_sim_ram.v','input16_icb_top.sv'}
        generated={'e203_cpu_top.v','e203_cpu.v','kwt_input16_icb_top.sv','kwt1_mmio.sv'}
        sources=[ROOT/name for name in stream if name.endswith(('.v','.sv')) and
                 Path(name).name not in skips|generated|{'reference_top.sv'}]
        sources += [base/n for n in sorted(generated)]
        sources += [out/'reference_top.sv',out/'tcm_blackbox.v',rtl/'kwt_tech_sram_blackbox.sv']
        script=out/'mapping.ys'
        script.write_text(f'''read_verilog -sv -DFPGA_SOURCE -DKWT_TECH_SRAM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated {' '.join(rel(p) for p in sources)}
hierarchy -check -top reference_top
synth -top reference_top -noabc -noshare
read_liberty -lib {rel(lib)}
dfflibmap -liberty {rel(lib)}
abc -liberty {rel(lib)}
clean
check -assert
stat -liberty {rel(lib)}
write_json {rel(out/'mapped.json')}
write_verilog -noattr -noexpr -simple-lhs {rel(out/'mapped.v')}
''')
        linux(f'yosys -Q -T -s {rel(script)}','mapping.log')

    def macros():
        template=(sram/'4096x16/cacti.cfg').read_text()
        results={}
        for label,size,width in (('shared',524288,32),('itcm',65536,64),('dtcm',65536,32)):
            config=out/(label+'.cfg')
            text=re.sub(r'(?m)^-size \(bytes\) \d+',f'-size (bytes) {size}',template)
            text=re.sub(r'(?m)^-block size \(bytes\) \d+',f'-block size (bytes) {width//8}',text)
            text=re.sub(r'(?m)^-output/input bus width\s+\d+',f'-output/input bus width {width}',text)
            config.write_text(text)
            linux(f'cd {rel(cacti)} && ./cacti -infile {cwd}/{rel(config)}',label+'.log')
            raw=Path(str(config)+'.out').read_text().splitlines()
            values=next(csv.reader(raw[-1:]))
            assert [int(float(values[i])) for i in (0,1,3)]==[45,size,width],(label,values)
            results[label]=dict(bytes=size,width=width,read_nJ=float(values[7]),write_nJ=float(values[8]),
                                leakage_mW=float(values[9]),area_mm2=float(values[10]),access_ns=float(values[4]))
        (out/'memory_models.json').write_text(json.dumps(results,indent=2))

    with ThreadPoolExecutor(max_workers=3) as pool:
        synth=pool.submit(mapping)
        ram=pool.submit(macros)
        window=activity()
        synth.result(); ram.result()
    sources={**stream,**{rel(p):sha(p) for p in [Path(__file__),*rate_sources,*objects,lib,
        rtl/'kwt_tech_sram_blackbox.sv',cacti/'cacti',sram/'verification.json',sram/'4096x16/cacti.cfg']}}
    assert all(sources[p]==digest for p,digest in object_hashes.items())
    (out/'capture.json').write_text(json.dumps(dict(passed=True,window=window,source_sha256=sources),indent=2))
    files=[p for p in out.rglob('*') if p.is_file()]
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in files},indent=2))
    print('PASS captured',window)


if __name__=='__main__':
    main()
