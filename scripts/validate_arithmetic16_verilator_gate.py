"""Same SV acceptance TB, compiled timed Verilator, actual mapped cells."""
import argparse
import json
import subprocess
from pathlib import Path
from local_tools import ROOT,sha
import validate_arithmetic16 as original

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--mapped',type=Path,required=True);ap.add_argument('--single',action='store_true');ap.add_argument('--passes',type=int,default=1);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);original.vectors(out);rel=out.relative_to(ROOT).as_posix();mapped=a.mapped.resolve()
    if a.single:
        tb=(out/'tb.sv').read_text().replace('c%2','0').replace('||bank_overlap==0','');(out/'tb.sv').write_text(tb)
    src=[mapped/'mapped.v',mapped/'functional_cells.v']
    for name,digest in json.loads((mapped/'manifest.json').read_text()).items():assert sha(mapped/name)==digest,name
    def run(cmd,name):
        r=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+cmd],capture_output=True,text=True)
        (out/(name+'.log')).write_text(r.stdout+r.stderr);assert r.returncode==0,(name,r.stdout[-1600:],r.stderr[-1200:]);return r.stdout
    tools=run('verilator --version','tools')
    names=' '.join(p.relative_to(ROOT).as_posix() for p in src)
    run(f'verilator --binary --timing --top-module tb -Wno-fatal --output-split 18000 --output-split-cfuncs 200 -j 4 --Mdir {rel}/model {names} {rel}/tb.sv','build')
    result=run(f'{rel}/model/Vtb +root={rel} +passes={a.passes}','simulation');assert 'PASS cases=96' in result,result[-1500:]
    expected={n:[int(v,16) for v in (out/'vectors'/f'{n}.hex').read_text().split()] for n in ['raw','rq','error']};codes=0
    for line in (out/'observed.txt').read_text().splitlines():
        f=line.split();tag=int(f[2]);assert int(f[3],16)==expected['raw' if f[0]=='RAW' else 'rq'][tag]
        if f[0]=='RQ':assert int(f[4])==expected['error'][tag]
        codes+=4
    assert codes==49408*a.passes
    report=dict(passed=True,profiles=96,passes=a.passes,independently_checked_scalar_codes=codes,mismatches=0,mapped_functional_regression=True,
        simulator=tools.strip(),simulator_semantics='compiled timed SV, functional same-library cells, no SDF; no all-X formal claim',
        accumulator_buffers=1 if a.single else 2,scope='arithmetic partition only, not full encoder RTL/SoC/SRAM',full_encoder_RTL=False,summary=result)
    (out/'verification.json').write_text(json.dumps(report,indent=2));bound=[Path(__file__),Path(original.__file__),*src,mapped/'manifest.json',original.component.BASE/'run/params/parameters.npz']
    (out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in bound},indent=2))
    selected=[p for p in out.rglob('*') if p.is_file() and 'model' not in p.relative_to(out).parts]+[out/'model/Vtb']
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in selected},indent=2));print(json.dumps(report,indent=2))

if __name__=='__main__':main()
