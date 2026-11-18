"""Single-buffer specialization, with accurate published scope metadata."""
import argparse
import json
import sys
from pathlib import Path
from local_tools import ROOT,sha
import synth_arithmetic16_banked as flow

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve()
    sys.argv=[str(Path(flow.__file__)),'--output',str(out),'--single'];flow.main()
    report=json.loads((out/'verification.json').read_text());report['scope']='single-buffer 16x16 MAC plus independent 4-lane RQ; no SRAM/nonlinear/controller/SoC'
    report['accumulator_buffers']=1;assert report['sequential_cells']<10000
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    bindings=json.loads((out/'source_bindings.json').read_text());bindings[Path(__file__).relative_to(ROOT).as_posix()]=sha(Path(__file__))
    (out/'source_bindings.json').write_text(json.dumps(bindings,indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'},indent=2))

if __name__=='__main__':main()
