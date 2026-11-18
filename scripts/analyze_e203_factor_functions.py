"""Reproducible exclusive PC-bin grouping; never infer inclusive call latency."""
import argparse,json,shutil
from pathlib import Path
from local_tools import ROOT,sha

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();base=a.input.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if (out/'manifest.json').exists():raise ValueError('Published analysis exists; use new output')
    rows={};bindings={}
    for group in ['p0_baseline','p1a_null_cancel','p1b_aligned','p1c_itcm']:
        folder=base/group;symbols=[]
        for line in (folder/'firmware.nm').read_text().splitlines():
            address,kind,name=line.split()
            if kind.lower()=='t':symbols.append((int(address,16),name))
        functions={}
        for line in (folder/'window_counts.txt').read_text().splitlines():
            fields=line.split()
            if fields[:2]!=['pc','0']:continue
            pc,cycles,retired=map(int,fields[2:]);name=max(s for s in symbols if s[0]<=pc)[1]
            row=functions.setdefault(name,dict(cycles=0,retired=0));row['cycles']+=cycles;row['retired']+=retired
        summary=json.loads((folder/'summary.json').read_text())
        assert sum(r['cycles'] for r in functions.values())==summary['main']['cycles']
        assert sum(r['retired'] for r in functions.values())==summary['main']['retired']
        rows[group]=functions
        for path in [folder/'firmware.nm',folder/'window_counts.txt',folder/'summary.json']:bindings[path.relative_to(ROOT).as_posix()]=sha(path)
    report=dict(passed=True,functions=rows,input_sha256=bindings,script_sha256=sha(Path(__file__)),semantics='shadow IR residency includes stalls; counts are exclusive PC bins, not inclusive call costs')
    (out/'function_comparison.json').write_text(json.dumps(report,indent=2));shutil.copyfile(Path(__file__),out/'source_executed.py')
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print('PASS function cycles and retirements conserved in all four configurations')

if __name__=='__main__':main()
