"""Bound mapped Dense data/control fanout without changing original cells."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from buffer_input16_fanout import cell_digest
from local_tools import ROOT, sha


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fanout',type=int,default=12)
    args=parser.parse_args()
    assert 2<=args.fanout<=32
    source=args.source.resolve()
    out=args.output.resolve()
    netlist=source/'mapped.json'
    original=json.loads((source/'manifest.json').read_text())
    assert sha(netlist)==original['mapped.json']
    report=json.loads((source/'verification.json').read_text())
    assert report['rq']=='right'
    design=json.loads(netlist.read_text())
    top=design['modules']['e203_subsys_nice_core']
    cells=top['cells']
    nets=top['netnames']
    names=sorted(cells)
    before=cell_digest(cells,names,{})
    clock=top['ports']['nice_clk']['bits'][0]
    next_bit=max(bit for net in nets.values() for bit in net['bits'] if isinstance(bit,int))+1
    sinks=defaultdict(list)
    drivers={}
    for name in names:
        cell=cells[name]
        for port,bits in cell['connections'].items():
            for index,bit in enumerate(bits):
                if not isinstance(bit,int) or bit==clock:
                    continue
                if cell['port_directions'][port]=='input':
                    sinks[bit].append((name,port,index))
                else:
                    drivers[bit]=(name,port,cell['type'])

    out.mkdir(parents=True)
    records=[]
    aliases={}
    buffers={}
    for root,pins in sorted(sinks.items()):
        if len(pins)<=args.fanout:
            continue
        pending=pins
        start=next_bit
        while len(pending)>args.fanout:
            parents=[]
            for offset in range(0,len(pending),args.fanout):
                bit=next_bit
                next_bit+=1
                name=f'dense_fanout_buf_{bit}'
                assert name not in cells and name+'_net' not in nets
                nets[name+'_net']=dict(hide_name=0,bits=[bit],attributes={})
                cells[name]=dict(hide_name=0,type='BUF_X1',parameters={},attributes={},
                                 port_directions={'A':'input','Z':'output'},connections={'A':[root],'Z':[bit]})
                buffers[bit]=name
                aliases[bit]=root
                for sink,port,index in pending[offset:offset+args.fanout]:
                    cells[sink]['connections'][port][index]=bit
                parents.append((name,'A',0))
            pending=parents
        records.append(dict(bit=root,driver=drivers.get(root),old_fanout=len(pins),
                            root_fanout=len(pending),buffers=next_bit-start))
    assert before==cell_digest(cells,names,aliases)
    for bit,name in buffers.items():
        parent=cells[name]['connections']['A'][0]
        assert parent==aliases[bit] or (parent>bit and aliases[parent]==aliases[bit])
    loads=defaultdict(int)
    for cell in cells.values():
        for port,bits in cell['connections'].items():
            if cell['port_directions'][port]=='input':
                for bit in bits:
                    if isinstance(bit,int) and bit!=clock:
                        loads[bit]+=1
    assert max(loads.values())<=args.fanout
    with (out/'mapped.json').open('w') as fd:
        json.dump(design,fd,separators=(',',':'))
    area=0.798e-6*len(buffers)
    result=dict(passed=True,rq='right',scope='post-map fanout ECO with structural projection',
                structural_projection_verified=True,clock_net_excluded=True,complete_gate_regression=False,
                before_max_fanout=max(map(len,sinks.values())),after_max_fanout=max(loads.values()),
                buffers=len(buffers),area_increment_mm2=area,
                supply_dense_partition_standard_cell_mm2=report['supply_dense_partition_standard_cell_mm2']+area,
                trees=sorted(records,key=lambda row:row['old_fanout'],reverse=True),
                source_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in
                               [Path(__file__),netlist,source/'verification.json',ROOT/'scripts/buffer_input16_fanout.py']})
    (out/'verification.json').write_text(json.dumps(result,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='trees'},indent=2))


if __name__=='__main__':
    main()
