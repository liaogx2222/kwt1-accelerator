"""Deterministic standalone LN8 RTL delta relative to frozen PV16."""
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
REV='ccd3f9e3c534938bbd191e3b3e7de90fac4cfdd8'
PARENT='d011cbafdb38f15aa3395fbb2276e09692546356'
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    def blob(rev,n):return subprocess.check_output(['git','show',rev+':'+n],cwd=ROOT)
    data=blob(REV,'rtl/ln8_opt/kwt_layer_banked.sv');old=blob(PARENT,'rtl/pv16_opt/kwt_layer_banked.sv');name='rtl/v2/kwt_layer_banked.sv'
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w',format=tarfile.USTAR_FORMAT) as tf:
        info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.mtime=info.uid=info.gid=0;info.uname=info.gname='';tf.addfile(info,io.BytesIO(data))
    archive=out/'ln8_rtl_only.tar.gz'
    with archive.open('wb') as f:
        with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as z:z.write(raw.getvalue())
    with tarfile.open(archive,'r:gz') as tf:assert tf.getnames()==[name] and tf.extractfile(name).read()==data
    sha=lambda b:hashlib.sha256(b).hexdigest()
    m=dict(source_commit=REV,parent_commit=PARENT,archive=archive.name,archive_SHA256=sha(archive.read_bytes()),
        files={name:sha(data)},baseline_files={name:sha(old)},owner_queue_candidate_included=False,
        excludes='all flow/SDC/library/server/CPU/interface/firmware/parameter files',
        import_instruction='Review only this LN8 core overlay relative to PV16; resynthesize changed accelerator and relink complete original-interface SoC.')
    (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');(out/'SHA256SUMS').write_text(m['archive_SHA256']+'  '+archive.name+'\n')
    (out/'rtl.diff').write_text(''.join(difflib.unified_diff(old.decode().splitlines(True),data.decode().splitlines(True),fromfile=PARENT+'/'+name,tofile=REV+'/'+name)))
    print(json.dumps(m,indent=2))
