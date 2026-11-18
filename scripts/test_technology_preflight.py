"""Directed negative tests without fictitious foundry libraries or RTL edits."""
import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path
import check_technology as tech
from local_tools import ROOT,sha

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    template=ROOT/'flow/targets/smic40.binding.pending.json';cfg=json.loads(template.read_text());results={}
    p=subprocess.run([sys.executable,ROOT/'scripts/check_technology.py','--config',template,'--output',out/'unbound.json'],capture_output=True,text=True)
    assert p.returncode==2,p.returncode
    r=json.loads(p.stdout);assert len(r['ports'])==16 and not r['preflight_passed'] and len(r['missing'])==31 and not r['errors'];results['unbound_exit_2']=True
    changes=[('wrong_top',lambda c:c.update(top='wrong'), 'top must'),
             ('missing_macro',lambda c:c['sram'].update(instances=19),'sram.instances'),
             ('wrong_macro_latency',lambda c:c['sram'].update(read_latency_cycles=2),'sram.read_latency'),
             ('wrong_clock',lambda c:c['clock'].update(period_ns=10),'clock must'),
             ('blanket_false_path',lambda c:c['exceptions'].append(dict(scope='all',source='test',reason='test')),'Whole-domain')]
    for name,modify,error in changes:
        c=copy.deepcopy(cfg);modify(c);path=out/(name+'.json');path.write_text(json.dumps(c));r=tech.check(path)
        assert not r['preflight_passed'] and any(error in s for s in r['errors']);results[name]=True
    assert all('io.'+kind+'_delay_ns.'+port in r['missing'] for port,kind in tech.ports().items() if port not in ['clk','rst_n']);results['all_14_nonclock_reset_ports_unconstrained']=True
    original=tech.sha
    try:
        tech.sha=lambda path:'injected_bad_digest'
        r=tech.check(template);assert any(s.startswith('source drift:') for s in r['errors']);results['source_digest_fault_injection']=True
    finally:tech.sha=original
    report=dict(passed=True,tests=results,no_foundry_files_created=True,source_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in [template,ROOT/'scripts/check_technology.py',Path(__file__)]})
    (out/'tests.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

if __name__=='__main__':main()
