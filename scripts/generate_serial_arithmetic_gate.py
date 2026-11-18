"""Low-memory mapped regression: exit Verilator generation before make."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from local_tools import ROOT,sha
import validate_arithmetic16 as original
import resume_arithmetic_gate_cpp as recovery

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--mapped',type=Path,required=True);ap.add_argument('--single',action='store_true');a=ap.parse_args();out=a.output.resolve();mapped=a.mapped.resolve();generation=out.parent/(out.name+'_generation')
    assert not out.exists() and not generation.exists();generation.mkdir(parents=True);original.vectors(generation)
    if a.single:
        tb=(generation/'tb.sv').read_text().replace('c%2','0').replace('||bank_overlap==0','');(generation/'tb.sv').write_text(tb)
    rel=generation.relative_to(ROOT).as_posix();cmd=f'verilator --cc --exe --main --timing --top-module tb -Wno-fatal --output-split 18000 --output-split-cfuncs 200 --Mdir {rel}/model {mapped.relative_to(ROOT).as_posix()}/mapped.v {mapped.relative_to(ROOT).as_posix()}/functional_cells.v {rel}/tb.sv'
    result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+cmd],capture_output=True,text=True)
    (generation/'generation.log').write_text(result.stdout+result.stderr);assert result.returncode==0,(result.stdout[-1000:],result.stderr[-1000:])
    # Generation process is gone here: its netlist AST cannot overlap PCH.
    sys.argv=[str(Path(recovery.__file__)),'--output',str(out),'--generated',str(generation/'model'),'--mapped',str(mapped)]+(['--single'] if a.single else [])
    recovery.main();bindings=json.loads((out/'source_bindings.json').read_text())
    bindings[Path(__file__).relative_to(ROOT).as_posix()]=sha(Path(__file__));bindings[(generation/'generation.log').relative_to(ROOT).as_posix()]=sha(generation/'generation.log')
    (out/'source_bindings.json').write_text(json.dumps(bindings,indent=2));(out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and p.name!='manifest.json'},indent=2))

if __name__=='__main__':main()
