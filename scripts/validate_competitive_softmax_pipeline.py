"""Same resident fixtures/paired IO tests for bounded two-row Softmax."""
import argparse
import json
import sys
from pathlib import Path
from local_tools import ROOT,sha
import validate_competitive_resident_attention as qualified
from integer_model.competitive_softmax_pipeline import SoftmaxPipelinedAttention


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['run','check'],default='check');ap.add_argument('--scope',choices=['smoke','all'],default='all');args=ap.parse_args();out=args.output.resolve()
    if args.stage=='check':qualified.check(out);return
    qualified.ResidentAttention=SoftmaxPipelinedAttention
    sys.argv=[str(Path(qualified.__file__)),'--output',str(out),'--stage','run','--scope',args.scope]
    qualified.main()
    report=json.loads((out/'verification.json').read_text());report['Softmax_two_row_pipeline']=True
    assert all(row[mode]['Softmax_pending_rows_max']==2 and row[mode]['extra_arithmetic_units']==0 for row in report['cases'] for mode in ['resident','materialized'])
    (out/'verification.json').write_text(json.dumps(report,indent=2));bindings=json.loads((out/'source_bindings.json').read_text())
    for p in [Path(__file__),ROOT/'integer_model/competitive_softmax_pipeline.py']:bindings[p.relative_to(ROOT).as_posix()]=sha(p)
    (out/'source_bindings.json').write_text(json.dumps(bindings,indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'},indent=2))


if __name__=='__main__':main()
