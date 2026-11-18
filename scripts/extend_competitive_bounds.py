"""Cross-resource lower bounds, actual loader evidence and unimplemented proposal."""
import argparse
import json
import math
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();out=args.output.resolve()
    assert not out.exists(),'New review output';out.mkdir(parents=True)
    analysis=ROOT/'testdata/competitive_targets_20261104';loader=ROOT/'testdata/competitive_targets_loader_20261104'
    for folder in [analysis,loader]:
        for name,digest in json.loads((folder/'manifest.json').read_text()).items():assert sha(folder/name)==digest,name
        for name,digest in json.loads((folder/'source_bindings.json').read_text()).items():assert sha(ROOT/name)==digest,name
    prior=json.loads((analysis/'analysis.json').read_text());actual=json.loads((loader/'verification.json').read_text());assert actual['passed'] and actual['total_loader_cycles']==526906
    n,d,layers=99,64,12;features=n*d*2*layers;scores=n*n*layers
    operations=dict(Dense_RQ=684288,Softmax_score_RQ=scores,Softmax_e_times_reciprocal=scores,
        Softmax_probability_times_denominator=scores,PV_RQ=76032,
        LN_residual_two_products=2*features,LN_square=features,LN_normalize_gamma_output_three_pass=3*features)
    mul=sum(operations.values());assert mul==2025540
    rounds=operations['Dense_RQ']+scores+operations['PV_RQ']+features+3*features;assert rounds==1486188
    budget=625000
    report=dict(targets=prior['targets'],cycles_per_task=budget,base_analysis=prior,actual_loader=actual,
        shared_arithmetic_lower_bounds=dict(multiply_requests_by_existing_state=operations,
            scalar_multiply_requests_excluding_standalone_M_REQ=mul,
            scalar_RNE_results_excluding_standalone_M_REQ=rounds,
            mean_multiply_issues_per_cycle_needed=mul/budget,mean_RNE_results_per_cycle_needed=rounds/budget,
            minimum_scalar_mul_issue_equivalents_at_II1=math.ceil(mul/budget),
            minimum_scalar_RNE_issue_equivalents_at_II1=math.ceil(rounds/budget),
            LN_sqrt_operations=2*n*layers,LN_and_Softmax_divide_operations=3*n*layers,
            existing_single_iterative_unit_service_cycles=2*n*layers*32+3*n*layers*64,
            scope='v1 quantization points and arithmetic graph; overlap cannot exceed total issue capacity. Narrow/vector/fused implementations may reorganize the graph but must prove equal results and preserve rounding.'),
        MAC_and_nonoverlap_loader_floor=dict(current_8x8=1335360+526906,
            hypothetical_16x16_issue_only=362208+526906,
            hardware_16x16_exists=False,full_candidate_cycles_measured=False,
            required_changes=['loader and compute overlap with conflict-free bank/ownership scheduling or a faster loader',
                'rework same-bank two-halfword writes/word layout, pipelining and CRC acceptance without loss',
                'avoid reading/writing current active weight data during next-tile prefetch']),
        area_storage_constraints=dict(target_total_mm2=0.27,current_private_bytes=163840,current_private_bits=1310720,
            maximum_average_macro_area_um2_per_bit_if_zero_logic=0.27e6/1310720,
            current_reference_standard_cell_area_mm2=0.475862296,
            conclusion='160KiB allocation and logic must be reconsidered against actual public macro data; a capacity number is not a measured macro area'),
        unimplemented_architecture_proposal=dict(
            compute='examine 16x16 output-stationary tiles plus separate narrow/vector RQ and fused LN/Softmax streams, not four copies of current 64x64 math unit',
            weight_residency='shared SRAM retains current layer packet; private weight tile up to 256x16 signed8 =4096B, reuse across query/token groups',
            memory_starting_budget=dict(operand_macros='16 x 1024x16 =32KiB',scratch_macros='4 x 4096x16 =32KiB',
                total_private_bytes=65536,macro_count=20,port_bytes_per_cycle_nominal=40,
                required_16x16_operand_bytes_per_issue=32,
                validity='proposal only; live tensor capacity, address mapping, same-bank collisions, prefetch and writeback not yet proven; S16-input candidate requires new audit'),
            accumulator_state=dict(current_bytes=64*4,proposed_bytes=256*4,increment_bytes=768,
                old_declared_register_bytes=3808,old_plus_increment_bytes=4576,
                internal_4KiB_budget_would_be_exceeded_without_other_reuse=True),
            external_payload_MBps_floor=184.79616,
            software='E203 retains ownership, descriptor/error/timeout/abort/reset control; investigate legal platform block transport, not CPU numerical computation',
            first_acceptance='executable value-driven tile/bank/arithmetic schedule and same integer golden, complete IO ledger, actual mapped area and activity. No new RTL approval or benchmark success inferred.'),
        all_targets_met=False,new_RTL_implemented=False,new_area_or_energy_measured=False)
    (out/'analysis.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),analysis/'analysis.json',loader/'verification.json',ROOT/'rtl/v2/kwt_layer_banked.sv',ROOT/'rtl/v2/kwt_packet_loader.sv',ROOT/'rtl/v2/kwt1_accel.sv']
    (out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in sources},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps(dict(multiply_lower_bound=mul,RNE_lower_bound=rounds,loader_MAC16_floor=889114,proposal_only=True),indent=2))


if __name__=='__main__':main()
