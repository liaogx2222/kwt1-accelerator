"""Reuse the checked full SoC executable for independent cold class tasks."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import subprocess


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True)
    p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cases',default=','.join(map(str,range(1,12))));p.add_argument('--jobs',type=int,default=6)
    a=p.parse_args();root=a.project.resolve();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    m=json.loads((root/'manifest.json').read_text())
    for n,h in m['files'].items():assert sha(root/n)==h,n
    proof=dict(manifest_sha256=sha(root/'manifest.json'),model_sha256=sha(a.model),
        scope='actual RTL on full SV SoC bench; not mapped netlist or PPA')
    (out/'inputs.json').write_text(json.dumps(proof,indent=2)+'\n')
    def task(case):
        folder=out/('case_%02d'%case);folder.mkdir()
        with (folder/'run.log').open('x') as f:
            code=subprocess.run([str(a.model.resolve()),'+CASE='+str(case),'+RECOVERY=0',
                '+FIXTURES='+str(root/'fixtures'),'+OUT='+str(folder)],cwd=str(root),
                stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT).returncode
        text=(folder/'run.log').read_text();assert code==0,'PROCESS_FAILED '+str(case)
        assert 'PASS SOC_INPUT16_GATE recovery=0 case='+str(case)+' ' in text,'NO_PASS '+str(case)
        assert 'mismatches=0' in text
        cycles=int(re.search(r'SOC_GATE_METRICS cycles=(\d+)',text).group(1))
        result=dict(case=case,passed=True,cycles=cycles,codes=6336,log_sha256=sha(folder/'run.log'))
        (folder/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:rows=list(pool.map(task,map(int,a.cases.split(','))))
    (out/'summary.json').write_text(json.dumps(dict(passed=True,cases=rows,codes=6336*len(rows),
        actual_RTL=True,actual_mapped=False,cold_per_case=True,source=proof),indent=2)+'\n')


if __name__=='__main__':main()
