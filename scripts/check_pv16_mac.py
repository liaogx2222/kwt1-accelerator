"""Four-state PE equivalence including full U16, signed8, masks and idle X."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from local_tools import Tools

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--project',required=True,type=Path);ap.add_argument('--output',required=True,type=Path)
    a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    tools=Tools();iv=tools.find('iverilog',candidates=[Path('C:/iverilog/bin/iverilog.exe')])
    vvp=tools.find('vvp',candidates=[iv.with_name('vvp'+iv.suffix)])
    src=[a.project.resolve()/'rtl/v2/kwt_mac_array.sv',ROOT/'rtl/pv16_opt/tb_pv16_mac.sv'];exe=out/'sim.vvp'
    def run(cmd,log):
        p=subprocess.run(list(map(str,cmd)),cwd=ROOT,capture_output=True,text=True);log.write_text(p.stdout+p.stderr)
        assert p.returncode==0,str(log);return p.stdout
    run([iv,'-g2012','-s','tb_pv16_mac','-o',exe,*src],out/'compile.log')
    text=run([vvp,exe],out/'run.log');assert 'PASS PV16_MAC four_state=1' in text
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    r=dict(passed=True,four_state=True,scope='unchanged PE datapath only; not full SoC/vendor/gate X proof',
        reference='old low-byte and high-byte products accumulated separately then exactly recombined',
        cases=256,terms_per_case=99,masks_and_idle_X=True,inflight_resets=16,
        source_sha256={str(p):sha(p) for p in src},tool_sha256={str(p):sha(p) for p in [iv,vvp]},result=text)
    (out/'summary.json').write_text(json.dumps(r,indent=2)+'\n');print(text)
