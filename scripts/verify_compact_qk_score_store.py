"""Verify the one-group physical B score store and map its controller."""
import argparse
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
    core=rtl/'kwt_compact_qk_score_store.sv'
    sources=[core,rtl/'tb_compact_qk_score_store.sv',ROOT/'rtl/input16_trim2/kwt_sram_sp.sv']
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def rel(path):
        return path.relative_to(ROOT).as_posix()
    def run(command,log):
        result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                              capture_output=True,text=True)
        text=result.stdout+result.stderr
        (out/log).write_text(text)
        assert result.returncode==0,(log,text[-2000:])
        return text
    run(f'iverilog -g2012 -DKWT_SIM -s tb_compact_qk_score_store -o {rel(out/"test.vvp")} '
        +' '.join(rel(p) for p in sources),'build.log')
    result=run(f'vvp {rel(out/"test.vvp")}','simulation.log')
    match=re.search(r'PASS physical B scores=3465 stalls=(\d+) turnovers=(\d+) cancel=1',result)
    assert match,result
    script=out/'mapping.ys'
    script.write_text(f'''read_verilog -sv {rel(core)}
synth -top kwt_compact_qk_score_store -noabc -noshare
read_liberty -lib {rel(lib)}
dfflibmap -liberty {rel(lib)}
abc -liberty {rel(lib)}
clean
check -assert
stat -liberty {rel(lib)}
write_json {rel(out/'mapped.json')}
''')
    mapping=run(f'yosys -Q -T -s {rel(script)}','mapping.log')
    area=float(re.search(r'Chip area for module .*: ([0-9.]+)',mapping)[1])/1e6
    report=dict(passed=True,read_codes=3465,mismatches=0,stalls=int(match[1]),turnovers=int(match[2]),
                full_group_bytes=6336,stalled_cancel=True,standard_cell_mm2=area,integrated_E203=False,
                scope='standalone B score SRAM with synthetic signed scores; controller area only',
                source_sha256={rel(p):sha(p) for p in (Path(__file__),*sources,lib)})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(result,end='')


if __name__=='__main__':
    main()
