"""Reviewed two-line specialization of the same mapping/STA flow.

Archive the exact executed runner; the original live mapping script is not
modified while its independent structural experiment is running.
"""
import argparse
import json
import sys
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--shared',action='store_true');ap.add_argument('--single',action='store_true');args=ap.parse_args();out=args.output.resolve();assert not out.exists()
    variant='single' if args.single else 'shared' if args.shared else 'banked'
    assert (ROOT/f'testdata/resident_core_20261105/rtl_{variant}/verification.json').is_file(),'Wait for functional qualification'
    base=ROOT/'scripts/synth_arithmetic16.py';text=base.read_text()
    old="source=ROOT/('rtl/experimental/kwt_arithmetic16_structural.sv' if args.structural else 'rtl/experimental/kwt_arithmetic16.sv');library="
    new=f"source=ROOT/'rtl/experimental/kwt_arithmetic16_{variant}.sv';library="
    assert text.count(old)==1;text=text.replace(old,new)
    old="validated='rtl_structural' if args.structural else 'rtl_partition'";assert text.count(old)==1;text=text.replace(old,f"validated='rtl_{variant}'")
    runner=out.parent/(out.name+'_executed_runner.py');assert not runner.exists();runner.write_text(text)
    sys.argv=[str(runner),'--output',str(out)];namespace={'__file__':str(runner),'__name__':'__main__'};exec(compile(text,str(runner),'exec'),namespace)
    bindings=json.loads((out/'source_bindings.json').read_text())
    for path in [Path(__file__),base]:bindings[path.relative_to(ROOT).as_posix()]=sha(path)
    (out/'source_bindings.json').write_text(json.dumps(bindings,indent=2))
    (out/'runner_derivation.json').write_text(json.dumps(dict(base=base.relative_to(ROOT).as_posix(),base_sha256=sha(base),executed_runner=runner.relative_to(ROOT).as_posix(),runner_sha256=sha(runner),exact_replacements=2),indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'},indent=2))

if __name__=='__main__':main()
