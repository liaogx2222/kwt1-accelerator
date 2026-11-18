"""Full newly-added accelerator+MMIO+ICB mapping with all private SRAM accounted."""
import argparse
from collections import Counter
import json
import re
import subprocess
import time
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);r=ROOT/'rtl/input16_signed';base=ROOT/'testdata/input16_rtl_20261105';rel=out.relative_to(ROOT).as_posix()
    for name in ['derivation','sign_extension','layer_smoke','layer_all']:
        for f,h in json.loads((base/name/'source_bindings.json').read_text()).items():assert sha(ROOT/f)==h,(name,f)
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib';top='kwt_input16_icb_top'
    names=['kwt_sram_sp.sv','kwt_tech_sram_blackbox.sv','kwt_mac8x8.sv','kwt_iterative.sv','kwt_math.sv','kwt_packet_loader.sv','kwt_layer_banked.sv','kwt1_accel.sv','kwt1_mmio.sv']
    sources=[ROOT/'rtl/micro/mul_pipe.sv',ROOT/'rtl/micro/rne_pipe.sv',*[r/n for n in names],ROOT/'rtl/reference/icb_kwt_bridge.sv',ROOT/'rtl/input16_icb_top.sv']
    paths=' '.join(s.relative_to(ROOT).as_posix() for s in sources);library=lib.relative_to(ROOT).as_posix();include=(r/'generated').relative_to(ROOT).as_posix()
    (out/'abc.constr').write_text('set_driving_cell BUF_X1\nset_load 3.898\n')
    (out/'synth.ys').write_text(f'''read_verilog -sv -DKWT_TECH_SRAM -I{include} {paths}
hierarchy -check -top {top}
synth -top {top} -flatten -noabc -noshare
read_liberty -lib {library}
dfflibmap -liberty {library}
abc -liberty {library} -constr {rel}/abc.constr -D 6667
clean
check -assert
tee -o {rel}/stat.json stat -json -liberty {library}
write_json {rel}/mapped.json
write_verilog -noattr -noexpr {rel}/mapped.v
design -reset
read_liberty -ignore_miss_func -ignore_miss_dir {library}
write_verilog -noattr {rel}/functional_cells.v
''')
    def run(command,name):
        p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+command],capture_output=True,text=True);(out/(name+'.log')).write_text(p.stdout+p.stderr);assert p.returncode==0,(name,p.stdout[-1500:],p.stderr[-1500:]);return p.stdout
    start=time.time();run(f'yosys -Q -T -l {rel}/yosys.log -s {rel}/synth.ys','mapping')
    cells=json.loads((out/'mapped.json').read_text())['modules'][top]['cells'];counts=Counter(c['type'] for c in cells.values());macros=counts.pop('kwt_tech_sram_4096x16');assert macros==20
    areas={n:float(v) for n,v in re.findall(r'cell\s*\(\s*(\w+)\s*\)\s*\{.*?area\s*:\s*([\d.]+)',lib.read_text(),re.S)}
    assert set(counts)<=set(areas) and not any(t.startswith(('DLH','DLL')) for t in counts);cell_area=sum(areas[k]*v for k,v in counts.items());stat=json.loads((out/'stat.json').read_text());assert abs(cell_area-stat['modules']['\\'+top]['area'])<.02
    sram_path=ROOT/'testdata/full_scope_20261105/sram_cacti/verification.json';sram=json.loads(sram_path.read_text())['models']['4096x16'];sram_area=macros*sram['area_mm2']
    report=dict(passed=True,full_new_logic_mapped=True,includes=['complete 12-layer encoder','packet CRC and banking','MMIO','added ICB bridge'],top=top,array='8x8 input16_signed',
        technology='Nangate45 typical 1.1V 25C + CACTI 45nm 300K analytic SRAM components; different model provenance, no PVT/signoff equivalence',
        standard_cells=sum(counts.values()),sequential_cells=sum(n for t,n in counts.items() if t.startswith(('DFF','SDFF'))),counts=dict(counts),
        standard_cell_area_mm2=cell_area/1e6,private_SRAM_macros=macros,private_SRAM_geometry='4096x16 1RW',private_SRAM_bytes=163840,
        private_SRAM_analytical_per_macro_mm2=sram['area_mm2'],private_SRAM_analytical_total_mm2=sram_area,
        complete_counted_area_open_reference_mm2=cell_area/1e6+sram_area,complete_area_scope_included=True,
        official_complete_counted_area_mm2=None,official_missing=['designated standard-cell library','characterized designated exact private macro area'],
        fixed_platform_area_reported_separately=dict(CPU_mm2=None,shared_SRAM_mm2=None,fixed_bus_mm2=None),
        complete_gate_regression=False,complete_STA_signoff=False,SoC_average_power_mW=None,elapsed_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2));bound=[Path(__file__),*sources,r/'generated/kwt_profile.svh',lib,sram_path]
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in bound},indent=2));(out/'manifest.json').write_text(json.dumps({f.name:sha(f) for f in out.iterdir() if f.is_file()},indent=2));print(json.dumps({k:v for k,v in report.items() if k!='counts'},indent=2))


if __name__=='__main__':main()
