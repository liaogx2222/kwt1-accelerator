"""Count all declared sequential state from the elaborated production AST.

This is an RTL bit count, NOT mapped cell area. Only 20 explicit SRAM arrays
are excluded; PE accumulators, arithmetic pipelines, controller, bus and SRAM
output registers are conservatively included in the 4 KiB bound.
"""
import json,re
from collections import Counter
from pathlib import Path
def walk(x):
    if isinstance(x,dict):
        yield x
        for v in x.values():yield from walk(v)
    elif isinstance(x,list):
        for v in x:yield from walk(v)
def inventory(path,out):
    tree=json.loads(Path(path).read_text());nodes={n['addr']:n for n in walk(tree) if 'addr' in n};mods={n['addr']:n for n in tree['modulesp']}
    def width(ref):
        n=nodes[ref]
        if n['type']=='BASICDTYPE':
            if 'range' not in n:return 1
            hi,lo=map(int,n['range'].split(':'));return abs(hi-lo)+1
        if n['type']=='UNPACKARRAYDTYPE':
            hi,lo=map(int,re.findall(r'-?\d+',n['declRange']));return (abs(hi-lo)+1)*width(n['refDTypep'])
        raise AssertionError(n)
    counts=Counter()
    def visit(ref):
        counts[ref]+=1
        for n in walk(mods[ref]):
            if n['type']=='CELL':visit(n['modp'])
    visit(next(k for k,v in mods.items() if v['name']=='kwt1_mmio'))
    rows=[];sram_bits=0;register_bits=0;mult=[]
    for ref,count in counts.items():
        mod=mods[ref];assigned=set()
        for n in walk(mod):
            if n['type']=='ASSIGNDLY':
                assigned.update(v['varp'] for v in walk(n['lhsp']) if v['type']=='VARREF' and v.get('access') in ['WR','RW'])
            if n['type'] in ['MUL','MULS']:
                args=[v for key in ['lhsp','rhsp'] for v in n.get(key,[])]
                if len(args)==2 and all(v['type']!='CONST' for v in args):mult.append(dict(module=mod['name'],location=n['loc'],instances=count))
        for varref in sorted(assigned):
            var=nodes[varref];bits=width(var['dtypep'])*count;is_sram=mod.get('origName')=='kwt_sram_sp' and var['name']=='mem'
            if is_sram:sram_bits+=bits
            else:register_bits+=bits
            rows.append(dict(module=mod['name'],signal=var['name'],instances=count,bits=bits,storage='SRAM' if is_sram else 'register'))
    assert sram_bits==20*4096*16,(sram_bits,counts)
    assert register_bits<=4096*8,register_bits
    assert all('mul_pipe' in m['module'] or m['module']=='kwt_mac8x8' for m in mult),mult
    assert sum(m['instances'] for m in mult)==68,mult
    report=dict(register_bits=register_bits,register_bytes_ceiling=(register_bits+7)//8,budget_bytes=4096,SRAM_bits=sram_bits,SRAM_macros=20,nonconstant_multiplications=mult,signals=rows,
                scope='declared sequential RTL bits including PE, pipeline, controller, bus and SRAM output state; excludes only macro data arrays; not synthesis/PPA')
    Path(out).write_text(json.dumps(report,indent=2));print(f'REGISTERS {register_bits} bits = {(register_bits+7)//8} B; SRAM=20x4096x16',flush=True);return report
if __name__=='__main__':
    import sys
    inventory(sys.argv[1],sys.argv[2])
