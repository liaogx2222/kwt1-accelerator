"""Prepare parent Dense SoC and replace only the score-bank compute overlay."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);ap.add_argument('--baseline',action='store_true');ap.add_argument('--targeted',action='store_true');a=ap.parse_args();out=a.output.resolve();assert not out.exists()
    assert not a.baseline or not a.targeted
    subprocess.run([sys.executable,str(ROOT/'scripts/prepare_dense_overlap.py'),'--output',str(out)],cwd=ROOT,check=True)
    if a.baseline:
        print('PREPARED exact Dense parent receipt');sys.exit(0)
    m=json.loads((out/'source_manifest.json').read_text());n='rtl/v2/kwt_layer_banked.sv';m['parent_dense_SHA256']=m['files'][n]
    if not a.baseline:
        b=(ROOT/'rtl/score4_opt/kwt_layer_banked.sv').read_bytes();(out/n).write_bytes(b);m['files'][n]=hashlib.sha256(b).hexdigest()
    m.update(variant='dense_parent' if a.baseline else 'score4',worktree_parent='9476619b7c85d8b5806744478a3419d8e5965015',
        changed_production_files_relative_parent=[] if a.baseline else [n])
    if a.targeted:
        from target_score4 import instrument
        tb=out/'flow/tb_soc_metrics.sv';tb.write_text(instrument(tb.read_text()));m['files']['flow/tb_soc_metrics.sv']=hashlib.sha256(tb.read_bytes()).hexdigest()
        m['supported_reset_points'] += [15,16,17]
        m['verification_only_changes'].append('score4 store/read/tail reset, stalls and reset quiescence')
    (out/'source_manifest.json').write_text(json.dumps(m,indent=2)+'\n');print('PREPARED',m['variant'])
