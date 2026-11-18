"""Standalone deterministic RTL-only delta; never touch an existing package."""
import argparse
import difflib
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REV = 'bc364d068c3f9d73b340a33136a998fd4ecdd05b'
BASE = '595724b88858b142a407f6a5c4761945252d523b'
TARGET = 'rtl/v2/kwt_layer_banked.sv'

if __name__ == '__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
    out=a.output.resolve();assert not out.exists(), 'preserve existing archive';out.mkdir(parents=True)
    def blob(rev, name):return subprocess.check_output(['git','show',rev+':'+name],cwd=ROOT)
    data=blob(REV,'rtl/pv16_opt/kwt_layer_banked.sv');old=blob(BASE,TARGET)
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w',format=tarfile.USTAR_FORMAT) as tf:
        item=tarfile.TarInfo(TARGET);item.size=len(data);item.mode=0o644;item.mtime=0
        item.uid=item.gid=0;item.uname=item.gname='';tf.addfile(item,io.BytesIO(data))
    archive=out/'pv16_rtl_only.tar.gz'
    with archive.open('wb') as f:
        with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as z:z.write(raw.getvalue())
    with tarfile.open(archive,'r:gz') as tf:
        assert tf.getnames()==[TARGET] and tf.extractfile(TARGET).read()==data
    sha=lambda b:hashlib.sha256(b).hexdigest()
    manifest=dict(source_commit=REV,worktree_parent='120316fe907a850c3f81939ed178fcb177af1449',
        integration_parent='2cf2dfa',baseline_arithmetic=BASE,archive=archive.name,archive_sha256=sha(archive.read_bytes()),
        files={TARGET:sha(data)},baseline_files={TARGET:sha(old)},
        excluded='all server flows, SDC, libraries, CPU/SoC interface sources, firmware, parameters and existing packages',
        import_instruction='Review and replace only this file in the matching S16 SYSBUS source project; resynthesize the changed accelerator, do not reuse the old accelerator DDC.')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (out/'SHA256SUMS').write_text(manifest['archive_sha256']+'  '+archive.name+'\n')
    diff=''.join(difflib.unified_diff(old.decode().splitlines(True),data.decode().splitlines(True),fromfile=BASE+'/'+TARGET,tofile=REV+'/'+TARGET))
    (out/'rtl.diff').write_text(diff)
    print(json.dumps(manifest,indent=2))
