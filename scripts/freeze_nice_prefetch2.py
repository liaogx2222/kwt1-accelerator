"""Freeze complete accepted raw campaign; preserve interrupted attempts too."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True,type=Path);ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();src=a.input.resolve();out=a.output.resolve();assert not out.exists()
    r=json.loads((src/'release_summary.json').read_text());assert r['passed'];selected={};projects=set();models=set()
    def add(p,name=None):
        assert p.is_file() and p.stat().st_size<2000000,str(p);selected[name or p.relative_to(src).as_posix()]=p
    add(src/'release_summary.json')
    for entry in r['evidence']:
        d=src/entry
        for name in ['result.json','command.json','run.log']:add(d/name)
        for p in d.glob('matrix_task_*.hex'):add(p)
        command=json.loads((d/'command.json').read_text());models.add(Path(command[0]).parent)
        projects.add(Path(next(x.split('=',1)[1] for x in command if x.startswith('+FIXTURES='))).parent)
        for name in ['summary.json','verilate.log','link.log']:
            if (d.parent/name).exists():add(d.parent/name)
    for p in models:add(p/'sources.json')
    for p in projects:add(p/'source_manifest.json')
    for folder in ['contract_v5','inventory']:
        for p in (src/folder).rglob('*'):
            if p.is_file() and (p.name=='summary.json' or p.suffix=='.log'):add(p)
    for folder in ['contract','contract_v2','consecutive_gap4','targeted/inflight_reads']:
        for p in (src/folder).rglob('*.log'):add(p,'earlier_attempts/'+p.relative_to(src).as_posix())
    for name in ['manifest.json','SHA256SUMS','rtl.diff']:add(ROOT/'deliverables/nice_prefetch2_20261115'/name,'RTL_archive/'+name)
    out.mkdir(parents=True);(out/'.gitattributes').write_text('* -text\n');idx={}
    for name,p in sorted(selected.items()):
        data=p.read_bytes();q=out/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(data);idx[name]=dict(source=str(p),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    (out/'index.json').write_text(json.dumps(dict(passed=True,verbatim_raw_copies=True,files=idx),indent=2)+'\n');print('FROZEN',len(idx),'files')
