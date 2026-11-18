"""Prepare the frozen NICE/LN8 system, replacing one compute core only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);ap.add_argument('--targeted',action='store_true');ap.add_argument('--error-checks',action='store_true');ap.add_argument('--baseline',action='store_true');a=ap.parse_args();out=a.output.resolve();assert not out.exists()
    assert not a.error_checks or a.targeted
    assert not a.baseline or not a.targeted
    subprocess.run([sys.executable,str(ROOT/'scripts/prepare_nice_prefetch2.py'),'--output',str(out)],cwd=ROOT,check=True)
    m=json.loads((out/'source_manifest.json').read_text());n='rtl/v2/kwt_layer_banked.sv';m['parent_core_SHA256']=m['files'][n]
    if not a.baseline:
        data=(ROOT/'rtl/dense_overlap/kwt_layer_banked.sv').read_bytes();(out/n).write_bytes(data);m['files'][n]=hashlib.sha256(data).hexdigest()
    m.update(variant='nice_parent' if a.baseline else 'dense_overlap',worktree_parent='8ef274d289e1d8ba094c8b5021b9db365b906072',changed_production_files_relative_parent=[] if a.baseline else [n])
    if a.targeted:
        from target_dense_overlap import instrument
        tb=out/'flow/tb_soc_metrics.sv';tb.write_text(instrument(tb.read_text(),a.error_checks));m['files']['flow/tb_soc_metrics.sv']=hashlib.sha256(tb.read_bytes()).hexdigest()
        m['supported_reset_points'] += [11,12,13]+([14] if a.error_checks else [])
        m['verification_only_changes'].append('Dense simultaneous MAC/RQ and S16/tail reset, stall and reset-quiescence checks')
    (out/'source_manifest.json').write_text(json.dumps(m,indent=2)+'\n');print('PREPARED DENSE OVERLAP')
