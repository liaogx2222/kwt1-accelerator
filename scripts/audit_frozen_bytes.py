"""Verify frozen raw bytes on disk and in the Git index or a revision."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--directory',required=True,type=Path);ap.add_argument('--git-index',action='store_true');ap.add_argument('--revision',default='HEAD');a=ap.parse_args()
    folder=a.directory.resolve();records=json.loads((folder/'index.json').read_text())['files'];names=list(records)
    for n in names:assert hashlib.sha256((folder/n).read_bytes()).hexdigest()==records[n]['sha256'],'disk '+n
    prefix=':' if a.git_index else a.revision+':'
    specs=[prefix+(folder/n).relative_to(ROOT).as_posix() for n in names]
    p=subprocess.run(['git','cat-file','--batch'],input=('\n'.join(specs)+'\n').encode(),cwd=ROOT,capture_output=True);assert p.returncode==0
    stream=io.BytesIO(p.stdout)
    for n in names:
        header=stream.readline().split();assert len(header)==3 and header[1]==b'blob',(n,header)
        data=stream.read(int(header[2]));assert stream.read(1)==b'\n'
        assert hashlib.sha256(data).hexdigest()==records[n]['sha256'],'Git '+n
    assert not stream.read();print('PASS raw disk and Git bytes',len(names),'files',sum(v['bytes'] for v in records.values()),'bytes')
