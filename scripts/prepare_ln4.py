"""Preserve exact iter-fast SoC and replace only normalization scheduling RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--baseline',action='store_true');ap.add_argument('--targeted',action='store_true');a=ap.parse_args();out=a.output.resolve();assert not out.exists()
    assert not a.baseline or not a.targeted
    subprocess.run([sys.executable,str(ROOT/'scripts/prepare_iter_fast.py'),'--output',str(out)],cwd=ROOT,check=True)
    if a.baseline:print('PREPARED exact iter parent');sys.exit(0)
    m=json.loads((out/'source_manifest.json').read_text());n='rtl/v2/kwt_layer_banked.sv';m['parent_iter_core_SHA256']=m['files'][n]
    data=(ROOT/'rtl/ln4_opt/kwt_layer_banked.sv').read_bytes();(out/n).write_bytes(data);m['files'][n]=hashlib.sha256(data).hexdigest()
    m.update(variant='ln4',worktree_parent='eb7277e3774b147c2c69ecfbbdaaeeb148363c3d',changed_production_files_relative_parent=[n])
    if a.targeted:
        from target_ln4 import instrument
        tb=out/'flow/tb_soc_metrics.sv';tb.write_text(instrument(tb.read_text()));m['files']['flow/tb_soc_metrics.sv']=hashlib.sha256(tb.read_bytes()).hexdigest()
        m['supported_reset_points'] += [25,26,27,28,30]
        m['verification_only_changes'].append('LN4 statistics/even/odd/tail/error reset, independent-lane fork stall and packed-output hold')
    (out/'source_manifest.json').write_text(json.dumps(m,indent=2)+'\n');print('PREPARED LN4')
