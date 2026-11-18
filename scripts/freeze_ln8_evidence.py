"""Freeze compact LN8 raw evidence verbatim; exclude executables and ASTs."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True,type=Path);ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
    src=a.input.resolve();out=a.output.resolve();assert not out.exists();r=json.loads((src/'release_summary.json').read_text());assert r['passed']
    selected={};projects=set()
    def add(p,name=None):
        assert p.is_file() and p.stat().st_size<2000000,str(p);selected[name or p.relative_to(src).as_posix()]=p
    add(src/'release_summary.json')
    for name in r['evidence']:
        folder=src/name;add(folder/'summary.json')
        for d in folder.glob('case_*'):
            for file in ['command.json','result.json','run.log']:add(d/file)
            for p in d.glob('matrix_task_*.hex'):add(p)
            cmd=json.loads((d/'command.json').read_text());model=Path(cmd[0]).parent
            add(model/'sources.json','model_receipts/'+model.relative_to(src).as_posix()+'/sources.json')
            projects.add(Path(next(x.split('=',1)[1] for x in cmd if x.startswith('+FIXTURES='))).parent)
        for file in ['verilate.log','link.log']:
            if (folder/file).exists():add(folder/file)
    for p in projects:add(p/'source_manifest.json')
    for file in ['summary.json','command.json','tool.log']:add(src/'inventory'/file)
    for file in ['manifest.json','SHA256SUMS','rtl.diff']:add(ROOT/'deliverables/ln8_opt_20261114'/file,'RTL_archive/'+file)
    out.mkdir(parents=True);(out/'.gitattributes').write_text('* -text\n');index={}
    for name,p in sorted(selected.items()):
        data=p.read_bytes();q=out/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(data)
        index[name]=dict(source=str(p),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    (out/'index.json').write_text(json.dumps(dict(passed=True,verbatim_raw_copies=True,files=index),indent=2)+'\n')
    print('FROZEN',len(index),'files',sum(v['bytes'] for v in index.values()),'bytes')
