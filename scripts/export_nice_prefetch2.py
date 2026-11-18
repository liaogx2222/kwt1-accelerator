"""Deterministic RTL-only NICE/owner delta against the frozen LN8 SoC."""
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
REV='d6d6bd23efd047c4f89b73b4b78398026ab29fe5'
PARENT='97efbfc666a1ba7569ff999408b740a8e731a8d1'
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    files={};old={}
    for name,base in [('kwt_nice_block.sv','595724b88858b142a407f6a5c4761945252d523b:rtl/arch60_block/kwt_nice_block.sv'),('kwt_sysbus_arbiter3.sv',PARENT+':rtl/sysbus_v1/kwt_sysbus_arbiter3.sv')]:
        files['soc/'+name]=subprocess.check_output(['git','show',REV+':rtl/nice_prefetch2/'+name],cwd=ROOT)
        old['soc/'+name]=subprocess.check_output(['git','show',base],cwd=ROOT)
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w',format=tarfile.USTAR_FORMAT) as tf:
        for name,data in sorted(files.items()):
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.uid=info.gid=info.mtime=0;info.uname=info.gname='';tf.addfile(info,io.BytesIO(data))
    archive=out/'nice_prefetch2_rtl_only.tar.gz'
    with archive.open('wb') as f:
        with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as z:z.write(raw.getvalue())
    with tarfile.open(archive,'r:gz') as tf:
        assert sorted(tf.getnames())==sorted(files)
        for n,data in files.items():assert tf.extractfile(n).read()==data
    sha=lambda data:hashlib.sha256(data).hexdigest()
    m=dict(source_commit=REV,parent_commit=PARENT,archive=archive.name,archive_sha256=sha(archive.read_bytes()),
        files={n:sha(d) for n,d in files.items()},baseline_files={n:sha(d) for n,d in old.items()},
        required_accelerator_SHA256='a08f682fc4c06f69524ea9ba83f66d5a8e4328d47b92c5b28810ecfb3ff9f6ff',
        import_instruction='Review the two RTL files in the matching original-interface LN8 SoC; resynthesize CPU/NICE and relink. Never reuse a CPU DDC containing old NICE.',
        excludes='all flows, libraries, SDC, server scripts, firmware, parameters, testbenches and existing packages')
    (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');(out/'SHA256SUMS').write_text(m['archive_sha256']+'  '+archive.name+'\n')
    (out/'rtl.diff').write_text(''.join(''.join(difflib.unified_diff(old[n].decode().splitlines(True),files[n].decode().splitlines(True),fromfile='LN8/'+n,tofile=REV+'/'+n)) for n in sorted(files)))
    print('RTL ARCHIVE',m['archive_sha256'])
