"""One reproducible entry for actual E203 builds, grouped runs and independent gate."""
import argparse
import concurrent.futures
import subprocess
import sys
from pathlib import Path
from local_tools import ROOT,SUFFIX

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['all','build','run','check'],default='all');ap.add_argument('--output',type=Path,required=True);ap.add_argument('--tools',type=Path);a=ap.parse_args();out=a.output.resolve()
    if a.stage!='check' and (out/'verification.json').exists():raise ValueError('Published evidence exists; choose a fresh output')
    def run(args):
        p=subprocess.run([str(v) for v in [sys.executable,ROOT/'scripts/run_reference_e203.py',*args,*(['--tools',a.tools] if a.tools else [])]],cwd=ROOT)
        if p.returncode:raise RuntimeError('Reference subprocess failed: '+str(args))
    if a.stage in ['all','build']:run(['--stage','build','--output',out/'build'])
    if a.stage in ['all','run']:
        model=out/'build/model'/('sim'+SUFFIX)
        groups=[('classes_0_3',['--labels','0,1,2,3']),('classes_4_7',['--labels','4,5,6,7']),('classes_8_11',['--labels','8,9,10,11']),('faults',['--faults-only'])]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(run,[*args,'--model',model,'--output',out/name]) for name,args in groups]
            for f in futures:f.result()
    if a.stage in ['all','check']:
        from check_reference_e203 import check
        import os
        check(out,Path(os.environ.get('KWT_E203_REPO',ROOT.parent/'e203_hbirdv2')).resolve())

if __name__=='__main__':main()
