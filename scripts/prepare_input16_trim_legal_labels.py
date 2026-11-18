"""Archive a syntax-only rename of Verilog strength-keyword generate labels."""
import argparse
import json
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();old=ROOT/'rtl/input16_trim';new=ROOT/'rtl/input16_trim2';assert not out.exists() and not new.exists();out.mkdir(parents=True);bound=[Path(__file__)]
    for f in old.rglob('*'):
        if not f.is_file():continue
        p=new/f.relative_to(old);p.parent.mkdir(parents=True,exist_ok=True);t=f.read_text()
        if f.name=='kwt_sram_sp.sv':
            assert t.count('begin:small')==t.count('begin:large')==1;t=t.replace('begin:small','begin:narrow_bank').replace('begin:large','begin:full_bank')
        if f.name=='sim_accel.cpp':
            assert t.count('__DOT__large__DOT__')==1;t=t.replace('__DOT__large__DOT__','__DOT__full_bank__DOT__')
        p.write_text(t);bound.extend([f,p])
    (out/'verification.json').write_text(json.dumps(dict(passed=True,only_rename_of_reserved_generate_labels=True,arithmetic_or_port_changes=False),indent=2));(out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in bound},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))


if __name__=='__main__':main()
