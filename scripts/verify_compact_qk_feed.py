"""Verify the physical resident-Q/K to A-cache to existing 16x16 MAC path."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve();out.mkdir(parents=True)
    rtl=ROOT/'rtl/block_transfer'
    trim=ROOT/'rtl/input16_trim2'
    baseline=ROOT/'testdata/input16_rtl_20261105/p4_e203_compact_qkv_resident_v4'
    inherited=ROOT/'testdata/input16_rtl_20261105/p3_e203_compact_ln2_v2/arithmetic.sv'
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    core=rtl/'kwt_compact_qk_feed.sv'
    resident=rtl/'kwt_compact_qkv_resident.sv'
    sources=[core,rtl/'tb_compact_qk_feed.sv',resident,trim/'kwt_sram_sp.sv',inherited]
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def rel(path):
        return path.relative_to(ROOT).as_posix()
    prior=json.loads((baseline/'verification.json').read_text())
    for path in (resident,inherited,trim/'kwt_sram_sp.sv'):
        assert sha(path)==prior['source_sha256'][rel(path)],path

    def run(command,log):
        with (out/log).open('w') as fd:
            result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                                  stdout=fd,stderr=subprocess.STDOUT)
        text=(out/log).read_text()
        assert result.returncode==0,(log,text[-2000:])
        return text

    def map_control():
        script=out/'mapping.ys'
        script.write_text(f'''read_verilog -sv {rel(core)}
synth -top kwt_compact_qk_feed -noabc -noshare
read_liberty -lib {rel(lib)}
dfflibmap -liberty {rel(lib)}
abc -liberty {rel(lib)}
clean
check -assert
stat -liberty {rel(lib)}
write_json {rel(out/'mapped.json')}
''')
        text=run(f'yosys -Q -T -s {rel(script)}','mapping.log')
        return float(re.search(r'Chip area for module .*: ([0-9.]+)',text)[1])/1e6

    with ThreadPoolExecutor(max_workers=1) as pool:
        mapped=pool.submit(map_control)
        run(f'iverilog -g2012 -DKWT_SIM -s tb_compact_qk_feed -o {rel(out/"test.vvp")} '
            +' '.join(rel(p) for p in sources),'build.log')
        text=run(f'vvp {rel(out/"test.vvp")}','simulation.log')
        match=re.search(r'PASS resident QK tiles=49 scores=9801 tile_cycles=(\d+) max_tile=(\d+) stalls=(\d+)',text)
        assert match,text
        cycles,max_tile,stalls=map(int,match.groups())
        area=mapped.result()
    inputs=[Path(__file__),*sources,lib,baseline/'verification.json',baseline/'manifest.json']
    report=dict(passed=True,tiles=49,scores=9801,mismatches=0,tile_cycles=cycles,max_tile=max_tile,stalls=stalls,
                feeder_standard_cell_mm2=area,A_cache_bytes=1024,
                scope='standalone resident SRAM to existing MAC; deterministic Q/K fixture; control area excludes SRAM and MAC',
                integrated_E203=False,source_sha256={rel(p):sha(p) for p in inputs})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(text,end='')


if __name__=='__main__':
    main()
