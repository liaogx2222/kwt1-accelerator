"""Package the bounded RNE proof, simulation and public-library STA comparison."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True)
    rel=out.relative_to(ROOT).as_posix()
    rtl=ROOT/'rtl/block_transfer'
    generic=ROOT/'rtl/micro/rne_pipe.sv'
    specialized=rtl/'kwt_rne_dense_right.sv'
    tb=rtl/'tb_rne_dense_right.sv'
    miter=rtl/'rne_dense_miter.sv'
    mapping=ROOT/'flow/dense_rne_nangate45.ys'
    formal=ROOT/'flow/dense_rne_equivalence.ys'
    liberty=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    sta=ROOT/'tools/opensta_reference/root/usr/bin/sta'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'

    def paths(files):
        return ' '.join(p.relative_to(ROOT).as_posix() for p in files)

    def linux(command,log):
        with (out/log).open('w') as fd:
            result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                                  stdout=fd,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-3000:])

    linux(f'iverilog -g2012 -s tb_rne_dense_right -o {rel}/tb {paths([generic,specialized,tb])}','compile.log')
    linux(f'vvp {rel}/tb','simulation.log')
    assert re.search(r'PASS comparable=\s*10728 rejected=3', (out/'simulation.log').read_text())
    linux(f'yosys -Q -s {paths([formal])}','equivalence.log')
    assert 'SAT proof finished - no model found: SUCCESS!' in (out/'equivalence.log').read_text()
    map_src=mapping.read_text()
    first,second=map_src.split('design -load sources',1)
    (out/'mapping.ys').write_text(first+f'write_verilog -simple-lhs -noexpr -noattr {rel}/generic.v\n'
                                 +'design -load sources'+second+f'write_verilog -simple-lhs -noexpr -noattr {rel}/right.v\n')
    linux(f'yosys -Q -s {rel}/mapping.ys','mapping.log')
    results={}
    for name,top in (('generic','rne_pipe'),('right','kwt_rne_dense_right')):
        (out/f'{name}.tcl').write_text(f'''read_liberty {paths([liberty])}
read_verilog {rel}/{name}.v
link_design {top}
create_clock -name rne_clk -period 6.666667 [get_ports clk]
set_case_analysis 1 [get_ports rst_n]
set_input_delay -clock rne_clk 0 [get_ports {{req_valid req_a* req_shift* req_sat_bits* req_error req_tag* resp_ready}}]
set_output_delay -clock rne_clk 0 [all_outputs]
report_checks -path_delay max -group_count 4 -format full_clock_expanded -digits 6
set worst [lindex [find_timing_paths -path_delay max -group_count 4] 0]
puts "WORST_SETUP_SLACK [get_property $worst slack]"
exit
''')
        linux(f'{paths([sta])} -exit {rel}/{name}.tcl',f'{name}_sta.log')
        log=(out/f'{name}_sta.log').read_text()
        assert not re.search(r'^Error:',log,re.M),log
        slack=float(re.search(r'^WORST_SETUP_SLACK (\S+)',log,re.M)[1])
        area=float(re.search(rf"Chip area for module '\\{top}':\s+([\d.]+)",(out/'mapping.log').read_text())[1])/1e6
        results[name]=dict(standard_cell_area_mm2=area,setup_slack_ns=slack)
    sources=[Path(__file__),generic,specialized,tb,miter,mapping,formal,liberty,sta]
    report=dict(passed=True,scope='standalone RNE, ideal clock and zero port delays, no parasitics',
                legal_shifts=[38,48],sat_bits=8,bounded_equivalence_steps=4,simulation_comparisons=10728,
                results=results,source_sha256={paths([p]):sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps(results,indent=2))


if __name__=='__main__':
    main()
