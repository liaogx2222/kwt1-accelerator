"""Same-task target arithmetic and hard bounds; no unmeasured PPA forecasts."""
import argparse
import json
import math
from pathlib import Path
from local_tools import ROOT, sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    out=args.output.resolve();assert not out.exists(),'New analysis directory';out.mkdir(parents=True)
    hz=150000000;target=240;budget=hz//target;assert hz%target==0
    layers,n,d,ff=12,99,64,256
    dense=layers*n*(4*d*d+2*d*ff);qk=layers*n*n*d;pv=qk
    byte_macs=dense+qk+2*pv;mathematical_macs=dense+qk+pv
    dense_rq=layers*n*(4*d+ff+d);pv_rq=layers*n*d
    baseline=json.loads((ROOT/'testdata/competition_metrics_20261104/metrics.json').read_text())
    ref=baseline['software_reference'];cycles=ref['measured_task_cycles'][0]
    packet=757312;payload=packet+2*6336;wait=packet//4*6+13*1024;assert wait==1149280
    tiles=[]
    for rows,cols in [(8,8),(16,8),(8,16),(16,16)]:
        qr=math.ceil(n/rows);kc=math.ceil(n/cols)
        dense_cycles=qr*(4*math.ceil(d/cols)*d+math.ceil(ff/cols)*d+math.ceil(d/cols)*ff)
        qk_cycles=qr*kc*d
        pv_cycles=qr*math.ceil(d/cols)*n*2
        total=layers*(dense_cycles+qk_cycles+pv_cycles)
        tiles.append(dict(rows=rows,columns=cols,PEs=rows*cols,dense_MAC_issue_cycles=layers*dense_cycles,
            QK_MAC_issue_cycles=layers*qk_cycles,PV_two_pass_MAC_issue_cycles=layers*pv_cycles,
            total_MAC_issue_cycles=total,remaining_of_625k_for_everything_else=budget-total,
            scope='ideal issue count for generalized existing tiled loop; no memory/arithmetic/IO/stall costs or mapped design'))
    assert tiles[0]['total_MAC_issue_cycles']==1335360 and byte_macs==80974080
    report=dict(target_origin='User-confirmed same competition complete 12-layer task; new design benchmark, not independently published result',
        targets=dict(accuracy_drop_pp=0.1,throughput_tasks_per_second=240,SoC_power_mW=18,
                     energy_uJ_per_task=75,counted_area_including_private_SRAM_mm2=0.27),
        clock_assumption_Hz=hz,cycles_per_task_budget=budget,latency_ms=1000/target,
        power_energy_consistency=dict(power_mW_div_tasks_per_second_times_1000=18/240*1000,consistent=True),
        accuracy=dict(validation_samples=4445,FP_correct=4348,current_integer_correct=4338,
            required_integer_correct=4348-math.floor(4445*0.1/100),net_additional_correct_needed=6,
            official_600_allowed_net_correct_loss=math.floor(600*0.1/100),
            official_600_statement='at most 0 fewer correct predictions than same-head FP at <=0.1pp; no claim of generalization'),
        current=dict(task_cycles=cycles,core_compute_cycles=5058532,MAC_issue_cycles=1335360,
            provider_wait_cycles=wait,whole_task_speedup_required=cycles/budget,
            core_compute_speedup_required=5058532/budget,
            reference_45nm_standard_cell_area_mm2=0.475862296,SRAM_area_unknown=True,
            area_ratio_to_0p27_before_macros=0.475862296/0.27,
            area_comparison_scope='different/unknown target technology and private macro; numeric gap is not a same-library PPA comparison'),
        workload=dict(dense_MACs=dense,QK_MACs=qk,PV_U16xS8_MACs=pv,
            mathematical_MACs=mathematical_macs,byte_MACs_with_current_PV_two_pass=byte_macs,
            ideal_byte_MACs_per_cycle_required=byte_macs/budget,
            minimum_8bit_PEs_at_100percent_utilization=math.ceil(byte_macs/budget),
            ideal_64PE_issue_lower_bound=math.ceil(byte_macs/64),
            one_pass_U16_PV_64PE_lower_bound=math.ceil(mathematical_macs/64),
            Dense_requant_outputs=dense_rq,Dense_plus_PV_requant_outputs=dense_rq+pv_rq,
            one_shared_RNE_II1_cannot_meet_target_even_for_Dense_alone=dense_rq>budget,
            required_mean_Dense_RQ_results_per_cycle=dense_rq/budget,
            note='Dense requant outputs cannot be removed while preserving v1 materialized quantization points; other LN/Softmax/residual arithmetic not yet added to this lower bound'),
        data_supply=dict(parameter_packet_bytes=packet,total_input_parameter_output_payload_bytes=payload,
            reference_supply_MBps=100,reference_packet_latency_cycles=1024,
            parameter_only_required_MBps_at_240=packet*target/1e6,
            all_payload_required_MBps_at_240=payload*target/1e6,
            maximum_tasks_per_second_at_current_provider_even_with_zero_compute=hz/wait,
            minimum_supplier_MBps_with_13_latency_gaps=packet/(budget/hz-13*1024/hz)/1e6,
            scope='source ingress payload only; CPU staging rereads, MMIO, code, responses and topology contention add traffic; overlapping cannot exceed steady-state source throughput'),
        tile_issue_experiments=tiles,
        area_and_energy=dict(fixed_reference_cells_exclude_20_macros=True,
            allowed_energy_uJ_per_task=75,allowed_energy_pJ_per_byte_MAC_if_whole_SoC_budget_assigned_to_MACs=75e6/byte_macs,
            scope='energy ratio is budget only; not a MAC-cell energy measurement and leaves no allowance for CPU/SRAM/control'),
        architecture_conclusion='64PE, one shared II1 requant lane and 100MB/s ingress each independently prevent 240task/s; retain v1 as functional control, examine new compute/nonlinear/memory/supply architecture before implementation',
        candidates_not_approved=['16x16 issue-only candidate needs full fused nonlinear schedule, banking, state/lifetimes and mapped area/power',
            'at least two or equivalent vectorized requant outputs per cycle, with complete LN/Softmax workload accounting',
            'higher effective source bandwidth / legal transport integration, measured CPU and bus cost; DMA alone cannot fix compute lower bounds'],
        target_met=False,actual_new_RTL=False,actual_power_measured=False)
    (out/'analysis.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),ROOT/'testdata/competition_metrics_20261104/metrics.json',ROOT/'rtl/v2/kwt_layer_banked.sv',ROOT/'rtl/v2/kwt_math.sv']
    (out/'source_bindings.json').write_text(json.dumps({path.relative_to(ROOT).as_posix():sha(path) for path in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({path.name:sha(path) for path in out.iterdir() if path.is_file()},indent=2))
    print(json.dumps(dict(cycles_budget=budget,MACs=byte_macs,Dense_RQ=dense_rq,tiles=tiles,supply=report['data_supply']),indent=2))


if __name__=='__main__':main()
