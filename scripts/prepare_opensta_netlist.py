"""Only Yosys serialization -simple-lhs, no logic pass; verify JSON roundtrip."""
import argparse,json,subprocess
from pathlib import Path
from local_tools import ROOT,sha
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    rel=out.relative_to(ROOT).as_posix();base=ROOT/'testdata/nangate45_reference/native_compat_20261104'
    for name,digest in json.loads((base/'manifest.json').read_text()).items():assert sha(base/name)==digest,name
    script=f'read_json testdata/nangate45_reference/native_compat_20261104/mapped.json\nwrite_verilog -noattr -noexpr -simple-lhs {rel}/mapped_simple.v\nwrite_json {rel}/roundtrip.json\n'
    (out/'serialize.ys').write_text(script)
    p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd /mnt/e/project/ChipCompetition/keyword-transformer && yosys -Q -T -s {rel}/serialize.ys'],capture_output=True,text=True);(out/'execution.log').write_text(p.stdout+p.stderr);assert p.returncode==0,p.stderr[-2000:]
    original=json.loads((base/'mapped.json').read_text())['modules']['kwt1_mmio'];after=json.loads((out/'roundtrip.json').read_text())['modules']['kwt1_mmio']
    assert original['cells']==after['cells'] and original['ports']==after['ports'] and original['netnames']==after['netnames']
    summary=dict(passed=True,scope='serialization only; same mapped JSON cell/port/net objects, no synth/opt passes; not a formal equivalence proof',cells=len(original['cells']),SRAM_macros=sum(c['type']=='kwt_tech_sram_4096x16' for c in original['cells'].values()),source_json_sha256=sha(base/'mapped.json'),netlist_sha256=sha(out/'mapped_simple.v'),script_sha256=sha(Path(__file__)))
    (out/'summary.json').write_text(json.dumps(summary,indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
