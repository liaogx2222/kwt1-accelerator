"""Reuse identical kernel fixtures/negative tests for bounded MAC/RQ overlap."""
import argparse
import json
import sys
from pathlib import Path
from local_tools import ROOT,sha
sys.path.insert(0,str(ROOT))
from integer_model.competitive_tile16_pipeline import PipelinedTile16
import validate_competitive_tile16 as qualified


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--stage',choices=['smoke','all'],default='smoke');ap.add_argument('--lanes',type=int,default=4)
    args=ap.parse_args();out=args.output.resolve();own=sha(Path(__file__))
    qualified.Tile16Dense=PipelinedTile16
    sys.argv=[str(ROOT/'scripts/validate_competitive_tile16.py'),'--output',str(out),'--stage',args.stage,'--lanes',str(args.lanes)]
    qualified.main()
    assert sha(Path(__file__))==own
    report=json.loads((out/'verification.json').read_text());report['MAC_RQ_overlap_implemented']=True
    report['scope']='bounded two-accumulator Dense/RQ overlap qualification; no complete encoder/IO/PPA result'
    report['MAC_RQ_overlap_cycles']=sum(row['MAC_RQ_overlap_cycles'] for row in report['cases'])
    assert all(row['max_queued_jobs']<=2 and row['max_product_queue']<=3 and row['max_output_queue']<=2 for row in report['cases'])
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    bindings=json.loads((out/'source_bindings.json').read_text())
    for p in [Path(__file__),ROOT/'integer_model/competitive_tile16_pipeline.py']:bindings[p.relative_to(ROOT).as_posix()]=sha(p)
    (out/'source_bindings.json').write_text(json.dumps(bindings,indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'},indent=2))


if __name__=='__main__':main()
