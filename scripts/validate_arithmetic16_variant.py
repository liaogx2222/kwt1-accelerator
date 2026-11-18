"""Identical golden vectors/TB for the static-PE variant or mapped partition."""
import argparse
import json
import subprocess
from pathlib import Path
from local_tools import ROOT,sha
import validate_arithmetic16 as original


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--mapped',type=Path);ap.add_argument('--passes',type=int,default=2);args=ap.parse_args();out=args.output.resolve();assert not out.exists();out.mkdir(parents=True);cases=original.vectors(out);rel=out.relative_to(ROOT).as_posix()
    src=ROOT/'rtl/experimental/kwt_arithmetic16_structural.sv';sources=[ROOT/'rtl/micro/mul_pipe.sv',ROOT/'rtl/micro/rne_pipe.sv',src]
    used=[args.mapped.resolve()/'mapped.v',args.mapped.resolve()/'functional_cells.v'] if args.mapped else sources
    def run(cmd,name):
        r=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+cmd],capture_output=True,text=True)
        (out/(name+'.log')).write_text(r.stdout+r.stderr);assert r.returncode==0,(name,r.stdout[-1500:],r.stderr[-800:]);return r.stdout
    run(f'iverilog -g2012 -s tb -o {rel}/test.vvp '+ ' '.join(p.relative_to(ROOT).as_posix() for p in used)+f' {rel}/tb.sv','compile')
    text=run(f'vvp {rel}/test.vvp +root={rel} +passes={args.passes}','simulation');assert 'PASS cases=96' in text
    expected={n:[int(s,16) for s in (out/'vectors'/f'{n}.hex').read_text().split()] for n in ['raw','rq','error']};codes=0
    for line in (out/'observed.txt').read_text().splitlines():
        f=line.split();tag=int(f[2]);assert int(f[3],16)==expected['raw' if f[0]=='RAW' else 'rq'][tag]
        if f[0]=='RQ':assert int(f[4])==expected['error'][tag]
        codes+=4
    assert codes==49408*args.passes
    report=dict(passed=True,profiles=96,passes=args.passes,independently_checked_scalar_codes=codes,mismatches=0,structural_PE_variant=True,
        RTL_or_mapped='mapped partition' if args.mapped else 'RTL partition',full_encoder_RTL=False,SRAM_macros_in_partition=0,summary=text)
    (out/'verification.json').write_text(json.dumps(report,indent=2));bindings=[Path(__file__),Path(original.__file__),*sources,*used,original.component.BASE/'run/params/parameters.npz']
    (out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in bindings},indent=2));(out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()},indent=2));print(json.dumps(report,indent=2))

if __name__=='__main__':main()
