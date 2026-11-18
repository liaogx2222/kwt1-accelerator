"""Conservative cycle lower bound for the frozen S16 core's serial FSM.

This is source-bound arithmetic analysis, not synthesis or a new simulation.
The bound applies when the computational FSM/data path remain unchanged;
it does not prove that every possible 8x16 architecture cannot reach120task/s.
"""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REV='595724b88858b142a407f6a5c4761945252d523b'

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project',type=Path);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();project=a.project.resolve() if a.project else None;out=a.output.resolve()
    assert not out.exists(),'preserve prior calculation';out.mkdir(parents=True)
    sha=lambda b:hashlib.sha256(b).hexdigest()
    bound={};source={}
    for n in ['rtl/v2/kwt_layer_banked.sv','rtl/v2/kwt_mac_array.sv','rtl/v2/kwt_math.sv',
              'rtl/v2/kwt_iterative.sv','rtl/v2/kwt1_accel.sv','rtl/v2/generated/kwt_profile.svh']:
        original=subprocess.check_output(['git','show',REV+':'+n],cwd=ROOT).replace(b'\r\n',b'\n')
        if project:assert (project/n).read_bytes().replace(b'\r\n',b'\n')==original,'not the frozen arithmetic '+n
        bound[n]=sha(original);source[n]=original
    layer=source['rtl/v2/kwt_layer_banked.sv'].decode()
    for fragment in ['localparam ROWS=8','if(red==kdim-1)','if(red==63)','if(red==98)',
                     'state<=D_RQ','state<=Q_STORE','state<=SM_RQ','state<=N_RES',
                     'else norm_pass<=norm_pass+1','rows==3?64:128']:
        assert fragment in layer,'review required: '+fragment
    L,T,R,C,V=12,99,8,64,4
    blocks=(T+R-1)//R;full=T//R;tail=T%R
    assert (blocks,full,tail)==(13,12,3)
    # Six dense operators: Q,K,V,O each64x64; FC1 64x256; FC2 256x64.
    dense_MAC=L*blocks*(4*4*64+16*64+4*256)
    qk_MAC=L*blocks*((T+15)//16)*64
    pv_MAC=L*blocks*4*2*T # Existing FSM has two unsigned8-bit probability planes.
    # Each full dense tile takes32 four-lane issue groups. For a3-row tail,
    # V takes12 groups, the32non-V output tiles take16 three-lane groups.
    dense_RQ=L*(36*full*32+4*12+32*16)
    phase=[
        dict(states='D_MAC + Q_MAC + P_MAC',cycles=dense_MAC+qk_MAC+pv_MAC,
             derivation=f'dense{dense_MAC} + QK{qk_MAC} + PV(two planes){pv_MAC}'),
        dict(states='D_RQ',cycles=dense_RQ,derivation='12*(36*12*32 + 4*12 + 32*16); ignore all pipeline flush latency'),
        dict(states='Q_STORE',cycles=L*((full*R+tail)*16)*7,derivation='12*(12*8+3)*16*7; existing FSM visits padded key columns'),
        dict(states='S_LOAD + S_CAPTURE',cycles=L*T*(1+T),derivation='12*99*(1+99); synchronous score-load states'),
        dict(states='SM_RQ',cycles=L*T*T,derivation='12*99*99; only lane0 issues score RQ/one EXP address per cycle'),
        dict(states='SM_ER + SM_QD',cycles=2*L*T*((T+V-1)//V),derivation='2*12*99*ceil(99/4); ignore flush latency'),
        dict(states='P_RQ',cycles=L*4*(full*(R*16//V)+(tail*16//V)),derivation='12*4*(12*32+12); ignore flush latency'),
        dict(states='N_LOAD_A + N_LOAD_B',cycles=2*L*2*((T+1)//2)*C,derivation='2 LN*12 layers*50 paired row loads*64 channels*2 states'),
        dict(states='N_RES',cycles=2*L*T*(2*C//V),derivation='2*12*99*128/4; two exact products per residual before one RNE'),
        dict(states='N_SQUARE',cycles=2*L*T*(C//V),derivation='2*12*99*64/4; ignore flush latency'),
        dict(states='N_PASS',cycles=2*L*T*3*(C//V),derivation='2*12*99*3*64/4; three existing normalization passes')]
    header=layer[:layer.index('reg [7:0] state')]
    state_values={n:int(v) for n,v in re.findall(r'\b([A-Z][A-Z0-9_]*)\s*=\s*(\d+)',header)}
    counted_states=[n.strip() for group in phase for n in group['states'].split('+')]
    assert len(counted_states)==len(set(counted_states))
    assert len({state_values[n] for n in counted_states})==len(counted_states),'overlapping FSM state values'
    assert 'else case(state)' in layer and 'for(ml=0;ml<4;ml=ml+1)' in layer
    lower=sum(p['cycles'] for p in phase);frequency=150000000;target=120
    budget=frequency//target
    assert lower==1674852 and lower>budget
    # All these states are distinct branches of one FSM. They cannot overlap
    # merely by speeding up its CPU/DMA supply. Omitted states only add cycles.
    mandatory_bus_words=2*(189328+3168)+1584
    result=dict(arithmetic_revision=REV,source_parent='2cf2dfa',source_canonical_sha256=bound,
        source_binding_mode='snapshot_and_frozen_Git' if project else 'frozen_Git_only',
        analysis_only=True,new_RTL_simulation_claimed=False,RTL_changed=False,
        frequency_Hz=frequency,frequency_signed_off_for_new_SYSBUS=False,target_tasks_per_second=target,
        target_cycle_budget=budget,nonoverlapping_phase_lower_bounds=phase,
        counted_FSM_state_values={n:state_values[n] for n in counted_states},
        frozen_FSM_compute_cycles_lower_bound=lower,
        ideal_throughput_upper_bound_with_frozen_FSM=float(Fraction(frequency,lower)),
        compute_subset_over_budget_cycles=lower-budget,
        omitted_costs=['all loading/CPU/bus waiting','LN DIV and SQRT','GELU','coefficient loading',
                       'most result stores/copies','math flush bubbles','task start/final output/ACK'],
        mandatory_bus_payload_words_lower_bound=mandatory_bus_words,
        ideal_bus_only_at_one_command_per_cycle_tasks_per_second=float(Fraction(frequency,mandatory_bus_words)),
        ideal_bus_bound_not_actual_original_bus_bandwidth=True,
        applies_to='frozen595724b computational FSM unchanged; arbitrary CPU/DMA supply improvement',
        does_not_prove='impossibility for a redesigned compute schedule, extra parallel engines or every8x16 implementation',
        conclusion='120task/s cannot be reached at150MHz by bus/CPU-only tuning of this frozen core',
        full_SOC_area_mm2=None,power_mW=None,energy_uJ=None)
    (out/'ceiling.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['target_cycle_budget','frozen_FSM_compute_cycles_lower_bound',
        'ideal_throughput_upper_bound_with_frozen_FSM','compute_subset_over_budget_cycles',
        'mandatory_bus_payload_words_lower_bound','ideal_bus_only_at_one_command_per_cycle_tasks_per_second','conclusion']},indent=2))

if __name__=='__main__':main()
