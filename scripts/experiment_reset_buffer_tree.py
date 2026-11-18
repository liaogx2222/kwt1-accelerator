"""Mapping-only diagnostic: non-inverting tree, old-cell projection conserved."""
import argparse,hashlib,json,math,re,subprocess
from pathlib import Path
from local_tools import ROOT,sha
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);rel=out.relative_to(ROOT).as_posix();source=ROOT/'testdata/nangate45_reference/native_compat_20261104/mapped.json';design=json.loads(source.read_text());m=design['modules']['kwt1_mmio'];cells=m['cells'];old_names=sorted(cells)
    def digest(project=None):
        h=hashlib.sha256()
        for name in old_names:
            c=cells[name]
            if project:
                c={**c,'connections':{p:[project.get(b,b) if c['port_directions'][p]=='input' else b for b in v] for p,v in c['connections'].items()}}
            h.update(name.encode());h.update(json.dumps(c,sort_keys=True,separators=(',',':')).encode())
        return h.hexdigest()
    before=digest();root=m['netnames']['accel.task_rst_n']['bits'][0];sinks=[]
    for name in old_names:
        c=cells[name]
        for pin,bits in c['connections'].items():
            if c['port_directions'][pin]=='input':sinks.extend((name,pin,i) for i,b in enumerate(bits) if b==root)
    assert len(sinks)==4794
    ids=[b for n in m['netnames'].values() for b in n['bits'] if isinstance(b,int)];newid=max(ids)+1;del ids;created=[];projection={};pending=sinks[:];level=0
    while len(pending)>16:
        next_level=[]
        for group_start in range(0,len(pending),16):
            name=f'ref_reset_L{level}_{group_start//16:04d}';bit=newid;newid+=1
            m['netnames'][name+'_net']=dict(hide_name=0,bits=[bit],attributes={});cells[name]=dict(hide_name=0,type='BUF_X1',parameters={},attributes={},port_directions={'A':'input','Z':'output'},connections={'A':[root],'Z':[bit]})
            for sink,pin,index in pending[group_start:group_start+16]:cells[sink]['connections'][pin][index]=bit
            projection[bit]=root;created.append(name);next_level.append((name,'A',0))
        pending=next_level;level+=1
    for name,pin,i in pending:cells[name]['connections'][pin][i]=root
    assert digest(projection)==before
    assert len(created)==321 and sum(c['type'].startswith('DFF') for c in cells.values())==29942 and sum(c['type']=='kwt_tech_sram_4096x16' for c in cells.values())==20
    # Check every inserted buffer reaches the original root, without loops.
    drivers={cells[name]['connections']['Z'][0]:cells[name]['connections']['A'][0] for name in created}
    for bit in drivers:
        visited=set();current=bit
        while current!=root:assert current not in visited and current in drivers;visited.add(current);current=drivers[current]
    (out/'buffered.json').write_text(json.dumps(design,separators=(',',':')));del design
    script=f'read_json {rel}/buffered.json\nwrite_verilog -noattr -noexpr -simple-lhs {rel}/mapped_buffered.v\n'
    (out/'write.ys').write_text(script);p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd /mnt/e/project/ChipCompetition/keyword-transformer && yosys -Q -T -s {rel}/write.ys'],capture_output=True,text=True);(out/'execution.log').write_text(p.stdout+p.stderr);assert p.returncode==0,p.stderr[-2000:]
    lib=(ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib').read_text();start=re.search(r'cell\s*\(\s*BUF_X1\s*\)\s*\{',lib);area=float(re.search(r'\barea\s*:\s*([\d.]+)',lib[start.end():])[1]);assert area==0.798
    summary=dict(passed=True,scope='mapping-only diagnostic, not adopted production netlist; non-inverting buffer tree and exact projection of every original cell, no formal/full-task verification of this variant',inserted_buffers=321,buffer_type='BUF_X1',levels=level,max_tree_fanout=16,original_sinks=len(sinks),original_cell_projection_sha256=before,projection_unchanged=True,inserted_sequential_bits=0,SRAM_macros=20,standard_cell_area_increment_um2=len(created)*area,standard_cell_area_um2=475862.296+len(created)*area,netlist_sha256=sha(out/'mapped_buffered.v'),source_json_sha256=sha(source),script_sha256=sha(Path(__file__)),functional_variant_regression=False,physical_signoff=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
