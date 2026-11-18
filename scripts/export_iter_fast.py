"""Deterministic two-file RTL-only iterative candidate, no server flow content."""
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
REV='c90b1e2a8be95ec1df2e2d73cf832239b684cde1';PARENT='8901e14ba4028d0711f25e0cfa598c6abe13835b'
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    files={};old={}
    for n,base in [('kwt_iterative.sv','595724b88858b142a407f6a5c4761945252d523b:rtl/v2/kwt_iterative.sv'),('kwt_layer_banked.sv',PARENT+':rtl/softmax_stream/kwt_layer_banked.sv')]:
        key='rtl/v2/'+n;files[key]=subprocess.check_output(['git','show',REV+':rtl/iter_fast/'+n],cwd=ROOT)
        assert files[key]==(ROOT/'rtl/iter_fast'/n).read_bytes();old[key]=subprocess.check_output(['git','show',base],cwd=ROOT)
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w',format=tarfile.USTAR_FORMAT) as tf:
        for n,data in sorted(files.items()):
            i=tarfile.TarInfo(n);i.size=len(data);i.mode=0o644;i.uid=i.gid=i.mtime=0;i.uname=i.gname='';tf.addfile(i,io.BytesIO(data))
    archive=out/'iter_fast_rtl_only.tar.gz'
    with archive.open('wb') as f:
        with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as z:z.write(raw.getvalue())
    with tarfile.open(archive,'r:gz') as tf:
        assert tf.getnames()==sorted(files)
        for n,data in files.items():assert tf.extractfile(n).read()==data
    sha=lambda b:hashlib.sha256(b).hexdigest()
    m=dict(parent_commit=PARENT,source_commit=REV,archive=archive.name,archive_sha256=sha(archive.read_bytes()),files={n:sha(d) for n,d in files.items()},baseline_files={n:sha(d) for n,d in old.items()},
        requires='matching original-interface Softmax-stream/NICE-prefetch2 parent; resynthesize accelerator; timing of deeper divider must be measured',
        excludes='all flows/SDC/libraries/server scripts/firmware/parameters/testbenches/old immutable packages')
    (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');(out/'SHA256SUMS').write_text(m['archive_sha256']+'  '+archive.name+'\n')
    (out/'rtl.diff').write_text(''.join(''.join(difflib.unified_diff(old[n].decode().splitlines(True),files[n].decode().splitlines(True),fromfile=PARENT+'/'+n,tofile=REV+'/'+n)) for n in sorted(files)))
    print('ITER RTL ARCHIVE',m['archive_sha256'])
