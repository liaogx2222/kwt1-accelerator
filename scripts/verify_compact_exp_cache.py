"""Verify and map the exact exp cache using the frozen common packet."""
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
    fixture=ROOT/'testdata/input16_rtl_20261105/trim2_e203/common.bin.hex'
    assert sha(fixture)==json.loads((fixture.parent/'manifest.json').read_text())[fixture.name]
    rtl=ROOT/'rtl/block_transfer'
    cache=rtl/'kwt_compact_exp_cache.sv'
    tb=rtl/'tb_compact_exp_cache.sv'
    sram=ROOT/'rtl/input16_trim2/kwt_sram_sp.sv'
    flow=ROOT/'flow/compact_exp_nangate45.ys'
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'

    def linux(command,log):
        with (out/log).open('w') as fd:
            result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                                  stdout=fd,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-3500:])

    sources=' '.join(p.relative_to(ROOT).as_posix() for p in (cache,tb,sram))
    linux(f'iverilog -g2012 -DKWT_SIM -s tb_compact_exp_cache -o {rel}/tb {sources}','compile.log')
    linux(f'vvp {rel}/tb +root={fixture.relative_to(ROOT).as_posix()}','simulation.log')
    keys=('entries','packed_bytes','writes','bank_reads','max_read_banks','load_cycles')
    log=(out/'simulation.log').read_text()
    fields=list(map(int,re.search(r'PASS '+r' '.join(k+r'=\s*(\d+)' for k in keys),log).groups()))
    assert fields[:3]==[4097,5024,2512] and fields[4]==3
    linux(f'yosys -Q -s {flow.relative_to(ROOT).as_posix()}','mapping.log')
    area=float(re.search(r'Chip area for module .*?:\s+([\d.]+)',(out/'mapping.log').read_text())[1])/1e6
    sources=[Path(__file__),cache,tb,sram,flow,lib,fixture]
    result=dict(passed=True,scope='fixed-profile exp cache with eight physical A-bank model ports',
                **dict(zip(keys,fields)),mismatches=0,reused_A_macro_count=8,extra_private_macros=0,
                controller_standard_cell_area_mm2=area,throughput_tasks_per_second=None,mean_SoC_power_mW=None,
                complete_counted_area_mm2=None,
                source_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(result,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
