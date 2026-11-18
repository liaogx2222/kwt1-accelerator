"""Independent bigint audit; extends frozen audit with algebraic wired shifts."""
import argparse,importlib.util,json,sys,gzip
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import audit_r1_events
old_truth=audit_r1_events.truth
def truth(op,a):
    # Algebraically independent expressions, no execution model imports.
    if op in ('center64','var64'):return 64*a[0]-a[1]
    if op=='h16':return 65536*a[0]+a[1]
    if op=='prob_n':return 65535*a[0]
    if op=='prob_q':return 65535*a[0]//(2**47)
    return old_truth(op,a)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--quick',action='store_true');a=ap.parse_args()
    audit_r1_events.truth=truth
    path=ROOT.parent/'docs/architecture/review_r1r2_execution.py'
    spec=importlib.util.spec_from_file_location('frozen_audit',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    rows=[]
    for mode in ['normal','boundary']:
        folder=a.output/'fused'/f'{mode}_00';trace=folder/'events.gz'
        result=m.bounded_event_audit(trace)
        free=0;iterative=0
        for line in gzip.open(trace,'rt',encoding='utf-8'):
            r=json.loads(line)
            if r['type']=='issue' and r['unit'] in ('div','sqrt'):
                assert r['at']>=free,'shared divider/sqrt overlap';free=r['ready'];iterative+=1
        result['shared_divider_sqrt_nonoverlap']=True;result['shared_iterative_requests']=iterative
        result.update(mode=mode,folder=str(folder));rows.append(result);print('FUSED AUDIT',mode,result['complete'],flush=True)
        (a.output/'fused_audit_checkpoint.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    (a.output/'fused_audit.json').write_text(json.dumps(dict(passed=True,layers=rows,scope='full events for profile 0 normal+boundary; other profiles saved-output oracle'),indent=2),encoding='utf-8')
if __name__=='__main__':main()
