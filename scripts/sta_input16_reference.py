"""Partial, reproducible register-to-register STA for the full mapped S16 top."""
import argparse
import json
import re
import subprocess
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--mapped',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();m=a.mapped.resolve();assert not out.exists();out.mkdir(parents=True);rel=out.relative_to(ROOT).as_posix()
    for n,h in json.loads((m/'manifest.json').read_text()).items():assert sha(m/n)==h,n
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib';sta=ROOT/'tools/opensta_reference/root/usr/bin/sta';net=out/'mapped_simple.v';source=m/'mapped.json'
    script=out/'serialize.ys'
    script.write_text(f'read_json {source.relative_to(ROOT).as_posix()}\nwrite_verilog -noattr -noexpr -simple-lhs {rel}/mapped_simple.v\n')
    command=['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd /mnt/e/project/ChipCompetition/keyword-transformer && yosys -Q -T -s {rel}/serialize.ys']
    serialization=subprocess.run(command,capture_output=True,text=True)
    (out/'serialization.log').write_text(serialization.stdout+serialization.stderr)
    assert serialization.returncode==0,serialization.stderr[-2000:]
    macro=out/'blackboxes.v';macro.write_text('''module kwt_tech_sram_4096x16(input clk,en,we,input [11:0] addr,input [15:0] wdata,output [15:0] rdata);endmodule
module kwt_tech_sram_1024x16(input clk,en,we,input [9:0] addr,input [15:0] wdata,output [15:0] rdata);endmodule
''')
    tcl=f'''read_liberty {lib.relative_to(ROOT).as_posix()}
read_verilog {macro.relative_to(ROOT).as_posix()}
read_verilog {net.relative_to(ROOT).as_posix()}
link_design kwt_input16_icb_top
create_clock -name clk_ref -period 6.666667 [get_ports clk]
set_case_analysis 1 [get_ports rst_n]
set_case_analysis 0 [get_ports {{accel_abort drop_response}}]
check_setup -verbose > {rel}/check_setup.txt
set starts [all_registers -output_pins]
set ends [get_pins */D]
report_checks -from $starts -to $ends -path_delay max -group_count 10 -format full_clock_expanded -fields {{slew capacitance input_pin net}} -digits 6 > {rel}/setup_paths.txt
report_checks -unconstrained -group_count 16 -digits 6 > {rel}/unconstrained_examples.txt
set paths [find_timing_paths -from $starts -to $ends -path_delay max -group_count 100000 -endpoint_count 1]
set worst 1e30
set sum 0.0
set negative 0
foreach path $paths {{
 set slack [get_property $path slack]
 if {{$slack < $worst}} {{set worst $slack}}
 if {{$slack < 0}} {{set sum [expr {{$sum+$slack}}];incr negative}}
}}
puts "D_PINS [llength $ends]"
puts "ENDPOINTS [llength $paths]"
puts "WNS $worst"
puts "TNS $sum"
puts "NEGATIVE $negative"
puts "DONE_REFERENCE_STA"
exit
''';(out/'run.tcl').write_text(tcl)
    cmd=f'cd /mnt/e/project/ChipCompetition/keyword-transformer && {sta.relative_to(ROOT).as_posix()} -exit {rel}/run.tcl'
    p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',cmd],capture_output=True,text=True);text=p.stdout+p.stderr;(out/'execution.log').write_text(text);assert p.returncode==0 and 'DONE_REFERENCE_STA' in text and not re.search(r'^Error:',text,re.M),text[-3000:]
    def get(n):return float(re.search('^'+n+r' (\S+)',text,re.M)[1])
    result=dict(passed=True,period_ns=6.666667,reference_reg2reg_WNS_ns=get('WNS'),reference_reg2reg_TNS_ns=get('TNS'),register_D_pins=int(get('D_PINS')),
        setup_endpoints_analyzed=int(get('ENDPOINTS')),negative_setup_endpoints=int(get('NEGATIVE')),scope='Nangate45 ideal-clock standard-cell register-to-register setup only',
        missing=['SRAM arcs/load/timing','CPU and external I/O delays','physical RC/CTS','reset recovery and removal','other corners and SMIC40'],complete_150MHz_signoff=False,
        serialization='Yosys read_json then write_verilog -simple-lhs, no logic passes')
    (out/'verification.json').write_text(json.dumps(result,indent=2));bound=[Path(__file__),sta,lib,source,m/'verification.json'];(out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in bound},indent=2));(out/'manifest.json').write_text(json.dumps({f.name:sha(f) for f in out.iterdir() if f.is_file()},indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
