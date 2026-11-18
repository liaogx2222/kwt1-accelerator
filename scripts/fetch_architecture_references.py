"""Pin small primary-source implementation excerpts; do not install code."""
import concurrent.futures
import json
import sys
import urllib.request
from pathlib import Path
from local_tools import ROOT,sha


def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'KWT-architecture-research','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=60) as response:return response.read()


def main():
    out=Path(sys.argv[1]).resolve();assert not out.exists();out.mkdir(parents=True)
    specs=[('pulp-platform/ITA','main',['README.md','LICENSE.hw','LICENSE.sw','src/ita_softmax.sv','src/ita_requantizer.sv','src/ita_accumulator.sv']),
        ('ucb-bar/gemmini','master',['LICENSE','src/main/scala/gemmini/AccumulatorMem.scala','src/main/scala/gemmini/AccumulatorScale.scala']),
        ('Dao-AILab/flash-attention','main',['LICENSE','csrc/flash_attn/src/softmax.h'])]
    pins=[];jobs=[]
    for repo,branch,files in specs:
        data=json.loads(get(f'https://api.github.com/repos/{repo}/commits/{branch}'));commit=data['sha']
        pins.append(dict(repository=repo,branch=branch,commit=commit,commit_date=data['commit']['committer']['date']))
        folder=out/repo.split('/')[-1];folder.mkdir()
        for name in files:jobs.append((folder/name,f'https://raw.githubusercontent.com/{repo}/{commit}/{name}'))
    def download(job):
        path,url=job;data=get(url);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        return dict(path=path.relative_to(out).as_posix(),url=url,sha256=sha(path),bytes=len(data))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:files=list(pool.map(download,jobs))
    (out/'provenance.json').write_text(json.dumps(dict(pins=pins,files=files,scope='research-only copies, no third-party implementation linked into production'),indent=2))
    (out/'source_bindings.json').write_text(json.dumps({Path(__file__).relative_to(ROOT).as_posix():sha(Path(__file__))},indent=2))
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()},indent=2))
    print(json.dumps(dict(pins=pins,downloaded_files=len(files)),indent=2))


if __name__=='__main__':main()
