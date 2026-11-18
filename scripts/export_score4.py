"""Deterministic single-file RTL archive against the formal Dense parent."""
import argparse
import difflib
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
PARENT='9476619b7c85d8b5806744478a3419d8e5965015';REV='4a163f7abe5043e4cfb269f7a8d71d12291e7535'
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    data=subprocess.check_output(['git','show',REV+':rtl/score4_opt/kwt_layer_banked.sv'],cwd=ROOT)
    old=subprocess.check_output(['git','show',PARENT+':rtl/dense_overlap/kwt_layer_banked.sv'],cwd=ROOT)
    assert data==(ROOT/'rtl/score4_opt/kwt_layer_banked.sv').read_bytes();name='rtl/v2/kwt_layer_banked.sv';raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w',format=tarfile.USTAR_FORMAT) as tf:
        info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.uid=info.gid=info.mtime=0;info.uname=info.gname='';tf.addfile(info,io.BytesIO(data))
    archive=out/'score4_rtl_only.tar.gz'
    with archive.open('wb') as f:
        with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as z:z.write(raw.getvalue())
    with tarfile.open(archive,'r:gz') as tf:assert tf.getnames()==[name] and tf.extractfile(name).read()==data
    sha=lambda b:hashlib.sha256(b).hexdigest()
    m=dict(parent_commit=PARENT,source_commit=REV,archive=archive.name,archive_sha256=sha(archive.read_bytes()),files={name:sha(data)},baseline_files={name:sha(old)},
        requires='matching Dense/NICE-prefetch2 parent; resynthesize accelerator; identical20privateSRAM/ports',
        excludes='flow/SDC/vendor libraries/server scripts/firmware/parameters/testbenches/previous immutable packages')
    (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');(out/'SHA256SUMS').write_text(m['archive_sha256']+'  '+archive.name+'\n')
    (out/'rtl.diff').write_text(''.join(difflib.unified_diff(old.decode().splitlines(True),data.decode().splitlines(True),fromfile=PARENT+'/'+name,tofile=REV+'/'+name)))
    print('SCORE4 RTL ARCHIVE',m['archive_sha256'])
