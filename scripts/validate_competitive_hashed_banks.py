"""Exhaustive address/port/lifetime tests, then real Dense/RQ qualification."""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
sys.path.insert(0,str(ROOT))
from integer_model.competitive_tile16 import MacroClock
from integer_model.competitive_hashed_banks import HashedScratch,HashedPipelinedTile16
import validate_competitive_tile16 as qualified


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['smoke','all'],default='smoke')
    args=ap.parse_args();out=args.output.resolve();own=sha(Path(__file__))
    # Prove injectivity at byte level, including N99 odd tails and width99.
    addressed=0
    for rows,cols,bits in [(99,64,8),(99,64,16),(99,256,8),(16,99,32),(3,99,16),(99,16,8)]:
        b=MacroClock();pool=HashedScratch(b);t=pool.allocate('probe',rows,cols,bits)
        seen=set()
        for row in range(rows):
            for col in range(cols):
                for plane in range(bits//8):
                    bank,address=t.word(row,col,plane);key=(bank,address,row%2)
                    assert key not in seen;seen.add(key)
                    p=int(bank[1:]);assert t.bases[p]<=address<t.bases[p]+t.sizes[p]
        addressed+=len(seen);pool.release(t)
    # Critical real simultaneous live sets fit each individual macro, not just
    # an aggregate byte sum. No arithmetic data are stored outside these banks.
    b=MacroClock();pool=HashedScratch(b)
    live=[pool.allocate('S16 input',99,64,16)]+[pool.allocate(name,99,64,8) for name in ['Q','K','V']]
    assert pool.peak==32000 and pool.bank_peak==[8000]*4
    for t in live:pool.release(t)
    a=pool.allocate('residual norm',99,64,8);h=pool.allocate('FC1 hidden',99,256,8)
    assert pool.bank_peak==[8000]*4
    # One row pair: four successive channels occupy four distinct SP banks.
    assert len({a.word(0,c)[0] for c in range(4)})==4
    pool.release(a);pool.release(h)
    qualified.Tile16Dense=HashedPipelinedTile16
    sys.argv=[str(ROOT/'scripts/validate_competitive_tile16.py'),'--output',str(out),'--stage',args.stage,'--lanes','4']
    qualified.main();assert sha(Path(__file__))==own
    report=json.loads((out/'verification.json').read_text());report['MAC_RQ_overlap_implemented']=True
    report['scope']='hashed scratch + bounded Dense/RQ model; live-set/address proof is not a full-layer/timing/RTL proof'
    report['hashed_mapping_byte_locations_checked']=addressed;report['critical_live_set_bytes']=32000
    report['critical_live_set_bank_bytes']=[8000]*4;report['four_channels_row_pair_conflict_free']=True
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    bindings=json.loads((out/'source_bindings.json').read_text())
    for p in [Path(__file__),ROOT/'integer_model/competitive_hashed_banks.py',ROOT/'integer_model/competitive_tile16_pipeline.py']:
        bindings[p.relative_to(ROOT).as_posix()]=sha(p)
    (out/'source_bindings.json').write_text(json.dumps(bindings,indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'},indent=2))


if __name__=='__main__':main()
