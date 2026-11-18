"""Validate the actual mapped drain control with same-library functional cells."""
import argparse
import json
from pathlib import Path
import subprocess

from local_tools import ROOT, sha


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    model,out=args.model.resolve(),args.output.resolve()
    mapping=model/'mapped.json'
    manifest=json.loads((model/'manifest.json').read_text())
    assert sha(mapping)==manifest[mapping.name]
    out.mkdir(parents=True)
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    tb=ROOT/'rtl/block_transfer/tb_compact_ln2_drain.sv'
    name='kwt_compact_ln2_drain'
    original=json.loads(mapping.read_text())
    leaf=out/'leaf.json'
    leaf.write_text(json.dumps(dict(creator=original['creator'],modules={name:original['modules'][name]})))
    def rel(path):
        return path.relative_to(ROOT).as_posix()
    (out/'emit.ys').write_text(f'''read_json {rel(leaf)}
write_verilog -noattr -noexpr {rel(out/'leaf.v')}
design -reset
read_liberty -ignore_miss_func -ignore_miss_dir {rel(lib)}
write_verilog -noattr {rel(out/'cells.v')}
''')
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def run(command,log):
        result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                              capture_output=True,text=True)
        (out/log).write_text(result.stdout+result.stderr)
        assert result.returncode==0,(log,result.stdout,result.stderr)
        return result.stdout
    run(f'yosys -Q -s {rel(out/"emit.ys")}','emit.log')
    run(f'iverilog -g2012 -s tb_compact_ln2_drain -o {rel(out/"test.vvp")} '
        f'{rel(tb)} {rel(out/"leaf.v")} {rel(out/"cells.v")}','build.log')
    result=run(f'vvp {rel(out/"test.vvp")}','simulation.log')
    assert 'PASS mapped drain full_frames=3 words=2376 turnovers=2373 cancel=1 reset=1' in result
    report=dict(passed=True,gate_scope=name,full_frames=3,words=2376,turnovers=2373,
                stalled_cancel=True,stalled_hard_reset=True,whole_top_gate_regression=False,
                source_sha256={rel(p):sha(p) for p in (Path(__file__),mapping,tb,lib)})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(result,end='')


if __name__=='__main__':
    main()
