"""Adapt the independent existing consumer test to the explicit fast latencies."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    out=ROOT/'scripts/check_iter_consumers.py';assert not out.exists();s=(ROOT/'scripts/check_pv16_consumers.py').read_text()
    old="    (out/'iter.txt').write_text(it+''.join(rows))";assert s.count(old)==1
    s=s.replace(old,"""    final_rows=[]
    for line in (it+''.join(rows)).splitlines():
        c=line.split();sm,aa,bb=int(c[0]),int(c[1],16),int(c[2],16)
        c[-1]=str(16 if sm else 1 if bb==0 else 11 if aa==1<<40 else 12 if aa==1<<47 else 64)
        final_rows.append(' '.join(c)+'\\n')
    (out/'iter.txt').write_text(''.join(final_rows))""")
    s=s.replace('#(.SHORT_CONST_DIV(1),.RADIX4_CONST(1))','#(.SHORT_CONST_DIV(1),.RADIX4_CONST(1),.RADIX16_CONST(1),.DOUBLE_SQRT(1))')
    s=s.replace('actual_RADIX4_CONST=1,reset_groups=5','actual_RADIX4_CONST=1,actual_RADIX16_CONST=1,actual_DOUBLE_SQRT=1,reset_groups=5')
    s=s.replace("scope='actual unchanged math/iterative consumers; not whole SoC/gate'","scope='actual unchanged RNE and fast exact iterative consumer dependencies; not whole SoC/gate'")
    out.write_text(s)
