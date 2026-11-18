"""Map the small-bank wrapper and integrate it into the actual full mapped top."""
import argparse
from collections import Counter
import copy
import json
import re
import subprocess
from pathlib import Path
from local_tools import ROOT,sha


TOP='kwt_input16_icb_top'
LEAF='kwt_weight_2048x16'
LARGE='kwt_tech_sram_4096x16'
SMALL='kwt_tech_sram_1024x16'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['leaf','merge'],required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);rel=out.relative_to(ROOT).as_posix();base=ROOT/'testdata/input16_rtl_20261105';lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib';library=lib.relative_to(ROOT).as_posix();bound=[Path(__file__),lib]
    def run(command,name):
        r=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+command],capture_output=True,text=True);(out/(name+'.log')).write_text(r.stdout+r.stderr);assert r.returncode==0,(name,r.stdout[-1500:],r.stderr[-1500:]);return r.stdout
    def check(folder):
        for f,h in json.loads((folder/'manifest.json').read_text()).items():assert sha(folder/f)==h,(folder,f)
        for f,h in json.loads((folder/'source_bindings.json').read_text()).items():assert sha(ROOT/f)==h,(folder,f)
        bound.extend([folder/'manifest.json',folder/'source_bindings.json'])
    areas={n:float(v) for n,v in re.findall(r'cell\s*\(\s*(\w+)\s*\)\s*\{.*?area\s*:\s*([\d.]+)',lib.read_text(),re.S)}
    if a.stage=='leaf':
        source=ROOT/'rtl/kwt_weight_2048x16.sv';bound.append(source);p=source.relative_to(ROOT).as_posix()
        (out/'leaf.ys').write_text(f'''read_verilog -sv -DKWT_TECH_SRAM {p}
synth -top {LEAF} -flatten -noabc -noshare
read_liberty -lib {library}
dfflibmap -liberty {library}
abc -liberty {library}
clean
check -assert
write_json {rel}/leaf.json
''');run(f'yosys -Q -T -s {rel}/leaf.ys','mapping')
        cells=json.loads((out/'leaf.json').read_text())['modules'][LEAF]['cells'];counts=Counter(c['type'] for c in cells.values());assert counts.pop(SMALL)==2 and set(counts)<=set(areas)
        report=dict(passed=True,private_1024x16_macros=2,wrapper_cell_counts=dict(counts),wrapper_area_um2=sum(areas[t]*n for t,n in counts.items()))
    else:
        mapped=base/'mapping_full';leaf=base/'trim_leaf';check(mapped);check(leaf);check(base/'trim2_native');check(base/'trim2_e203')
        original=json.loads((mapped/'mapped.json').read_text());child=json.loads((leaf/'leaf.json').read_text())['modules'];wrapper=child[LEAF];top=original['modules'][TOP];cells=top['cells'];old_counts=Counter(c['type'] for c in cells.values())
        next_bit=max(v for net in top['netnames'].values() for v in net['bits'] if isinstance(v,int))+1;names=[]
        for i in [1,3,5,7]:
            found=[n for n,c in cells.items() if c['type']==LARGE and f'bank[{i}]' in n];assert len(found)==1,found;name=found[0];names.append(name);parent=cells.pop(name)
            bit_map={}
            for port,details in wrapper['ports'].items():
                actual=parent['connections'][port];assert len(actual)==len(details['bits'])
                for key,value in zip(details['bits'],actual):
                    assert key not in bit_map or bit_map[key]==value;bit_map[key]=value
            def map_bit(v):
                nonlocal next_bit
                if not isinstance(v,int):return v
                if v not in bit_map:bit_map[v]=next_bit;next_bit+=1
                return bit_map[v]
            for n,c in wrapper['cells'].items():
                q=copy.deepcopy(c);q['connections']={p:[map_bit(v) for v in bits] for p,bits in c['connections'].items()};cells[name+'.'+n]=q
            for n,d in wrapper['netnames'].items():
                q=copy.deepcopy(d);q['bits']=[map_bit(v) for v in d['bits']];top['netnames'][name+'.'+n]=q
        original['modules'][SMALL]=child[SMALL];(out/'mapped.json').write_text(json.dumps(original,separators=(',',':')))
        (out/'emit.ys').write_text(f'''read_json {rel}/mapped.json
hierarchy -check -top {TOP}
check -assert
tee -o {rel}/stat.json stat -json -liberty {library}
write_verilog -noattr -noexpr {rel}/mapped.v
''');run(f'yosys -Q -T -s {rel}/emit.ys','structural_check')
        counts=Counter(c['type'] for c in cells.values());assert counts.pop(LARGE)==16 and counts.pop(SMALL)==8;old_counts.pop(LARGE)
        added=Counter(c['type'] for c in wrapper['cells'].values());added.pop(SMALL);assert counts==old_counts+Counter({t:n*4 for t,n in added.items()})
        std=sum(areas[t]*n for t,n in counts.items());stat=json.loads((out/'stat.json').read_text());assert abs(std-stat['modules']['\\'+TOP]['area'])<.02
        sram=ROOT/'testdata/full_scope_20261105/sram_cacti/verification.json';bound.append(sram);macro=json.loads(sram.read_text())['models'];mem=16*macro['4096x16']['area_mm2']+8*macro['1024x16']['area_mm2'];old=json.loads((mapped/'verification.json').read_text())
        report=dict(passed=True,full_new_logic_mapped=True,top=TOP,reused_mapped_full_logic_unchanged=True,replaced_macro_instances=names,
            added_wrapper_cells=dict(added),standard_cells=sum(counts.values()),standard_cell_area_mm2=std/1e6,private_SRAM_physical_macros={'4096x16':16,'1024x16':8},private_SRAM_bytes=147456,
            private_SRAM_analytical_area_mm2=mem,complete_counted_area_open_reference_mm2=std/1e6+mem,
            reference_area_reduction_mm2=old['complete_counted_area_open_reference_mm2']-std/1e6-mem,
            complete_area_scope_included=True,scope='complete new logic with mapped wrapper cells and analytic SRAM, Nangate45+CACTI; not designated-area signoff',
            official_complete_counted_area_mm2=None,complete_STA_signoff=False,full_mapped_functional_regression=False)
    (out/'verification.json').write_text(json.dumps(report,indent=2));(out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in bound},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
