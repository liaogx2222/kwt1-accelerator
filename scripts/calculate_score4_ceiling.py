"""Necessary serial work of score4, including unchanged iterative latencies."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REV='4a163f7abe5043e4cfb269f7a8d71d12291e7535'
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);ap.add_argument('--log',type=Path);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    raw=subprocess.check_output(['git','show',REV+':rtl/score4_opt/kwt_layer_banked.sv'],cwd=ROOT);s=raw.decode();assert raw==(ROOT/'rtl/score4_opt/kwt_layer_banked.sv').read_bytes()
    it_raw=subprocess.check_output(['git','show','595724b88858b142a407f6a5c4761945252d523b:rtl/v2/kwt_iterative.sv'],cwd=ROOT)
    assert hashlib.sha256(it_raw).hexdigest()=='105655baa794244aec3e8674e7a3cf05baf60fb87ea6a763a3ad6d7a5e6a53b2'
    it=it_raw.decode()
    for fragment in ['.SHORT_CONST_DIV(1),.RADIX4_CONST(1)','N_SQRT:iterate(1,h_value,0,N_INV)',
                     "iterate(0,64'h10000000000,iter_value,N_INV_RET)","SM_DIV:iterate(0,64'h800000000000",
                     'if(store_index[3:0]==valid_keys-1)','if(rows>4&&!store_index[4])store_index<=16']:
        assert fragment in s,fragment
    for fragment in ["count<=div40?6'd20:6'd23",'count<=31','if(count==1)begin state<=0;resp_valid<=1;']:
        assert fragment in it,fragment
    L,T,B,F,C,V=12,99,13,12,64,4
    phases=[('D_MAC + Q_MAC + P_MAC',610896,'dense479232 + QK69888 + PV61776'),
        ('Q_STORE',L*(F*2*T+T),'four row stores per clock, skip13 invalid key columns'),
        ('S_LOAD + S_CAPTURE',L*T*100,'one row initial read plus99captures'),
        ('SM_RQ',L*T*T,'one score/EXP issue per clock'),
        ('SM_ER + SM_QD',2*L*T*25,'two four-lane passes, no flush included'),
        ('P_RQ',L*4*(F*32+12),'PV exact requantization groups, no flush'),
        ('N_LOAD_A + N_LOAD_B',2*L*B*C*2,'two LN,13groups,64channels,two gather states'),
        ('N_RES',2*L*T*32,'two products/residual'),('N_SQUARE',2*L*T*16,'four squares/clock'),
        ('N_PASS',2*L*T*3*16,'three existing normalization passes'),
        ('I_WAIT',2*L*T*(32+21)+L*T*24,'SQRT32 and div2^40=21 per LN row; div2^47=24 per Softmax row')]
    states={n:int(v) for n,v in re.findall(r'\b([A-Z][A-Z0-9_]*)\s*=\s*(\d+)',s[:s.index('reg dq_active')])}
    names=[n.strip() for ns,_,_ in phases for n in ns.split('+')];assert len(names)==len(set(names))==len({states[n] for n in names})
    obs={int(n):int(c) for n,c in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',a.log.read_text())} if a.log else None
    rows=[]
    for ns,c,why in phases:
        r=dict(states=ns,cycles=c,derivation=why)
        if obs is not None:r['observed']=sum(obs[states[n.strip()]] for n in ns.split('+'));assert r['observed']>=c
        rows.append(r)
    lower=sum(c for _,c,_ in phases);assert lower==1377888
    r=dict(source_commit=REV,source_SHA256=hashlib.sha256(raw).hexdigest(),iterative_source_commit='595724b88858b142a407f6a5c4761945252d523b',iterative_SHA256=hashlib.sha256(it_raw).hexdigest(),
        analysis_only=True,necessary_serial_cycles=lower,phases=rows,frequency_assumed_Hz=150000000,frequency_signed_off=False,
        target120_budget_cycles=1250000,ideal_upper_tasks_s_for_this_schedule=150000000/lower,
        applies_to='successful full12-layer error-free task of current score4 FSM; unlimited ideal supply',
        notes='I_WAIT includes one response-visible consumer edge; zero-divisor error paths cannot complete a successful task. Previous Dense bound omitted I_WAIT; upper bounds of different counted subsets are not performance comparisons.',
        omitted=['all DenseRQ including overlap','many coefficient fetch/copy/store states','all source/CPU/bus waiting','GELU','flush bubbles'],
        arbitrary_rearchitected_8x16_impossibility_proven=False,goal120_achieved=False)
    (out/'ceiling.json').write_text(json.dumps(r,indent=2)+'\n');print(lower,r['ideal_upper_tasks_s_for_this_schedule'])
