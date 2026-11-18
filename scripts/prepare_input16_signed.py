"""Explicit 16-bit extension at mixed signed/unsigned conditional boundaries."""
import argparse
import json
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();src=ROOT/'rtl/input16';dest=ROOT/'rtl/input16_signed';assert not out.exists() and not dest.exists();out.mkdir(parents=True);dest.mkdir()
    files=list(src.rglob('*'));bound=[Path(__file__)];changes=0
    for f in files:
        if not f.is_file():continue
        target=dest/f.relative_to(src);target.parent.mkdir(parents=True,exist_ok=True);text=f.read_text()
        if f.name=='kwt_layer_banked.sv':
            old=' task read_word';assert text.count(old)==1
            text=text.replace(old,' function automatic signed [15:0] extended_byte(input [319:0] data,input integer bank,input integer high);begin extended_byte=$signed(byte_at(data,bank,high));end endfunction\n'+old)
            import re
            text,n=re.subn(r'\$signed\(byte_at\(([^\n]*?)\)\)',r'extended_byte(\1)',text)
            # The helper itself must retain its signed 8-to-16 assignment.
            text=text.replace('begin extended_byte=extended_byte(data,bank,high);','begin extended_byte=$signed(byte_at(data,bank,high));')
            assert n==4,n;changes=n-1
        target.write_text(text);bound.extend([f,target])
    report=dict(passed=True,explicit_sign_extensions=changes,reason='16-bit function result avoids conditional unsigned promotion of negative S8 operands',RTL_functional_verification=False)
    (out/'verification.json').write_text(json.dumps(report,indent=2));(out/'source_bindings.json').write_text(json.dumps({f.relative_to(ROOT).as_posix():sha(f) for f in bound},indent=2));(out/'manifest.json').write_text(json.dumps({f.name:sha(f) for f in out.iterdir() if f.is_file()},indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
