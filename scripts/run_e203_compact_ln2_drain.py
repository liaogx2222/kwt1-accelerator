"""Close the LN2 result path through the physical S banks and an elastic consumer."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha
from map_compact_ffn_writeback import graph_digest
from run_e203_compact_dense99 import area_report
from run_e203_compact_supply import cpu_overlay, replace_once


def overlay(source, simulate=False):
    ports='''    output wire drain_busy,drain_valid,drain_last,
    input wire drain_ready,
    output wire [9:0] drain_index,
    output wire [63:0] drain_data'''
    if simulate:
        ports+=',\n    output wire probe_drain_read'
    anchor='    output wire [63:0] ln_s_wdata'+(',' if simulate else '')
    edits=[
        (anchor+'\n','    output wire [63:0] ln_s_wdata,\n'+ports+(',' if simulate else '')+'\n'),
        ('    wire ln_a_read,ln_error,skip_saved;',
         '    wire ln_a_read,ln_error,skip_saved,drain_read;\n    wire [9:0] drain_read_index;'),
        ('(ln_s_active&&(copy_phase||write_s));',
         '(ln_s_active&&(copy_phase||write_s))||(drain_read&&(ln_s_active||copy_phase||write_s));'),
        ('!owns_s&&!capture_phase&&!ln_phase;', '!owns_s&&!capture_phase&&!ln_phase&&!drain_busy;'),
        ('s_enable=ln_s_active?', 's_enable=drain_read?4\'hf:ln_s_active?'),
        ('s_write=ln_s_active?', 's_write=drain_read?4\'h0:ln_s_active?'),
        ('s_address=ln_s_active?', "s_address=drain_read?{4{{2'b0,drain_read_index}}}:ln_s_active?"),
        ('finish_frame&&!coeff_phase&&!output_available)',
         'finish_frame&&!coeff_phase&&!output_available&&!drain_busy)'),
        ('internal_dense_ready&&ffn_start_ok&&!output_available;',
         'internal_dense_ready&&ffn_start_ok&&!output_available&&!drain_busy;'),
        ('.start_valid(dense_start&&ffn_start_ok&&!output_available)',
         '.start_valid(dense_start&&ffn_start_ok&&!output_available&&!drain_busy)'),
        ('    kwt_compact_dense dense (','''    kwt_compact_ln2_drain drain (
        .clk(nice_clk),.rst_n(nice_rst_n),.clear(dense_abort||!lease_hold),.start(output_release),
        .owned(drain_busy),.read_s(drain_read),.read_index(drain_read_index),.s_data(scratch_rdata),
        .out_valid(drain_valid),.out_ready(drain_ready),.out_index(drain_index),
        .out_last(drain_last),.out_data(drain_data));

    kwt_compact_dense dense ('''),
    ]
    if simulate:
        edits.append(('    assign probe_pair=ln_pair_read;',
                      '    assign probe_pair=ln_pair_read;\n    assign probe_drain_read=drain_read;'))
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def instrument(source,probe):
    edits=[
        ('namespace {',f'#include "{probe}"\n\nnamespace {{'),
        ('    CompactLN2BankProbe banks;','    CompactLN2BankProbe banks;\n    CompactLN2DrainProbe drain;'),
        ('dut.probe_narrow=std::getenv("KWT_LN2_WIDE")==nullptr;', 'dut.probe_narrow=1;'),
        ('        dut.cancel=cancel_next;', '''        dut.drain_ready=std::getenv("KWT_DRAIN_READY")!=nullptr||clocks%64>=16;
        dut.cancel=cancel_next;'''),
        ('!dut.ln_valid && !dut.ln_write && !dut.ln_phase,"failed to invalidate LN2 state"',
         '!dut.drain_valid && !dut.probe_drain_read && !dut.drain_busy,"failed to invalidate S drain"'),
        ('dut.ln_valid && !dut.ln_ready && dense.ln.writes>0 && !dense_cancelled',
         'dut.drain_valid && !dut.drain_ready && drain.words>=8 && !dense_cancelled'),
        ('            dense.ln.held=false;\n            check(!dut.ln_valid&&!dut.ln_write&&!dut.ln_phase,"stale LN2 output after cancel");',
         '''            drain.held=false;
            check(!dut.drain_valid&&!dut.probe_drain_read&&!dut.drain_busy,"stale S drain after cancel");'''),
        ('        banks.observe(dut);','        banks.observe(dut);\n        drain.observe(dut,frame,dense.ln.output);'),
        ('            banks.report();','            banks.report();\n            drain.report();'),
        ('        banks=CompactLN2BankProbe{};',
         '        banks=CompactLN2BankProbe{};\n        drain=CompactLN2DrainProbe{};'),
        ('PASS ln2_cancel output_before=%llu writes_before=%llu error_index=6167',
         'PASS drain_cancel words_before=%llu reads_before=%llu error_index=6167'),
        ('(unsigned long long)session.dense.ln.output_count,(unsigned long long)session.dense.ln.writes',
         '(unsigned long long)session.drain.words,(unsigned long long)session.drain.reads'),
        ('PASS LN2 FAULT stalled-result cancel and same-model hard-reset recovery',
         'PASS DRAIN FAULT stalled-result cancel and same-model hard-reset recovery'),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve()
    out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105'
    base=evidence/'p3_e203_compact_ln2_banks'
    ln2=evidence/'p3_e203_compact_ln2_v2'
    frozen=evidence/'trim2_e203'
    rtl=ROOT/'rtl/block_transfer'
    cpu=ROOT.parent/'e203_hbirdv2'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def rel(path):
        return os.path.relpath(path,ROOT).replace('\\','/')

    manifest=json.loads((base/'manifest.json').read_text())
    baseline=json.loads((base/'verification.json').read_text())
    for name,value in manifest.items():
        assert sha(base/name)==value,name
    for name,value in baseline['source_sha256'].items():
        assert sha(ROOT/name)==value,name
    top=out/'kwt_e203_dense_supply.sv'
    top.write_text(overlay((base/top.name).read_text()))
    sim=out/'drain_probe_top.sv'
    sim.write_text(overlay((base/'bank_probe_top.sv').read_text(),simulate=True))
    wrapper=out/'reference_top.sv'
    wrapper.write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',sim.read_text()))
    observer=out/'observer.cpp'
    probe=rtl/'compact_ln2_drain_probe.hpp'
    observer.write_text(instrument((base/observer.name).read_text(),f'{cwd}/{rel(probe)}'))
    core=rtl/'kwt_compact_ln2_drain.sv'
    platform=[wrapper,out/'e203_cpu_top.v',out/'e203_cpu.v']
    hardware=[ROOT/p for p in baseline['source_sha256'] if p.endswith(('.sv','.v')) and
              (p.startswith(('rtl/','../e203_hbirdv2/')) or (p.startswith(rel(ln2)+'/') and
                 Path(p).name not in {'kwt_e203_dense_supply.sv','reference_top.sv','e203_cpu_top.v','e203_cpu.v'}))]
    hardware=[p for p in hardware if p.name not in {'config.v','e203_defines.v','e203_cpu_top.v','e203_cpu.v'}]

    def linux(command,log):
        with (out/log).open('w') as fd:
            result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                                  stdout=fd,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-5000:])

    def mapping():
        lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
        script=out/'mapping.ys'
        script.write_text(f'''read_json {rel(base/'mapped.json')}
read_verilog -sv -overwrite {rel(top)} {rel(core)}
synth -top e203_subsys_nice_core -noabc -noshare
dfflibmap -liberty {rel(lib)}
abc -liberty {rel(lib)}
clean
check -assert
stat -liberty {rel(lib)}
write_json {rel(out/'mapped.json')}
''')
        linux(f'yosys -Q -s {rel(script)}','mapping.log')
        before=json.loads((base/'mapped.json').read_text())['modules']
        after=json.loads((out/'mapped.json').read_text())['modules']
        unchanged=[n for n,m in before.items() if n!='e203_subsys_nice_core' and m.get('cells')]
        assert all(graph_digest(before[n])==graph_digest(after[n]) for n in unchanged)
        return area_report(out,lib),unchanged

    def regression():
        files=' '.join(rel(p) for p in [*hardware,*platform,sim,core])
        linux(f'verilator --cc --exe --build -j 3 --no-timing -Wno-fatal --output-split 14000 '
              f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
              f'--top-module reference_top --Mdir {rel(out)}/model {files} {cwd}/{rel(observer)}','build.log')
        cases={}
        for case,mode,env in (('ready','normal','env KWT_DRAIN_READY=1'),
                              ('stalled','normal','env -u KWT_DRAIN_READY'),
                              ('recovery','faults','env -u KWT_DRAIN_READY')):
            linux(f'{env} {rel(out)}/model/Vreference_top {rel(ln2/"firmware.bin")} {rel(frozen)} 6 {mode}',f'{case}.log')
            lines=(out/f'{case}.log').read_text().splitlines()
            def metrics(prefix):
                line=next(s for s in lines if s.startswith(prefix))
                return {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
            bank,drain,dense=(metrics(p) for p in ('PASS BANKS ','PASS DRAIN ','PASS DENSE '))
            expected=baseline['cases']['narrow'].copy()
            expected['s_reads']+=4*9504
            assert bank==expected
            assert tuple(dense[k] for k in ('reads','aux','matrices','raw','rq','residual','stats','ln','ln_writes'))==(
                361796,6580,72,684288,684288,76032,1188,76032,9504)
            assert drain['words']==9504 and drain['codes']==76032 and drain['turnovers']==9492
            assert (drain['stalls']==0)==(case=='ready')
            assert drain['busy']==12*(792+2)+drain['stalls']
            if case=='recovery':
                assert 'PASS DRAIN FAULT stalled-result cancel and same-model hard-reset recovery' in lines
            cases[case]=dict(bank=bank,drain=drain,dense=dense)
        assert cases['stalled']==cases['recovery']
        return cases

    with ThreadPoolExecutor(max_workers=2) as pool:
        mapped=pool.submit(mapping)
        cases=regression()
        area,unchanged=mapped.result()
    sources={**baseline['source_sha256']}
    sources.update({rel(p):sha(p) for p in [Path(__file__),probe,core,top,sim,observer,*platform,
                    base/'verification.json',base/'manifest.json',base/'mapped.json']})
    report=dict(passed=True,actual_E203=True,full_encoder=False,supply_MBps=100,cases=cases,mismatches=0,
                baseline_cycles=baseline['cycles'],partition_standard_cell_mm2=area,
                baseline_standard_cell_mm2=baseline['partition_standard_cell_mm2'],reused_gate_modules=unchanged,
                private_macro_count=20,private_sram_bytes=65536,throughput_tasks_per_second=None,
                mean_SoC_power_mW=None,complete_counted_area_mm2=None)
    (out/'verification.json').write_text(json.dumps({**report,'source_sha256':sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
