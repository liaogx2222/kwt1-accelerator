"""Reference setup timing for the mapped compact supply/Dense partitions."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--mapped',type=Path,nargs='+',required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True)
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    sta=ROOT/'tools/opensta_reference/root/usr/bin/sta'

    def path(p):
        return p.relative_to(ROOT).as_posix()

    def run(cmd,log):
        with log.open('w') as fd:
            p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {cmd}'],
                             stdout=fd,stderr=subprocess.STDOUT)
        if p.returncode:
            raise RuntimeError(log.read_text(errors='replace')[-4000:])

    results={}
    sources=[Path(__file__),lib,sta]
    for entry in args.mapped:
        entry=entry.resolve()
        data=entry/'verification.json'
        mapped=entry/'mapped.json'
        m=json.loads((entry/'manifest.json').read_text())
        assert sha(data)==m[data.name] and sha(mapped)==m[mapped.name]
        kind=json.loads(data.read_text())['rq']
        folder=out/kind
        folder.mkdir()
        net=folder/'mapped_simple.v'
        run(f'yosys -Q -p \'read_json {path(mapped)}; write_verilog -simple-lhs -noattr -noexpr {path(net)}\'',
            folder/'serialization.log')
        tcl=folder/'setup.tcl'
        tcl.write_text(f'''read_liberty {path(lib)}
read_verilog {path(net)}
link_design e203_subsys_nice_core
create_clock -name dense_clk -period 6.666667 [get_ports nice_clk]
set_case_analysis 1 [get_ports nice_rst_n]
check_setup -verbose > {path(folder/'uncovered.txt')}
set launches [all_registers -output_pins]
set captures [get_pins */D]
report_checks -from $launches -to $captures -path_delay max -group_count 5 -digits 6 > {path(folder/'critical.txt')}
set p [find_timing_paths -from $launches -to $captures -path_delay max -group_count 100000 -endpoint_count 1]
set wns 1e30
set tns 0
set negative 0
foreach item $p {{
 set s [get_property $item slack]
 if {{$s<$wns}} {{set wns $s}}
 if {{$s<0}} {{set tns [expr {{$tns+$s}}]; incr negative}}
}}
puts "DENSE_STA [llength $captures] [llength $p] $wns $tns $negative"
exit
''')
        log=folder/'sta.log'
        run(f'{path(sta)} -exit {path(tcl)}',log)
        text=log.read_text()
        assert not re.search(r'^Error:',text,re.M),text[-3500:]
        values=re.search(r'^DENSE_STA (\d+) (\d+) (\S+) (\S+) (\d+)',text,re.M)
        assert int(values[2])>0
        results[kind]=dict(register_D_pins=int(values[1]),checked_endpoints=int(values[2]),
                           WNS_ns=float(values[3]),TNS_ns=float(values[4]),negative_endpoints=int(values[5]))
        sources.extend((data,mapped))
    report=dict(passed=True,scope='Nangate45 ideal-clock register-to-register setup only',
                clock_period_ns=6.666667,results=results,complete_signoff=False,
                excluded=['external I/O','SRAM arcs','hold','physical clock/parasitics','other corners'],
                source_sha256={path(p):sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*')
                                                if p.is_file()},indent=2))
    print(json.dumps(results,indent=2))


if __name__=='__main__':
    main()
