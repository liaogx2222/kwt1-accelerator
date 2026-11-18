"""Freeze complete passing campaign and retain the rejected first stall run."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();src=a.input.resolve();out=a.output.resolve();assert not out.exists()
    r=json.loads((src/'release_summary.json').read_text());assert r['passed'];selected={};models=set();projects=set()
    def add(p,name=None):
        assert p.is_file() and p.stat().st_size<2000000,str(p);selected[name or p.relative_to(src).as_posix()]=p
    add(src/'release_summary.json')
    for entry in r['evidence']:
        d=src/entry
        for name in ['result.json','command.json','run.log']:add(d/name)
        for p in d.glob('matrix_task_*.hex'):add(p)
        cmd=json.loads((d/'command.json').read_text());models.add(Path(cmd[0]).parent)
        projects.add(Path(next(x.split('=',1)[1] for x in cmd if x.startswith('+FIXTURES='))).parent)
        for name in ['summary.json','verilate.log','link.log']:
            if (d.parent/name).exists():add(d.parent/name)
    for p in models:
        add(p/'sources.json')
        if (p/'reuse_receipt.json').exists():add(p/'reuse_receipt.json')
    for p in projects:add(p/'source_manifest.json')
    for folder in ['inventory','ceiling_v2']:
        for p in (src/folder).rglob('*'):
            if p.is_file() and (p.suffix=='.log' or p.name in ['summary.json','command.json','ceiling.json']):add(p)
    for n in ['case_00/run.log','case_00/command.json','verilate.log','link.log','model/sources.json']:
        p=src/'targeted/stall'/n
        if p.exists():add(p,'earlier_failed_stall/'+n)
    for n in ['manifest.json','SHA256SUMS','rtl.diff']:add(ROOT/'deliverables/score4_20261115'/n,'RTL_archive/'+n)
    out.mkdir(parents=True);(out/'.gitattributes').write_text('* -text\n');idx={}
    for name,p in sorted(selected.items()):
        data=p.read_bytes();q=out/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(data);idx[name]=dict(source=str(p),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    (out/'index.json').write_text(json.dumps(dict(passed=True,verbatim_raw_copies=True,files=idx),indent=2)+'\n');print('FROZEN',len(idx),'files')
