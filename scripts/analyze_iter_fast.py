"""Source-bound structural cost, recurrence latencies and measured FSM delta."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REV='c90b1e2a8be95ec1df2e2d73cf832239b684cde1';PARENT='8901e14ba4028d0711f25e0cfa598c6abe13835b'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--round',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();base=a.round.resolve();assert not out.exists();out.mkdir(parents=True)
    oldcore=subprocess.check_output(['git','show',PARENT+':rtl/softmax_stream/kwt_layer_banked.sv'],cwd=ROOT)
    core=subprocess.check_output(['git','show',REV+':rtl/iter_fast/kwt_layer_banked.sv'],cwd=ROOT);unit=subprocess.check_output(['git','show',REV+':rtl/iter_fast/kwt_iterative.sv'],cwd=ROOT)
    assert core==oldcore.replace(b'.SHORT_CONST_DIV(1),.RADIX4_CONST(1)',b'.SHORT_CONST_DIV(1),.RADIX4_CONST(1),.RADIX16_CONST(1),.DOUBLE_SQRT(1)')
    m=json.loads((base/'candidate/project/source_manifest.json').read_text());assert m['files']['rtl/v2/kwt_layer_banked.sv']==hashlib.sha256(core).hexdigest() and m['files']['rtl/v2/kwt_iterative.sv']==hashlib.sha256(unit).hexdigest()
    inv=json.loads((base/'inventory/summary.json').read_text());oldinv=json.loads((ROOT/'evidence/softmax_stream_20261115/inventory/summary.json').read_text())
    bits=lambda j:sum(s['bits'] for s in j['signals'] if s['module'].startswith('kwt_iterative__'))
    assert bits(oldinv)==526 and bits(inv)==463 and inv['declared_register_bits']==32949
    log=(base/'candidate/cold0/case_00/run.log').read_text();phase={int(k):int(v) for k,v in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',log)};assert phase[93]==78408
    # 2 LN *12*99: sqrt32->16 and constant2^40 div21->11.
    # 12*99 Softmax rows: constant2^47 div24->12, same quotient+remainder.
    save=2*12*99*(16+10)+12*99*12;assert save==76032
    oldbound=json.loads((ROOT/'evidence/softmax_stream_20261115/ceiling/ceiling.json').read_text());assert oldbound['necessary_serial_cycles']==1260276
    r=dict(passed=True,parent_commit=PARENT,production_commit=REV,files={n:m['files'][n] for n in ['rtl/v2/kwt_layer_banked.sv','rtl/v2/kwt_iterative.sv']},
        core_only_change='enable two exact iterative parameters',declared_unit_bits=[526,463],declared_accelerator_bits=[33012,32949],
        logical_stages=dict(division_before='2x65-bit restoring',division_after='4x65-bit restoring',sqrt_before='1x66-bit',sqrt_after='2x34-bit plus request selection'),
        mapped_area_or_delay_inferred_from_stage_count=False,latencies=dict(div40=[21,11],div47=[24,12],sqrt64=[32,16],generic_div64=[64,64],zero_divisor=[1,1]),
        sqrt_width_proof='after k digits: root=floor(sqrt(prefix2k)), rem=prefix-root^2<=2root; before last digit root<2^31,rem<2^32; shifted rem<2^34; final root32/rem33 fit',
        I_WAIT_cycles=[154440,78408],compute_cycles=[1644792,1568760],predicted_and_measured_compute_saved=save,
        necessary_serial_subset_cycles=oldbound['necessary_serial_cycles']-save,target_tasks_s=100,target_cycles_at_assumed150MHz=1500000,
        observed_compute_only_upper_at_assumed150MHz=150000000/1568760,frequency_signed_off=False,goal100_achieved=False,
        physical_risk='two additional65-bit restoring stages lengthen critical path; narrow sqrt reduces state but comparator/mux timing must be measured',
        area_mm2=None,power_mW=None,energy_uJ=None,old_inventory_SHA256=sha(ROOT/'evidence/softmax_stream_20261115/inventory/summary.json'),inventory_SHA256=sha(base/'inventory/summary.json'))
    (out/'summary.json').write_text(json.dumps(r,indent=2)+'\n');print('ITER COST/DELTA',r['declared_unit_bits'],save,r['observed_compute_only_upper_at_assumed150MHz'])
