"""Execute the sealed trim variant; preserve the exact executed source."""
import argparse
import runpy
import sys
from local_tools import ROOT


def main():
    ap=argparse.ArgumentParser(add_help=False);ap.add_argument('--trim-stage',choices=['native','e203'],required=True);a,rest=ap.parse_known_args();base=ROOT/'testdata/input16_rtl_20261105/trim_derivation'
    source=base/('validate_input16_rtl_executed.py' if a.trim_stage=='native' else 'run_input16_e203_executed.py')
    t=source.read_text().replace('rtl/input16_trim','rtl/input16_trim2');actual=base.parent/f'trim2_{a.trim_stage}_actual_runner.py'
    if a.trim_stage=='e203':
        assert t.count('private_SRAM_bytes=163840')==1;t=t.replace('private_SRAM_bytes=163840','private_SRAM_bytes=147456')
    if actual.exists():assert actual.read_text()==t
    else:actual.write_text(t)
    sys.argv=[str(actual),*rest];runpy.run_path(str(actual),run_name='__main__')


if __name__=='__main__':main()
