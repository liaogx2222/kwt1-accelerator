"""AC vs ABC selection, then 12 classes + same-object fault recoveries."""
import argparse,concurrent.futures,json,subprocess,sys
from pathlib import Path
from local_tools import ROOT
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['all','check'],default='all');a=ap.parse_args();out=a.output.resolve()
    def execute(kind,name,labels='0',model=None,faults=False):
        args=[sys.executable,ROOT/'scripts/run_e203_combinations.py','--kind',kind,'--output',out/name,'--labels',labels]
        if model:args+=['--model',model]
        if faults:args+=['--faults']
        subprocess.run([str(x) for x in args],cwd=ROOT,check=True)
    if a.stage=='all':
        assert not out.exists(),'Use fresh output';out.mkdir(parents=True)
        for kind in ['ac','abc']:execute(kind,'compare_'+kind)
        values={k:json.loads((out/('compare_'+k)/'summary.json').read_text())['jobs'][0]['main']['cycles'] for k in ['ac','abc']};selected=min(values,key=values.get)
        model=out/('compare_'+selected)/'combinations.exe'
        groups=[('classes_0_3','0,1,2,3',False),('classes_4_7','4,5,6,7',False),('classes_8_11','8,9,10,11',False),('faults','0',True)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(execute,selected,name,labels,model,faults) for name,labels,faults in groups]
            for f in futures:f.result()
    from check_e203_combinations import check
    print(json.dumps(check(out),indent=2))
if __name__=='__main__':main()
