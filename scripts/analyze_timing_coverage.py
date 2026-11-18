"""Structural cone coverage: macros/I/O/reset. Not a replacement for STA paths."""
import argparse,collections,json
from pathlib import Path
from local_tools import ROOT,sha
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    source=ROOT/'testdata/nangate45_reference/native_compat_20261104/mapped.json';net=json.loads(source.read_text())['modules']['kwt1_mmio'];forward=collections.defaultdict(list);flops=[];macro_bits=[];macro_ports=[]
    for name,c in net['cells'].items():
        kind=c['type'];ports=c['connections'];directions=c['port_directions']
        if kind.startswith('DFF'):flops.append((name,c));continue
        if kind=='kwt_tech_sram_4096x16':
            macro_bits.extend(bit for bit in ports['rdata'] if isinstance(bit,int))
            macro_ports.append(dict(instance=name,inputs={k:v for k,v in ports.items() if directions[k]=='input'},outputs={k:v for k,v in ports.items() if directions[k]=='output'}));continue
        inputs={b for k,v in ports.items() if directions[k]=='input' for b in v if isinstance(b,int)};outputs={b for k,v in ports.items() if directions[k]=='output' for b in v if isinstance(b,int)}
        for bit in inputs:forward[bit].extend(outputs)
    assert len(flops)==29942 and len(macro_ports)==20
    def reachable(starts):
        seen=set(starts);queue=collections.deque(seen)
        while queue:
            b=queue.popleft()
            for v in forward.get(b,[]):
                if v not in seen:seen.add(v);queue.append(v)
        return seen
    macro_reach=reachable(macro_bits);abort_reach=reachable(net['netnames']['sw_abort']['bits'])
    io_bits=[b for name,p in net['ports'].items() if p['direction']=='input' and name!='clk' for b in p['bits'] if isinstance(b,int)];io_reach=reachable(io_bits)
    macro_regs=[];io_regs=[];abort_regs=[]
    for name,c in flops:
        if any(b in macro_reach for b in c['connections']['D']):macro_regs.append(name)
        if any(b in io_reach for b in c['connections']['D']):io_regs.append(name)
        if any(b in abort_reach for b in c['connections']['D']):abort_regs.append(name)
    critical={}
    for label,index in [('accel.core.math_unit.rne.result',19),('accel.core.math_unit.rne.result',63)]:
        q=net['netnames'][label]['bits'][index];matches=[(n,c) for n,c in flops if q in c['connections'].get('Q',[])];assert len(matches)==1
        name,c=matches[0];critical[f'{label}[{index}]']=dict(JSON_cell_name=name,macro_output_combinationally_reaches_D=name in macro_regs,unconstrained_top_input_combinationally_reaches_D=name in io_regs,sw_abort_combinationally_reaches_D=name in abort_regs)
    summary=dict(analysis_executed=True,scope='structural over-approximation, sequential boundaries stop traversal; ignores case-analysis/sensitization and does not count timing paths',register_data_endpoints=29942,macro_instances=20,macro_output_bits=len(macro_bits),macro_data_input_bits=sum(len(bits) for m in macro_ports for pin,bits in m['inputs'].items() if pin!='clk'),macro_affected_register_D_endpoints=len(macro_regs),top_input_affected_register_D_endpoints=len(io_regs),sw_abort_affected_register_D_endpoints=len(abort_regs),critical_RNE_endpoints=critical,warning='A reported setup path to every D pin is not complete source/arc coverage; macro and I/O source timing can be absent in mixed cones',source_json_sha256=sha(source),script_sha256=sha(Path(__file__)),complete_STA=False)
    for filename,value in [('summary.json',summary),('macro_boundaries.json',macro_ports),('macro_related_registers.json',macro_regs),('unconstrained_IO_related_registers.json',io_regs),('soft_abort_related_registers.json',abort_regs)]: (out/filename).write_text(json.dumps(value,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':main()
