"""Serial build of fully generated gate C++, after Verilator process exits.

Separating generation and make avoids retaining the netlist AST while C++
workers consume memory. No generated Verilog/C++ source is changed.
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path
from local_tools import ROOT,sha
import validate_arithmetic16 as original

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--generated',type=Path,required=True);ap.add_argument('--mapped',type=Path,required=True);ap.add_argument('--single',action='store_true');a=ap.parse_args();out=a.output.resolve();generated=a.generated.resolve();mapped=a.mapped.resolve();assert not out.exists();out.mkdir(parents=True);original.vectors(out)
    shutil.copyfile(generated.parent/'tb.sv',out/'tb.sv')
    assert (generated/'Vtb.mk').exists() and (generated/'Vtb__main.cpp').exists()
    def run(cmd,name):
        p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+cmd],capture_output=True,text=True)
        (out/(name+'.log')).write_text(p.stdout+p.stderr);assert p.returncode==0,(name,p.stdout[-1600:],p.stderr[-1000:]);return p.stdout
    gen=generated.relative_to(ROOT).as_posix();rel=out.relative_to(ROOT).as_posix()
    run(f'make -B -C {gen} -f Vtb.mk -j1 OPT_FAST=-O0 OPT_SLOW=-O0','serial_build')
    result=run(f'{gen}/Vtb +root={rel} +passes=1','simulation');assert 'PASS cases=96' in result
    expected={n:[int(v,16) for v in (out/'vectors'/f'{n}.hex').read_text().split()] for n in ['raw','rq','error']};codes=0
    for line in (out/'observed.txt').read_text().splitlines():
        f=line.split();tag=int(f[2]);assert int(f[3],16)==expected['raw' if f[0]=='RAW' else 'rq'][tag]
        if f[0]=='RQ':assert int(f[4])==expected['error'][tag]
        codes+=4
    assert codes==49408
    report=dict(passed=True,profiles=96,passes=1,independently_checked_scalar_codes=codes,mismatches=0,mapped_functional_regression=True,
        simulator='timed Verilator, serial C++ build OPT_FAST=-O0',accumulator_buffers=1 if a.single else 2,
        scope='same mapped arithmetic partition and SV TB; no SDF/full encoder/SoC claim',full_encoder_RTL=False,summary=result,
        generated_cpp_source=gen,generated_source_edited=False)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    bound=[Path(__file__),Path(original.__file__),mapped/'mapped.v',mapped/'functional_cells.v',generated.parent/'tb.sv',original.component.BASE/'run/params/parameters.npz']
    bound+=[p for p in generated.iterdir() if p.suffix in ['.cpp','.h','.mk']]
    (out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in bound},indent=2));selected=[p for p in out.rglob('*') if p.is_file()]
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in selected},indent=2));print(json.dumps(report,indent=2))

if __name__=='__main__':main()
