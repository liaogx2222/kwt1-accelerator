"""Update the proven score4 serial subset for the removed score scan."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REV='d8fe71081eb893b3c8394dc1d9c3a0ea1aa129ff'
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--log',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    raw=subprocess.check_output(['git','show',REV+':rtl/softmax_stream/kwt_layer_banked.sv'],cwd=ROOT);assert raw==(ROOT/'rtl/softmax_stream/kwt_layer_banked.sv').read_bytes();s=raw.decode()
    for frag in ['lane_a[ml]=$signed(score_rdata)-$signed(maximum);','if(math_accept&&sent<98)begin',
                 'maximum<=score_max_cache[norm_row];sent<=0;received<=0;exp_pending<=0;denominator<=0;state<=SM_RQ;']:
        assert frag in s,frag
    assert 'state<=S_CAPTURE' not in s
    base=ROOT/'evidence/score4_20261115/ceiling_v2/ceiling.json';old=json.loads(base.read_text());assert old['necessary_serial_cycles']==1377888
    rows=copy.deepcopy(old['phases']);row=next(p for p in rows if p['states']=='S_LOAD + S_CAPTURE');row.update(states='S_LOAD',cycles=12*99,derivation='one synchronous first-score request per row; SRAM advance overlaps the existing SM_RQ')
    states={n:int(v) for n,v in re.findall(r'\b([A-Z][A-Z0-9_]*)\s*=\s*(\d+)',s[:s.index('reg dq_active')])}
    obs={int(n):int(v) for n,v in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',a.log.read_text())};assert 70 not in obs
    names=[]
    for p in rows:
        group=[n.strip() for n in p['states'].split('+')];names+=group;p['observed']=sum(obs[states[n]] for n in group);assert p['observed']>=p['cycles']
    assert len(names)==len(set(names))==len({states[n] for n in names})
    lower=sum(p['cycles'] for p in rows);assert lower==1260276
    r=dict(source_commit=REV,source_SHA256=hashlib.sha256(raw).hexdigest(),analysis_only=True,necessary_serial_cycles=lower,phases=rows,
        base_proof_SHA256=hashlib.sha256(base.read_bytes()).hexdigest(),base_iterative_SHA256=old['iterative_SHA256'],
        frequency_assumed_Hz=150000000,frequency_signed_off=False,target_tasks_s=100,target_cycle_budget=1500000,
        ideal_upper_tasks_s_for_this_subset=150000000/lower,bound_rules_out_100=False,
        measured_compute_cycles=1644792,compute_only_upper_at_assumed150MHz=150000000/1644792,
        measured_task_cycles=2271587,measured_task_s_at_assumed150MHz=150000000/2271587,
        omitted=old['omitted'],goal100_achieved=False,physical_PPA_claimed=False,
        log_SHA256=hashlib.sha256(a.log.read_bytes()).hexdigest(),
        conclusion='serial subset no longer rules out100, but measured computation alone exceeds1.5M budget and current complete task is slower; further RTL/supply improvements required')
    (out/'ceiling.json').write_text(json.dumps(r,indent=2)+'\n');print(lower,r['compute_only_upper_at_assumed150MHz'],r['measured_task_s_at_assumed150MHz'])
