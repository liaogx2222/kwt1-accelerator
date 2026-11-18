"""Map the FFN integration while reusing and checking unchanged gate submodules."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from local_tools import ROOT, sha
from run_e203_compact_dense99 import area_report


def graph_digest(module):
    digest=hashlib.sha256()
    ids={}
    def normalize(bits):
        return [ids.setdefault(bit,len(ids)) if isinstance(bit,int) else bit for bit in bits]
    for name,port in sorted(module['ports'].items()):
        digest.update(json.dumps([name,port['direction'],normalize(port['bits'])]).encode())
    for name,cell in sorted(module.get('cells',{}).items()):
        connections=[[pin,normalize(bits)] for pin,bits in sorted(cell['connections'].items())]
        digest.update(json.dumps([name,cell['type'],cell['parameters'],connections],sort_keys=True).encode())
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dense99',type=Path,required=True)
    parser.add_argument('--writeback',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    dense,writeback,out=(p.resolve() for p in (args.dense99,args.writeback,args.output))
    original=dense/'mapped.json'
    top=writeback/'kwt_e203_dense_supply.sv'
    top_module='e203_subsys_nice_core'
    for folder,files in ((dense,[original]),(writeback,[top,writeback/'verification.json'])):
        manifest=json.loads((folder/'manifest.json').read_text())
        for p in files:
            assert sha(p)==manifest[p.name],p
    rtl=ROOT/'rtl/block_transfer'
    new_logic=[top,rtl/'kwt_compact_ffn_link.sv',rtl/'kwt_compact_ffn_writeback.sv']
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    out.mkdir(parents=True)

    def rel(p):
        return p.relative_to(ROOT).as_posix()

    (out/'mapping.ys').write_text(f'''read_json {rel(original)}
read_verilog -sv -overwrite {" ".join(rel(p) for p in new_logic)}
synth -top {top_module} -noabc -noshare
dfflibmap -liberty {rel(lib)}
abc -liberty {rel(lib)}
clean
check -assert
stat -liberty {rel(lib)}
write_json {rel(out/'mapped.json')}
''')
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    with (out/'mapping.log').open('w') as fd:
        p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',
                          f'cd {cwd} && yosys -Q -s {rel(out/"mapping.ys")}'],
                         stdout=fd,stderr=subprocess.STDOUT)
    if p.returncode:
        raise RuntimeError((out/'mapping.log').read_text(errors='replace')[-3000:])
    before=json.loads(original.read_text())['modules']
    after=json.loads((out/'mapped.json').read_text())['modules']
    unchanged=[name for name,mod in before.items() if name!=top_module and mod.get('cells')]
    for name in unchanged:
        assert name in after and graph_digest(before[name])==graph_digest(after[name]),name
    area=area_report(out,lib)
    base_area=json.loads((dense/'verification.json').read_text())['supply_dense_partition_standard_cell_mm2']
    sources=[Path(__file__),ROOT/'scripts/run_e203_compact_dense99.py',original,dense/'verification.json',
             writeback/'verification.json',lib,*new_logic]
    report=dict(passed=True,scope='hierarchical compact supply, Dense, GELU and FC2 A-bank result handoff',
                supply_dense_ffn_partition_standard_cell_mm2=area,previous_dense_partition_standard_cell_mm2=base_area,
                added_partition_standard_cell_mm2=area-base_area,unchanged_gate_modules=unchanged,
                private_macro_count=20,private_sram_bytes=65536,
                throughput_tasks_per_second=None,mean_SoC_power_mW=None,complete_counted_area_mm2=None,
                source_sha256={rel(p):sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':
    main()
