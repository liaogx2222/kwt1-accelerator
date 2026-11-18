"""Independent scalar arithmetic/producer-readiness audit of R1 event traces."""
import gzip
import json
import math
from pathlib import Path
import numpy as np


def truth(op,a):
    def rne(n,d):
        q,r=divmod(abs(int(n)),int(d));q+=int(2*r>d or (2*r==d and q%2));return -q if n<0 else q
    if op=='mul':return a[0]*a[1]
    if op=='mac':
        x,y,z=a
        return [[int(z[i][j])+int(x[i])*int(y[j]) for j in range(len(y))] for i in range(len(x))]
    if op=='add':return a[0]+a[1]
    if op=='sub':return a[0]-a[1]
    if op=='max':return max(a)
    if op=='shl':return a[0]*(1<<a[1])
    if op=='shr':return a[0]//(1<<a[1])
    if op.startswith('rne'):
        x= rne(a[0],1<<a[1]) if a[1]>=0 else a[0]*(1<<-a[1])
        if op=='rne_sat8':x=max(-127,min(127,x))
        if op=='rne_sat16':x=max(-32767,min(32767,x))
        return x
    if op=='divmod':return list(divmod(a[0],a[1]))
    if op=='sqrt':return math.isqrt(a[0])
    if op=='round_qr':return a[0]+int(2*a[1]>a[2] or (2*a[1]==a[2] and a[0]%2))
    if op=='ceil_qr':return a[0]+int(a[1]>0)
    if op=='correct_qr':
        n,q,prod,d=a
        if prod>n:q-=1;prod-=d
        return [q,n-prod]
    raise ValueError(op)


def audit(path):
    issued={};values={};counts={};last_issue={};sources=consumers=complete=0
    for line in gzip.open(path,'rt',encoding='utf-8'):
        r=json.loads(line);kind=r['type']
        if kind=='source':values[r['id']]=(r['time'],r['value']);sources+=1
        elif kind=='issue':
            assert r['id'] not in issued
            ii={'mul':1,'mac':1,'div':64,'sqrt':32,'alu':1,'rne':1}[r['unit']]
            if r['unit'] in last_issue:assert r['at']>=last_issue[r['unit']]+ii,'unit initiation interval violation'
            assert r['ready']>r['at']
            last_issue[r['unit']]=r['at']
            for a in r['operands']:
                if a['id'] is not None:
                    ready,v=values[a['id']];assert r['at']>=ready,'EARLY_USE'
                    if a['index'] is not None and isinstance(v,list):
                        idx=a['index'];v=np.array(v)[tuple(idx) if isinstance(idx,list) else idx].tolist()
                    assert v==a['value'],'operand not driven by producer result'
            issued[r['id']]=r
        elif kind=='complete':
            issue=issued.pop(r['id']);assert r['ready']==issue['ready'] and r['observed_at']>=r['ready']
            expected=truth(r['op'],[a['value'] for a in r['operands']]);assert expected==r['result'],'WRONG_RESULT'
            values[r['id']]=(r['ready'],r['result']);complete+=1;counts[r['op']]=counts.get(r['op'],0)+1
        elif kind=='consume':
            ready,v=values[r['id']];assert r['at']>=ready,'EARLY_USE'
            if r['index'] is not None and isinstance(v,list):v=np.array(v)[tuple(r['index']) if isinstance(r['index'],list) else r['index']].tolist()
            assert v==r['value'],'consumer value mismatch';consumers+=1
    assert not issued
    return {'complete':complete,'sources':sources,'consumers':consumers,'operations':counts,'passed':True}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('trace',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args();r=audit(a.trace)
    if a.output:a.output.write_text(json.dumps(r,indent=2),encoding='utf-8')
    print(json.dumps(r,indent=2))
