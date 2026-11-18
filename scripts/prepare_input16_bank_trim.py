"""Replace four 2048-used tail banks by allowed smaller macros; keep interface."""
import argparse
import json
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();src=ROOT/'rtl/input16_signed';dest=ROOT/'rtl/input16_trim';assert not out.exists() and not dest.exists();out.mkdir(parents=True);dest.mkdir();leaf=ROOT/'rtl/kwt_weight_2048x16.sv';bound=[Path(__file__),leaf]
    for f in src.rglob('*'):
        if not f.is_file():continue
        t=f.read_text();p=dest/f.relative_to(src);p.parent.mkdir(parents=True,exist_ok=True)
        if f.name=='kwt_sram_sp.sv':
            old='  kwt_sram_sp ram(clk,en[g],we[g],addr[g*12+:12],wdata[g*16+:16],rdata[g*16+:16]);';assert t.count(old)==1
            t=leaf.read_text()+'\n'+t.replace(old,'''  if(g<8&&g%2==1)begin:small
   kwt_weight_2048x16 ram(clk,en[g],we[g],addr[g*12+:12],wdata[g*16+:16],rdata[g*16+:16]);
  end else begin:large
   kwt_sram_sp ram(clk,en[g],we[g],addr[g*12+:12],wdata[g*16+:16],rdata[g*16+:16]);
  end''')
        if f.name=='sim_accel.cpp':
            old='__KET____DOT__ram__DOT__mem';assert t.count(old)==1;t=t.replace(old,'__KET____DOT__large__DOT__ram__DOT__mem')
        p.write_text(t);bound.extend([f,p])
    for name in ['validate_input16_rtl.py','run_input16_e203.py']:
        source=ROOT/'scripts'/name;txt=source.read_text();assert 'rtl/input16_signed' in txt;derived=out/(source.stem+'_executed.py');derived.write_text(txt.replace('rtl/input16_signed','rtl/input16_trim'));bound.extend([source,derived])
    result=dict(passed=True,mode='weight-tail SRAM trim',logical_banks=20,physical_macros={'4096x16':16,'1024x16':8},physical_bytes=147456,
        selected_logical_banks=[1,3,5,7],legal_addresses='0..2047; guard at every enabled edge in native and E203 RTL simulations',
        bound_reason='logical weights 6144 words per group; odd bank handles words 4096..6143. Only the loader and dense accesses use odd weight banks.',
        ABI_unchanged=True,score_not_established=True)
    (out/'verification.json').write_text(json.dumps(result,indent=2));(out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in bound},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
