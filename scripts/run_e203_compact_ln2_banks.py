"""Measure exact LN2 A/S read enables with the same E203 model and parameter stream."""
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
from verify_e203_compact_ln2_abort import observer as abort_observer


def bank_overlay(source, simulate=False):
    # The FC2 response lane uses row[3:0]. The skip response lane wraps
    # at eight rows, except in the last three rows packed into S2/S3.
    source=replace_once(source,'    wire [7:0] a_enable=ln_a_read?8\'hff:wb_active?wb_en:{8{a_en}};',
        f'''    wire narrow_ln_reads={"probe_narrow" if simulate else "1'b1"};
    wire ln_pair_read=output_read&&output_read_ready;
    wire [7:0] capture_mask=narrow_ln_reads&&ln_a_addr>=384?8'h03:8'hff;
    wire [7:0] a_row_mask=8'b1<<ln_row[3:1];
    wire [1:0] s_row_bank=ln_row>=96?{{1'b1,ln_row[1]}}:ln_row[2:1];
    wire [3:0] s_row_mask=4'b1<<s_row_bank;
    wire [7:0] a_enable=ln_a_read?capture_mask:wb_active?
                        ((narrow_ln_reads&&ln_pair_read)?a_row_mask:wb_en):{{8{{a_en}}}};''')
    source=replace_once(source,'s_enable=ln_s_active?ln_s_en:copy_phase?',
                        's_enable=ln_s_active?((narrow_ln_reads&&ln_pair_read)?s_row_mask:ln_s_en):copy_phase?')
    if not simulate:
        return source
    source=replace_once(source,'    output wire [63:0] ln_s_wdata\n', '''    output wire [63:0] ln_s_wdata,
    input wire probe_narrow,
    output wire probe_capture,probe_pair,
    output wire [7:0] probe_a_read,probe_a_write,
    output wire [3:0] probe_s_read,probe_s_write
''')
    return replace_once(source,'    wire [14:0] lut_offset=', '''    // Observe the accepted A/S macro ports, including the A address guard.
    assign probe_capture=ln_a_read;
    assign probe_pair=ln_pair_read;
    for (genvar i=0;i<8;i=i+1) begin: probe_a
        wire en=nice_rst_n&&a_enable[i]&&a_addresses[12*i+10+:2]==0;
        assign probe_a_read[i]=en&&!a_write[i];
        assign probe_a_write[i]=en&&a_write[i];
    end
    assign probe_s_read={4{nice_rst_n}}&s_enable&~s_write;
    assign probe_s_write={4{nice_rst_n}}&s_enable&s_write;
    wire [14:0] lut_offset=''')


def instrument(source, probe):
    source=abort_observer(source)
    edits=[
        ('namespace {',f'#include <cstdlib>\n#include "{probe}"\n\nnamespace {{'),
        ('    Dense99Scoreboard dense;', '    Dense99Scoreboard dense;\n    CompactLN2BankProbe banks;'),
        ('        dut.rst_n=0; dut.hrv=0; dut.mrv=0;',
         '        dut.probe_narrow=std::getenv("KWT_LN2_WIDE")==nullptr;\n        dut.rst_n=0; dut.hrv=0; dut.mrv=0;'),
        ('        dense.observe(dut,frame,','        banks.observe(dut);\n        dense.observe(dut,frame,'),
        ('            std::printf("PASS DENSE cycles=', '            banks.report();\n            std::printf("PASS DENSE cycles='),
        ('        dense=Dense99Scoreboard{};', '        dense=Dense99Scoreboard{};\n        banks=CompactLN2BankProbe{};'),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105'
    base=evidence/'p3_e203_compact_ln2_v2'
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
    source=(base/'kwt_e203_dense_supply.sv').read_text()
    mapped_top=out/'kwt_e203_dense_supply.sv'
    mapped_top.write_text(bank_overlay(source))
    sim_top=out/'bank_probe_top.sv'
    sim_top.write_text(bank_overlay(source,simulate=True))
    wrapper=out/'reference_top.sv'
    wrapper.write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',sim_top.read_text()))
    observer=out/'observer.cpp'
    probe=rtl/'compact_ln2_bank_probe.hpp'
    observer.write_text(instrument((base/'observer.cpp').read_text(),f'{cwd}/{rel(probe)}'))
    platform=[wrapper,out/'e203_cpu_top.v',out/'e203_cpu.v']
    hardware=[ROOT/p for p in baseline['source_sha256'] if p.endswith(('.sv','.v')) and
              (p.startswith(('rtl/','../e203_hbirdv2/')) or (p.startswith(rel(base)+'/') and
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
read_verilog -sv -overwrite {rel(mapped_top)}
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
        files=' '.join(rel(p) for p in [*hardware,*platform,sim_top])
        linux(f'verilator --cc --exe --build -j 3 --no-timing -Wno-fatal --output-split 14000 '
              f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
              f'--top-module reference_top --Mdir {rel(out)}/model {files} {cwd}/{rel(observer)}','build.log')
        cases={}
        for case,mode,flag in (('wide','normal','env KWT_LN2_WIDE=1 '),('narrow','normal','env -u KWT_LN2_WIDE '),
                               ('narrow_recovery','faults','env -u KWT_LN2_WIDE ')):
            linux(f'{flag}{rel(out)}/model/Vreference_top {rel(base/"firmware.bin")} {rel(frozen)} 6 {mode}',f'{case}.log')
            lines=(out/f'{case}.log').read_text().splitlines()
            def metrics(prefix):
                line=next(s for s in lines if s.startswith(prefix))
                return {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
            counts=metrics('PASS BANKS ')
            assert metrics('PASS DENSE ')==baseline['cases']['100']
            expected=(43008,594432,304128) if case=='wide' else (38400,76032,76032)
            assert tuple(counts[k] for k in ('capture_reads','fc2_reads','skip_reads'))==expected
            if case=='narrow_recovery':
                assert 'PASS LN2 FAULT stalled-result cancel and same-model hard-reset recovery' in lines
            cases[case]=counts
        assert cases['narrow']==cases['narrow_recovery']
        wide,narrow=(cases[k] for k in ('wide','narrow'))
        assert wide['a_writes']==narrow['a_writes'] and wide['s_writes']==narrow['s_writes']
        assert wide['a_reads']-narrow['a_reads']==523008 and wide['s_reads']-narrow['s_reads']==228096
        return cases

    with ThreadPoolExecutor(max_workers=2) as pool:
        mapped=pool.submit(mapping)
        cases=regression()
        area,unchanged=mapped.result()
    sources={**baseline['source_sha256']}
    sources.update({rel(p):sha(p) for p in [Path(__file__),probe,mapped_top,sim_top,observer,*platform,
                    base/'verification.json',base/'manifest.json',base/'mapped.json',
                    ROOT/'scripts/verify_e203_compact_ln2_abort.py',ROOT/'scripts/verify_e203_compact_dense_abort.py']})
    report=dict(passed=True,actual_E203=True,full_encoder=False,supply_MBps=100,
                cycles=baseline['cases']['100']['cycles'],cases=cases,mismatches=0,
                partition_standard_cell_mm2=area,baseline_standard_cell_mm2=baseline['partition_standard_cell_mm2'],
                reused_gate_modules=unchanged,private_macro_count=20,private_sram_bytes=65536,
                throughput_tasks_per_second=None,mean_SoC_power_mW=None,complete_counted_area_mm2=None)
    (out/'verification.json').write_text(json.dumps({**report,'source_sha256':sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
