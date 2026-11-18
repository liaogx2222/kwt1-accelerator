"""Actual Nangate45 arithmetic-partition mapping and scoped reference STA."""
import argparse
import collections
import json
import re
import subprocess
import time
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--structural',action='store_true');args=ap.parse_args();out=args.output.resolve();assert not out.exists();out.mkdir(parents=True);rel=out.relative_to(ROOT).as_posix()
    source=ROOT/('rtl/experimental/kwt_arithmetic16_structural.sv' if args.structural else 'rtl/experimental/kwt_arithmetic16.sv');library=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    sources=[Path(__file__),source,ROOT/'rtl/micro/mul_pipe.sv',ROOT/'rtl/micro/rne_pipe.sv',library]
    validated='rtl_structural' if args.structural else 'rtl_partition'
    for name,digest in json.loads((ROOT/f'testdata/resident_core_20261105/{validated}/source_bindings.json').read_text()).items():assert sha(ROOT/name)==digest,name
    src=' '.join(p.relative_to(ROOT).as_posix() for p in sources[1:4]);lib=library.relative_to(ROOT).as_posix()
    (out/'abc.constr').write_text('set_driving_cell BUF_X1\nset_load 3.898\n')
    flow=f'''read_verilog -sv {src}
synth -top kwt_arithmetic16 -flatten -noabc -noshare
read_liberty -lib {lib}
dfflibmap -liberty {lib}
abc -liberty {lib} -constr {rel}/abc.constr -D 6667
clean
check -assert
tee -o {rel}/stat.json stat -json -liberty {lib}
write_json {rel}/mapped.json
write_verilog -noattr -noexpr {rel}/mapped.v
design -reset
read_liberty -ignore_miss_func -ignore_miss_dir {lib}
write_verilog -noattr {rel}/functional_cells.v
'''
    (out/'map.ys').write_text(flow)
    def run(command,name):
        r=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+command],capture_output=True,text=True)
        (out/(name+'.log')).write_text(r.stdout+r.stderr);assert r.returncode==0,(name,r.stdout[-1800:],r.stderr[-1000:]);return r.stdout
    started=time.time();run(f'yosys -Q -T -l {rel}/yosys.log -s {rel}/map.ys','mapping')
    net=json.loads((out/'mapped.json').read_text())['modules']['kwt_arithmetic16'];counts=collections.Counter(c['type'] for c in net['cells'].values())
    areas={name:float(a) for name,a in re.findall(r'cell\s*\(\s*(\w+)\s*\)\s*\{.*?area\s*:\s*([\d.]+)',library.read_text(),re.S)}
    assert set(counts)<=set(areas);assert not any(k.startswith(('DLH','DLL')) for k in counts)
    area=sum(areas[k]*v for k,v in counts.items());stat=json.loads((out/'stat.json').read_text());assert abs(area-stat['modules']['\\kwt_arithmetic16']['area'])<.02
    # Clock-only reg-to-reg scope, explicitly leaving real input/output timing
    # and reset transitions uncovered. In particular external MAC operands are
    # not register launch points in this partition and are not signed off.
    sta=f'''read_liberty {lib}
read_verilog {rel}/mapped.v
link_design kwt_arithmetic16
create_clock -name arithmetic_clk -period 6.666667 [get_ports clk]
set_case_analysis 1 [get_ports rst_n]
check_setup -verbose > {rel}/check_setup.txt
set starts [all_registers -output_pins]
set ends [get_pins */D]
report_checks -from $starts -to $ends -path_delay max -group_count 8 -format full_clock_expanded -fields {{slew capacitance input_pin net}} -digits 6 > {rel}/setup_paths.txt
report_checks -unconstrained -group_count 12 -digits 6 > {rel}/unconstrained_examples.txt
set paths [find_timing_paths -from $starts -to $ends -path_delay max -group_count 100000 -endpoint_count 1]
set wns 1e30
set tns 0
set neg 0
foreach path $paths {{
 set s [get_property $path slack]
 if {{$s < $wns}} {{set wns $s}}
 if {{$s < 0}} {{set tns [expr {{$tns+$s}}]; incr neg}}
}}
puts "D_PINS [llength $ends]"
puts "SETUP_PATHS [llength $paths]"
puts "WNS $wns"
puts "TNS $tns"
puts "NEGATIVE $neg"
puts "PARTITION_STA_DONE"
exit
'''
    (out/'reference_sta.tcl').write_text(sta)
    result=run(f'tools/opensta_reference/root/usr/bin/sta -exit {rel}/reference_sta.tcl','sta');assert 'PARTITION_STA_DONE' in result and not re.search(r'^Error:',result,re.M)
    def value(name):return float(re.search(r'^'+name+r' (\S+)',result,re.M)[1])
    report=dict(mapping_passed=True,top='kwt_arithmetic16',scope='dual-buffer 16x16 MAC plus independent 4-lane RQ, no SRAM/nonlinear/controller/SoC',
        technology='Nangate45 typical 1.1V 25C research reference',standard_cells=sum(counts.values()),
        sequential_cells=sum(v for k,v in counts.items() if k.startswith(('DFF','SDFF'))),standard_cell_area_um2=area,standard_cell_area_mm2=area/1e6,
        SRAM_macros=0,SRAM_area=None,full_encoder_area=None,power=None,gate_functional_regression='pending',counts=dict(counts),
        reference_clock_ns=6.666667,reference_reg2reg_WNS_ns=value('WNS'),reference_reg2reg_TNS_ns=value('TNS'),negative_setup_endpoints=int(value('NEGATIVE')),
        register_D_pins=int(value('D_PINS')),setup_endpoints_analyzed=int(value('SETUP_PATHS')),
        complete_STA_signoff=False,uncovered=['external MAC input-to-accumulator timing','all real I/O delays/drives/loads','reset recovery/removal','SRAM/controller/SoC','clock tree/parasitics/other PVT/SMIC40'],
        full_encoder_RTL=False,all_competition_targets_met=False,elapsed_seconds=time.time()-started)
    (out/'verification.json').write_text(json.dumps(report,indent=2));(out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps({k:v for k,v in report.items() if k!='counts'},indent=2))


if __name__=='__main__':main()
