"""Source-bound necessary cycles, excluding all overlapped Dense RQ work."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REV='40d5323'
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--log',type=Path);a=ap.parse_args()
    out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    raw=subprocess.check_output(['git','show',REV+':rtl/dense_overlap/kwt_layer_banked.sv'],cwd=ROOT)
    assert raw==(ROOT/'rtl/dense_overlap/kwt_layer_banked.sv').read_bytes();s=raw.decode()
    for fragment in ['localparam ROWS=8','if(red==kdim-1)','if(red==63)','if(red==98)',
                     'if(dq_live)output_limit=dq_tail?64:128','N_LOAD_FIRST:state<=N_LOAD_A;',
                     'else norm_pass<=norm_pass+1','if(ch==63)begin sent<=0;received<=0;state<=N_RES;end']:
        assert fragment in s,fragment
    L,T,R,C,V=12,99,8,64,4;blocks=(T+R-1)//R;full=T//R;tail=T%R
    phases=[
        ('D_MAC + Q_MAC + P_MAC',L*blocks*(4*4*64+16*64+4*256)+L*blocks*7*64+L*blocks*4*T,'dense + QK + one-pass PV MAC'),
        ('Q_STORE',L*T*16*7,'existing padded 16-column score retirement'),
        ('S_LOAD + S_CAPTURE',L*T*(1+T),'one initial state plus99 synchronous score captures'),
        ('SM_RQ',L*T*T,'one score requantization / EXP lookup per cycle'),
        ('SM_ER + SM_QD',2*L*T*((T+V-1)//V),'two four-lane passes; ignore pipeline flush'),
        ('P_RQ',L*4*(full*(R*16//V)+(tail*16//V)),'PV result groups; ignore flush'),
        ('N_LOAD_A + N_LOAD_B',2*L*blocks*C*2,'two LN stages,13 gathered batches,64 channels,two states'),
        ('N_RES',2*L*T*(2*C//V),'two products per residual before RNE'),
        ('N_SQUARE',2*L*T*(C//V),'four lanes; ignore flush'),
        ('N_PASS',2*L*T*3*(C//V),'three four-lane normalization passes; ignore flush')]
    states={n:int(v) for n,v in re.findall(r'\b([A-Z][A-Z0-9_]*)\s*=\s*(\d+)',s[:s.index('reg dq_active')])}
    names=[n.strip() for ns,_,_ in phases for n in ns.split('+')]
    assert len(names)==len(set(names))==len({states[n] for n in names})
    rows=[]
    observed={int(i):int(c) for i,c in re.findall(r'LOCAL_PHASE state=(\d+) cycles=(\d+)',a.log.read_text())} if a.log else None
    for ns,c,why in phases:
        r=dict(states=ns,cycles=c,derivation=why)
        if observed is not None:
            r['observed']=sum(observed[states[n.strip()]] for n in ns.split('+'));assert r['observed']>=c
        rows.append(r)
    lower=sum(c for _,c,_ in phases);assert lower==1326804
    result=dict(analysis_only=True,source_commit=REV,source_SHA256=hashlib.sha256(raw).hexdigest(),
        counted_distinct_FSM_states={n:states[n] for n in names},necessary_serial_cycles=lower,phases=rows,
        omitted=['all Dense RQ, including work overlapping MAC','Dense snapshots/waits','LN DIV/SQRT','GELU',
                 'coefficient fetch','most stores/copies','all CPU/source/bus/loading wait','flush bubbles','final write ACK'],
        frequency_Hz_assumed=150000000,frequency_signed_off=False,target120_cycle_budget=1250000,
        ideal_upper_tasks_s_for_this_compute_schedule=150000000/lower,
        scope='current Dense-overlap FSM; unlimited ideal supply cannot reach120 at150MHz',
        arbitrary_redesigned_8x16_impossibility_proven=False,physical_PPA_claimed=False)
    if a.log:result['dynamic_crosscheck_log_SHA256']=hashlib.sha256(a.log.read_bytes()).hexdigest()
    (out/'ceiling.json').write_text(json.dumps(result,indent=2)+'\n');print(lower,result['ideal_upper_tasks_s_for_this_compute_schedule'])
