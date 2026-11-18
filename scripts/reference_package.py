"""Standalone source/fixture replay. Frozen golden comparison, no training data."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from local_tools import ROOT,sha

def read(p):return json.loads(p.read_text())
def verify():
    manifest=read(ROOT/'manifest.json')['sha256']
    for name,digest in manifest.items():assert sha(ROOT/name)==digest,('package drift',name)
    return manifest

def check(out):
    verify();codes=0;classes=[]
    for group in ['classes_0_3','classes_4_7','classes_8_11','faults']:
        base=out/group;r=read(base/'execution.json');assert r['passed'] and not r['quick']
        rows=[list(map(int,line.split())) for line in (base/'cpu_metrics.txt').read_text().splitlines()];assert len(rows)==4
        assert [(r[2],r[3]) for r in rows]==([(1,-3),(0,0),(2,-7),(0,0)] if group=='faults' else [(0,0)]*4)
        for row in rows:
            job,label,fault,rc=row[:4]
            if not rc:
                assert row[8:13]==[189328,13,13,0,61728] and row[15]==5058532 and 0<row[13]<=16384
                assert (base/f'cpu_observed_job_{job:02d}.hex').read_text().split()==(ROOT/'fixtures'/f'expected_{label:03d}.hex').read_text().split();codes+=6336
                if group!='faults':classes.append(label)
        assert 'PASS E203 jobs=4' in (base/'live.log').read_text()
    assert codes==88704 and sorted(classes)==list(range(12))
    report=dict(passed=True,output_codes_compared=codes,mismatches=0,scope='standalone replay against manifest-bound, independently derived frozen host golden; original independent integer recomputation in evidence/verification.json',physical_signoff=False,linux_execution='pending' if os.name=='nt' else 'this host')
    (out/'package_verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['all','verify','build','run','check'],default='verify');ap.add_argument('--output',type=Path,default=ROOT/'runs/replay');ap.add_argument('--tools',type=Path);a=ap.parse_args()
    verify()
    if a.stage=='verify':print('PASS package SHA256 bindings');return
    os.environ['KWT_E203_REPO']=str(ROOT/'cpu/e203_hbirdv2')
    for stage in (['build','run'] if a.stage=='all' else [a.stage] if a.stage in ['build','run'] else []):
        args=[sys.executable,ROOT/'scripts/validate_reference_system.py','--stage',stage,'--output',a.output]
        if a.tools:args+=['--tools',a.tools]
        subprocess.run([str(x) for x in args],cwd=ROOT,check=True)
    if a.stage in ['all','check']:check(a.output.resolve())

if __name__=='__main__':main()
