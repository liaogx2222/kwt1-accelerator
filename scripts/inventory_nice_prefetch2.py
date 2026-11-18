"""Elaborate exact NICE state at production TIMEOUT; no area estimate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from inventory_pv16 import walk

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    baseline=out/'baseline.sv';baseline.write_bytes(subprocess.check_output(['git','show','595724b88858b142a407f6a5c4761945252d523b:rtl/arch60_block/kwt_nice_block.sv'],cwd=ROOT))
    vr=ROOT.parent/'keyword-transformer/tools/rtl_v1_python/verilator';env=dict(os.environ,VERILATOR_ROOT=str(vr));rows={}
    for label,source in [('baseline',baseline),('prefetch',ROOT/'rtl/nice_prefetch2/kwt_nice_block.sv')]:
        dest=out/label;dest.mkdir();cmd=[vr/'bin/verilator_bin.exe','--json-only','--Wno-fatal','--top-module','e203_subsys_nice_core','--Mdir',dest,source]
        p=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,capture_output=True,text=True);(dest/'tool.log').write_text(p.stdout+p.stderr);assert p.returncode==0
        tree=json.loads((dest/'Ve203_subsys_nice_core.tree.json').read_text());nodes={n['addr']:n for n in walk(tree) if 'addr' in n}
        def width(ref):
            n=nodes[ref]
            if n['type']=='BASICDTYPE':
                hi,lo=map(int,n.get('range','0:0').split(':'));return abs(hi-lo)+1
            if n['type']=='UNPACKARRAYDTYPE':
                hi,lo=map(int,re.findall(r'-?\d+',n['declRange']));return (abs(hi-lo)+1)*width(n['refDTypep'])
            raise ValueError(n['type'])
        assigned={v['varp'] for n in walk(tree) if n['type']=='ASSIGNDLY' for v in walk(n['lhsp']) if v['type']=='VARREF' and v.get('access') in ['WR','RW']}
        bits={nodes[k]['name']:width(nodes[k]['dtypep']) for k in assigned}
        rows[label]=dict(bits=sum(bits.values()),signals=bits,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),command=list(map(str,cmd)))
    assert rows['baseline']['bits']==168 and rows['prefetch']['bits']==229
    result=dict(passed=True,production_TIMEOUT=131072,NICE_state_delta_bits=61,owner_queue_delta_bits=9,total_declared_state_delta_bits=70,cases=rows,scope='NICE declared RTL state; no mapped area/power or whole SoC state claim')
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
