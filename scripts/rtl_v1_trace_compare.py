"""Compare arithmetic operation streams independently of stall timing."""
import json,sys
from pathlib import Path
def compare(a,b):
    result={}
    for prefix in ['Q','R']:
        aa=[s for s in Path(a).read_text().splitlines() if s.startswith(prefix+' ')];bb=[s for s in Path(b).read_text().splitlines() if s.startswith(prefix+' ')]
        diff=next((i for i,(x,y) in enumerate(zip(aa,bb)) if x!=y),None)
        result[prefix]=dict(records=[len(aa),len(bb)],first_difference=diff)
        if diff is not None:result[prefix].update(left=aa[max(0,diff-2):diff+2],right=bb[max(0,diff-2):diff+2])
    print(json.dumps(result,indent=2));return result
if __name__=='__main__':compare(sys.argv[1],sys.argv[2])
