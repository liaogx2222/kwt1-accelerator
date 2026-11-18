"""Declared production accelerator state, excluding its twenty SRAM arrays."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
def walk(v):
    if isinstance(v,dict):
        yield v
        for x in v.values():yield from walk(x)
    elif isinstance(v,list):
        for x in v:yield from walk(x)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--project',required=True,type=Path);ap.add_argument('--output',required=True,type=Path)
    a=ap.parse_args();p=a.project.resolve();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    vr=ROOT.parent/'keyword-transformer/tools/rtl_v1_python/verilator'
    env=dict(os.environ,VERILATOR_ROOT=str(vr))
    names=[n for n in (p/'flow/local_sources.txt').read_text().splitlines() if n.startswith('rtl/')]
    cmd=[vr/'bin/verilator_bin.exe','--json-only','--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC',
         '-I'+str(p/'rtl/v2/generated'),'-GBLOCK_STREAM=1','--top-module','kwt1_mmio','--Mdir',out,*[p/n for n in names]]
    q=subprocess.run(list(map(str,cmd)),cwd=p,env=env,capture_output=True,text=True)
    (out/'tool.log').write_text(q.stdout+q.stderr);(out/'command.json').write_text(json.dumps(list(map(str,cmd)),indent=2));assert q.returncode==0
    tree=json.loads((out/'Vkwt1_mmio.tree.json').read_text());nodes={n['addr']:n for n in walk(tree) if 'addr' in n};mods={n['addr']:n for n in tree['modulesp']}
    def width(ref):
        n=nodes[ref]
        if n['type']=='BASICDTYPE':
            if 'range' not in n:return 1
            hi,lo=map(int,n['range'].split(':'));return abs(hi-lo)+1
        if n['type']=='UNPACKARRAYDTYPE':
            hi,lo=map(int,re.findall(r'-?\d+',n['declRange']));return (abs(hi-lo)+1)*width(n['refDTypep'])
        raise ValueError(n['type'])
    counts=Counter()
    def visit(ref):
        counts[ref]+=1
        for n in walk(mods[ref]):
            if n['type']=='CELL':visit(n['modp'])
    visit(next(k for k,v in mods.items() if v['name']=='kwt1_mmio'))
    bits=0;sram=0;signals=[];multipliers=0
    for ref,count in counts.items():
        mod=mods[ref];assigned=set()
        for n in walk(mod):
            if n['type']=='ASSIGNDLY':assigned.update(v['varp'] for v in walk(n['lhsp']) if v['type']=='VARREF' and v.get('access') in ['WR','RW'])
            if n['type'] in ['MUL','MULS']:
                args=[v for k in ['lhsp','rhsp'] for v in n.get(k,[])]
                if len(args)==2 and all(v['type']!='CONST' for v in args):multipliers+=count
        for v in assigned:
            var=nodes[v];size=width(var['dtypep'])*count;ram=mod.get('origName')=='kwt_sram_sp' and var['name']=='mem'
            if ram:sram+=size
            else:bits+=size
            signals.append(dict(module=mod['name'],signal=var['name'],bits=size,storage='SRAM' if ram else 'register'))
    assert sram==20*4096*16
    sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
    r=dict(passed=True,BLOCK_STREAM=1,declared_register_bits=bits,register_bytes_ceiling=(bits+7)//8,
        private_SRAM_macros=20,private_SRAM_bytes=sram//8,multiplier_operator_instances=multipliers,
        source_sha256={n:sha(p/n) for n in names+['rtl/v2/generated/kwt_profile.svh']},signals=signals,
        scope='declared accelerator RTL state only; no CPU/shared/TCM/NICE area or physical mapping claim')
    (out/'summary.json').write_text(json.dumps(r,indent=2)+'\n');print('PRODUCTION INVENTORY',bits,'bits',(bits+7)//8,'B',multipliers,'multiply operators',flush=True)
