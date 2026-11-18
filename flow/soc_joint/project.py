"""Python 3.6 compatible standalone SoC source importer/checker."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]

def sha(data):return hashlib.sha256(data).hexdigest()

def check():
    m=json.loads((ROOT/'manifest.json').read_text())
    bad=[name for name,row in m['files'].items() if not (ROOT/name).is_file() or sha((ROOT/name).read_bytes())!=row['sha256']]
    if bad:raise SystemExit('SOC_SOURCE_MISMATCH '+', '.join(bad[:8]))
    print('SOC_PROJECT_VERIFIED files=%d revision=%s'%(len(m['files']),m['revision']))

def import_files(kind, source):
    m=json.loads((ROOT/'manifest.json').read_text())
    prefix='cpu/e203/' if kind=='cpu' else 'rtl/' if kind=='accelerator' else 'fixtures/'
    planned={}
    for name,row in m['files'].items():
        if name.startswith(prefix):
            p=source/name if kind=='accelerator' else source/name[len(prefix):]
            if not p.is_file():raise SystemExit('SOC_IMPORT_MISSING '+str(p))
            data=p.read_bytes().replace(b'\r\n',b'\n')
            if sha(data)!=row['sha256']:raise SystemExit('SOC_IMPORT_HASH_MISMATCH '+str(p))
            target=ROOT/name
            if target.exists() and target.read_bytes()!=data:raise SystemExit('SOC_REFUSE_OVERWRITE '+name)
            planned[name]=data
    for name,data in planned.items():
        p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
        if not p.exists():p.write_bytes(data)
    print('SOC_IMPORTED %s files=%d'%(kind,len(planned)))

def filelist(destination):
    check()
    lines=[]
    for line in (ROOT/'flow/files.f').read_text().splitlines():
        prefix='+incdir+' if line.startswith('+incdir+') else ''
        path=(ROOT/line[len(prefix):]).resolve()
        if not path.exists():raise SystemExit('SOC_FILELIST_MISSING '+str(path))
        lines.append(prefix+str(path))
    destination.write_text('\n'.join(lines)+'\n')

if __name__=='__main__':
    if sys.argv[1:]==['check']:check()
    elif len(sys.argv)==3 and sys.argv[1]=='filelist':filelist(Path(sys.argv[2]))
    elif len(sys.argv)==3 and sys.argv[1] in ['import-cpu','import-fixtures','import-accelerator']:
        import_files(sys.argv[1][7:],Path(sys.argv[2]))
    else:raise SystemExit('usage: project.py check | filelist <output> | import-cpu <e203 dir> | import-fixtures <fixtures dir> | import-accelerator <accelerator project>')
