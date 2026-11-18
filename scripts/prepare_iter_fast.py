"""Parent streaming SoC plus one iterative unit and two parameter enables."""
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
    subprocess.run([sys.executable,str(ROOT/'scripts/prepare_softmax_stream.py'),'--output',str(out)],cwd=ROOT,check=True)
    if a.baseline:print('PREPARED exact streaming parent');sys.exit(0)
    m=json.loads((out/'source_manifest.json').read_text());parents={}
    for n in ['kwt_iterative.sv','kwt_layer_banked.sv']:
        target='rtl/v2/'+n;parents[target]=m['files'][target];data=(ROOT/'rtl/iter_fast'/n).read_bytes();(out/target).write_bytes(data);m['files'][target]=hashlib.sha256(data).hexdigest()
    m.update(variant='iter_fast',worktree_parent='8901e14ba4028d0711f25e0cfa598c6abe13835b',changed_production_files_relative_parent=list(parents),parent_sources=parents)
    if a.targeted:
        from target_iter_fast import instrument
        tb=out/'flow/tb_soc_metrics.sv';tb.write_text(instrument(tb.read_text()));m['files']['flow/tb_soc_metrics.sv']=hashlib.sha256(tb.read_bytes()).hexdigest()
        m['supported_reset_points'] += [21,22,23,24]
        m['verification_only_changes'].append('actual iterative sqrt/div response holds and in-flight/held reset recovery')
    (out/'source_manifest.json').write_text(json.dumps(m,indent=2)+'\n');print('PREPARED iter_fast')
