"""Freeze accepted raw logs, source receipts, units and the rejected held-reset."""
import argparse
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();src=a.input.resolve();out=a.output.resolve();assert not out.exists()
    result=json.loads((src/'release_summary.json').read_text());assert result['passed'];selected={};models=set();projects=set()
    def add(p,name=None):
        assert p.is_file() and p.stat().st_size<2000000,str(p);selected[name or p.relative_to(src).as_posix()]=p
    add(src/'release_summary.json')
    for entry in result['evidence']:
        d=src/entry
        for n in ['result.json','command.json','run.log']:add(d/n)
        for p in d.glob('matrix_task_*.hex'):add(p)
        cmd=json.loads((d/'command.json').read_text());models.add(Path(cmd[0]).parent);projects.add(Path(next(x.split('=',1)[1] for x in cmd if x.startswith('+FIXTURES='))).parent)
        for n in ['summary.json','verilate.log','link.log']:
            if (d.parent/n).exists():add(d.parent/n)
    for p in models:
        add(p/'sources.json')
        if (p/'reuse_receipt.json').exists():add(p/'reuse_receipt.json')
    for p in projects:add(p/'source_manifest.json')
    for folder in ['inventory','analysis','unit','consumers']:
        for p in (src/folder).rglob('*'):
            # Large exhaustive unit vectors are recreated by fixed-seed script;
            # their hashes/counts are frozen in the unit summaries instead.
            if p.is_file() and p.name not in ['fast.txt','compat.txt'] and (p.suffix in ['.log','.sv','.txt'] or p.name in ['summary.json','command.json']):add(p)
    for n in ['case_00/run.log','case_00/command.json']:
        p=src/'held_reset'/n
        if p.exists():add(p,'earlier_failed_held_reset/'+n)
    for n in ['manifest.json','SHA256SUMS','rtl.diff']:add(ROOT/'deliverables/iter_fast_20261115'/n,'RTL_archive/'+n)
    out.mkdir(parents=True);(out/'.gitattributes').write_text('* -text\n');idx={}
    for name,p in sorted(selected.items()):
        data=p.read_bytes();q=out/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(data);idx[name]=dict(source=str(p),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    (out/'index.json').write_text(json.dumps(dict(passed=True,verbatim_raw_copies=True,large_unit_vectors_regenerated_from_fixed_seed=True,files=idx),indent=2)+'\n');print('FROZEN',len(idx),'files')
