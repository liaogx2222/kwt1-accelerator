"""Unified frozen-profile reproduction and independent evidence checks.

python scripts/run_r1r2_evidence.py --stage all --output testdata/r1r2/release
Individual stages may run concurrently after snapshot, in different subfolders.
check is read-only against artifacts except writing verification/manifest.
"""
import argparse
import gzip
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from integer_model.register_contract import static_layout,budget


def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def write(path,obj):path.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def source_paths():
    files=list((ROOT/'integer_model').glob('*.py'))+list((ROOT/'rtl/micro').glob('*.sv'))
    files += [ROOT/'scripts'/s for s in ['validate_kwt1_r1.py','validate_kwt1_r2.py','audit_r1_events.py',
              'validate_arithmetic_rtl.py','run_r1r2_evidence.py']]
    files += [ROOT/'tests/integer/test_r1_boundaries.py',ROOT/'requirements-r1r2.lock']
    return sorted(files)


def provenance(out):
    assert platform.python_version()=='3.10.9','use locked Python version'
    assert np.__version__=='1.26.2','use requirements-r1r2.lock'
    sources={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in source_paths()}
    inputs={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in [
        ROOT/'testdata/integer_v1/params/parameters.npz',ROOT/'testdata/integer_v1/params/manifest.json',
        ROOT/'testdata/integer_v1/fixture/encoder_input.npy',ROOT/'testdata/integer_v1/validation/encoder_output_int8.npy']}
    for p in sorted((ROOT/'testdata/p4a/hw_params_verified').glob('*')):
        if p.is_file():inputs[str(p.relative_to(ROOT)).replace('\\','/')]=sha(p)
    assert inputs['testdata/integer_v1/params/parameters.npz']=='4699ba38d9df1a635ff25eb379cc27521cf8b04205f2eba3f9c8d94a5d120a7a'
    tools={}
    iv=shutil.which('iverilog') or 'E:/project/FPGAcompetition/RISCV_CPU/tools/iverilog/bin/iverilog.exe'
    bindir=Path(iv).parent
    for name in ['iverilog.exe','vvp.exe']:
        tools[name]={'path':str(bindir/name),'sha256':sha(bindir/name)}
    result={'python':platform.python_version(),'numpy':np.__version__,'platform':platform.platform(),
            'sources':sources,'inputs':inputs,'tools':tools,'source_E01':'OPEN; no new historical clue, no recovery attempt'}
    target=out/'provenance.json'
    if target.exists():
        previous=read(target)
        for field in ['sources','inputs','tools']:assert previous[field]==result[field],f'{field} changed after snapshot; use a new output directory'
    else:
        write(target,result)
        for p in source_paths():
            dest=out/'source_snapshot'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    write(out/'register_layout.json',static_layout());return result


def audit_lifetimes(path):
    changes={};categories=set();intervals=0
    for line in gzip.open(path,'rt',encoding='utf-8'):
        start,end,size,name,phase=json.loads(line);assert end>=start and size>=0
        categories.add(name);intervals+=1
        if start!=end:
            changes[start]=changes.get(start,0)+size;changes[end]=changes.get(end,0)-size
    live=peak=0;peak_at=0
    for t,delta in sorted(changes.items()):
        live+=delta;assert live>=0
        if live>peak:peak,peak_at=live,t
    assert live==0
    assert 'softmax_index_buffer' in categories
    assert 'div_iterative_state' in categories
    return {'peak_bytes':peak,'peak_cycle':peak_at,'intervals':intervals,'passed':True}


def audit_all(out):
    from audit_r1_events import audit
    rows=[]
    for i in range(12):
        folder=out/'baseline'/f'layer_{i:02d}'
        events=audit(folder/'arithmetic.jsonl.gz');life=audit_lifetimes(folder/'lifetimes.jsonl.gz')
        expected=read(folder/'summary.json')['liveness']['peak_bytes'];assert life['peak_bytes']==expected
        write(folder/'independent_audit.json',{'arithmetic':events,'lifetimes':life});rows.append({'layer':i,'arithmetic':events,'lifetimes':life})
        print('independent audit',i,events['complete'],life['peak_bytes'],flush=True)
    write(out/'audits.json',rows)


def check(out):
    base=read(out/'baseline/summary.json');edge=read(out/'full_boundary/summary.json');unit=read(out/'unit/summary.json')
    assert len(base['layers'])==len(edge['layers'])==len(unit['profiles'])==12
    assert base['zero_mismatch'] and edge['zero_mismatch'] and unit['passed'] and unit['actual_retirement_fault_detected']
    assert base['budget_4096_pass'] and edge['budget_4096_pass']
    audits=read(out/'audits.json');assert len(audits)==12 and all(r['arithmetic']['passed'] and r['lifetimes']['passed'] for r in audits)
    stream=read(out/'stream/summary.json');assert len(stream['scenarios'])==5 and len(stream['negative_tests'])==8
    for s in stream['scenarios']:
        assert len(s['packets'])==13 and sum(p['cycles'] for p in s['packets'])==s['third_segment_cycles']
        for p in s['packets']:assert p['CRC_valid'] and p['accepted_beats']==p['bytes']//4 and p['FIFO_peak_entries']<=8
    packets=read(out/'packet_baseline/summary.json')['execution'];optimized=read(out/'packet_optimized/summary.json')['execution']
    assert len(packets['layers'])==len(optimized['layers'])==12 and packets['saved_golden_equal'] and optimized['saved_golden_equal']
    assert packets['output_sha256']==optimized['output_sha256'] and packets['MBps']==optimized['MBps']==100
    assert all(r['register_budget']['passed'] for r in packets['layers']+optimized['layers'])
    variants=[]
    for name in ['cache','gelu2','gelu8']:
        v=read(out/name/'summary.json');assert len(v['layers'])==2 and v['zero_mismatch'] and v['budget_4096_pass']
        for r in v['layers']:
            i=r['layer'];assert np.array_equal(np.load(out/name/f'layer_{i:02d}/output.npy'),np.load(out/'baseline'/f'layer_{i:02d}/output.npy'))
        variants.append({'name':name,'layers':[{k:r[k] for k in ['layer','core_cycles','coefficient_read_bytes','bank_reads','bank_writes','register_budget']} for r in v['layers']]})
    rtl=read(out/'rtl/summary.json');assert rtl['passed'] and rtl['vectors']==1818
    result={'passed':True,'baseline_layers':12,'full_boundary_layers':12,'audited_layers':12,
            'baseline_core_cycles_per_layer':base['layers'][0]['core_cycles'],
            'baseline_register_peak_bytes':base['register_total_peak_bytes'],
            'optimized_register_peak_bytes':max(r['register_budget']['reserved_total_peak_bytes'] for r in optimized['layers']),
            'packet_baseline_cycles':packets['total_cycles'],'packet_optimized_cycles':optimized['total_cycles'],
            'baseline_ms_assumed_150MHz':packets['latency_ms_at_assumed_150MHz'],
            'optimized_ms_assumed_150MHz':optimized['latency_ms_at_assumed_150MHz'],
            'variants':variants,'RTL_vectors':rtl['vectors'],'SOURCE_E01':'OPEN','PPA_150MHz':'not verified'}
    write(out/'verification.json',result)
    hashes={str(p.relative_to(out)).replace('\\','/'):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='evidence_manifest.json' and p.suffix!='.log'}
    write(out/'evidence_manifest.json',hashes);print(json.dumps(result,indent=2,ensure_ascii=False))


def main():
    stages=['snapshot','unit','baseline','full_boundary','stream','packet_baseline','cache','gelu2','gelu8','packet_optimized','rtl','audit','check']
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,default=ROOT/'testdata/r1r2/release')
    ap.add_argument('--stage',choices=stages+['all'],default='all');a=ap.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
    provenance(a.output)
    for stage in stages if a.stage=='all' else [a.stage]:
        folder=a.output/stage
        if stage=='snapshot':continue
        if stage=='audit':audit_all(a.output);continue
        if stage=='check':check(a.output);continue
        if stage=='unit':args=['tests/integer/test_r1_boundaries.py','--output',str(folder)]
        elif stage in ['baseline','full_boundary','cache','gelu2','gelu8']:
            args=['scripts/validate_kwt1_r1.py','--output',str(folder)]
            if stage=='full_boundary':args+=['--boundary-input','--no-traces','--lifetime-only']
            if stage in ['cache','gelu2','gelu8']:args+=['--layers','0,11','--variant','coefficient_cache' if stage=='cache' else stage,'--no-traces']
        elif stage in ['stream','packet_baseline','packet_optimized']:
            args=['scripts/validate_kwt1_r2.py','--output',str(folder)]
            if stage!='stream':args+=['--execute','--execution-only']
            if stage=='packet_optimized':args+=['--optimized']
        else:args=['scripts/validate_arithmetic_rtl.py','--output',str(folder)]
        print('RUN',stage,flush=True)
        subprocess.run([sys.executable,*args],cwd=ROOT,check=True)


if __name__=='__main__':main()
