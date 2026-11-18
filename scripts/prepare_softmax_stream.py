"""Parent score4 SoC plus one exact Softmax streaming compute overlay."""
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
    subprocess.run([sys.executable,str(ROOT/'scripts/prepare_score4.py'),'--output',str(out)],cwd=ROOT,check=True)
    if a.baseline:print('PREPARED exact score4 parent receipt');sys.exit(0)
    m=json.loads((out/'source_manifest.json').read_text());n='rtl/v2/kwt_layer_banked.sv';m['parent_score4_SHA256']=m['files'][n]
    b=(ROOT/'rtl/softmax_stream/kwt_layer_banked.sv').read_bytes();(out/n).write_bytes(b);m['files'][n]=hashlib.sha256(b).hexdigest()
    m.update(variant='softmax_stream',worktree_parent='5b3deec31c8e34d8e1484ae794fb1912ce4c8986',changed_production_files_relative_parent=[n])
    if a.targeted:
        from target_softmax_stream import instrument
        tb=out/'flow/tb_soc_metrics.sv';tb.write_text(instrument(tb.read_text()));m['files']['flow/tb_soc_metrics.sv']=hashlib.sha256(tb.read_bytes()).hexdigest()
        m['supported_reset_points'] += [18,19,20]
        m['verification_only_changes'].append('streaming-score and EXP pause/reset, final-row max/probability alias lifetime')
    (out/'source_manifest.json').write_text(json.dumps(m,indent=2)+'\n');print('PREPARED softmax stream')
