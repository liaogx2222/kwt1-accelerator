"""Bind the measured LN scheduling delta to the committed source and inventory."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PARENT = 'eb7277e3774b147c2c69ecfbbdaaeeb148363c3d'
REV = '80e2ab4170a3d96518766d5f1d4561cd7577132c'
CORE = 'rtl/v2/kwt_layer_banked.sv'
ITER = 'rtl/v2/kwt_iterative.sv'
DELTA = {33:-2016, 51:-138240, 75:-1152, 76:-73728, 59:-2016, 95:117504}

def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def phase(p):
    return {int(k):int(v) for k,v in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',p.read_text())}

if __name__ == '__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--round',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();base=a.round.resolve();out=a.output.resolve();assert not out.exists()
    cm,bm=[read(base/n/'project/source_manifest.json') for n in ['candidate','baseline']]
    data=subprocess.check_output(['git','show',REV+':rtl/ln4_opt/kwt_layer_banked.sv'],cwd=ROOT)
    assert data==(ROOT/'rtl/ln4_opt/kwt_layer_banked.sv').read_bytes()
    assert hashlib.sha256(data).hexdigest()==cm['files'][CORE]
    assert sorted(n for n in cm['files'] if cm['files'][n]!=bm['files'][n])==[CORE]
    assert cm['files'][ITER]=='69fe36f441d5aef4d3dc6e07d097784e36e9cd2912a7fef9ca19cd2c9bd933e8'
    old,new=[phase(base/n/'cold0/case_00/run.log') for n in ['baseline','candidate']]
    delta={n:new.get(n,0)-old.get(n,0) for n in old.keys()|new.keys() if old.get(n,0)!=new.get(n,0)}
    assert delta==DELTA and sum(delta.values())==-99648
    inv=read(base/'inventory/summary.json');before=read(ROOT/'evidence/iter_fast_20261115/inventory/summary.json')
    for n in ['declared_register_bits','multiplier_operator_instances','private_SRAM_macros']:
        assert inv[n]==before[n]
    assert inv['declared_register_bits']==32949 and inv['private_SRAM_macros']==20 and inv['multiplier_operator_instances']==144
    b,c=[read(base/n/'cold0/summary.json')['cases'][0] for n in ['baseline','candidate']]
    assert b['profiles'][0][2:]==[2265230,1568760,7615408,1239000]
    assert c['profiles'][0][2:]==[2256860,1469112,7615408,1239000]
    # Every complete batch: even+odd x three passes x (64 requests +4 drain).
    # 12 batches/layer x12layers x2LN =288 batches.
    assert 288*2*3*(64+4)==new[95]==117504
    r=dict(passed=True,parent_commit=PARENT,production_commit=REV,files={n:cm['files'][n] for n in [CORE,ITER]},
        phase_cycle_changes=delta,compute_cycles=[1568760,1469112],compute_cycles_saved=99648,
        task_cycles=[2265230,2256860],task_cycles_saved=8370,noncompute_wait_added=91278,
        declared_register_bits=[32949,32949],multiplier_operator_instances=[144,144],private_SRAM_macros=[20,20],
        full_batches=288,rows_per_batch=8,rows_per_math_group=4,tail_rows=3,
        storage_proof='all eight S16 residual statistics complete before redundant sign-byte storage reuse; S32 high16 in dead low_pv, low16 in own probability slots; even S8 in own dead slots until odd result commits packed word; tail uses legacy path',
        arithmetic_proof='same residual SAT16 and existing RNE pipes; pass1 beta-add assigned low32 modulo2^32 exactly as original; per-row lane order and tags preserved',
        production_registers_added=0,new_arithmetic_lanes=0,private_read_write_change_case0=[0,0],shared_read_write_change_case0=[1685,0],
        target_tasks_s=100,target_cycles_at_assumed150MHz=1500000,
        compute_only_ratio_at_assumed150MHz=150000000/1469112,
        conditional_complete_tasks_s=150000000/2256860,frequency_signed_off=False,goal100_achieved=False,
        compute_only_ratio_is_not_complete_task_throughput=True,
        physical_risk='four-lane operand and halfword selectors; four simultaneous SRAM writes; existing deeper iterative divider inherited; area, timing, activity and peak power need same-candidate server measurements',
        area_mm2=None,power_mW=None,energy_uJ=None,inventory_SHA256=sha(base/'inventory/summary.json'))
    out.mkdir(parents=True);(out/'summary.json').write_text(json.dumps(r,indent=2)+'\n')
    print('PASS LN4 DELTA',r['compute_cycles_saved'],r['task_cycles_saved'])
