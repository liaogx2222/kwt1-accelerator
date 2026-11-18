"""Required three metrics, no incomplete sum can masquerade as scored PPA."""
import argparse
import json
import os
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);base=ROOT/'testdata/full_scope_20261105';sources=[Path(__file__)]
    def read(folder,name='verification.json'):
        path=folder/name;sources.append(path);return json.loads(path.read_text())
    policy=ROOT.parent/'docs/architecture/METRICS_SCOPE_AND_REPORTING_20261105.json';p=read(policy.parent,policy.name)
    assert p['missing_component_must_not_be_zero'] and p['same_frozen_configuration_required']
    sram=read(base/'sram_cacti');assert sram['passed'];mem=sram['models'];rows=[]
    for name,folder,mapping in [('compact','metered_single','nangate_single'),('balanced','metered_dual','nangate_shared')]:
        report=read(base/folder);mapped=read(ROOT/'testdata/resident_core_20261105'/mapping);cases=report['cases'];frequency=150000000;cycles=sum(m['cycles'] for m in cases);seconds=cycles/frequency
        assert report['passed'] and mapped['mapping_passed'];dynamic_nJ=0
        for m in cases:
            assert len(m['bank_accesses'])==20
            for bank,c in m['bank_accesses'].items():
                macro=mem['4096x16' if bank.startswith('S') else '1024x16'];dynamic_nJ+=c['r']*macro['read_energy_nJ']+c['w']*macro['write_energy_nJ']
        private_leak=sram['resident_core_private_SRAM']['analytical_standby_leakage_mW'];private_dynamic_mW=dynamic_nJ*1e-6/seconds
        private_avg=private_leak+private_dynamic_mW;private_task_uJ=private_avg*seconds*1000/len(cases)
        partitions=dict(MAC_RQ_mapped_standard_cells_mm2=mapped['standard_cell_area_mm2'],private_SRAM_CACTI_analytical_mm2=sram['resident_core_private_SRAM']['analytical_area_mm2'])
        missing_area=['all accelerator logic beyond MAC+RQ (LN/Softmax/GELU/iteration/control/register reuse)', 'new top-level bank and external interface logic', 'characterized exact SRAM macro area and binding']
        missing_power=['mapped full accelerator same-window activity', 'CPU activity and mapped power', 'interconnect activity and mapped power', 'shared SRAM model/activity', 'characterized private SRAM models/clock/idle behavior']
        rows.append(dict(candidate=name,configuration=dict(precision='S16 first input, S8 internal, W8; exact original RNE/LUT',array='16x16',vector_lanes=4,accumulator_buffers=report['accumulator_buffers'],softmax_window=128,LN_context_rows=2,private_SRAM_bytes=65536),
            throughput_tasks_per_second=None,SoC_average_power_mW=None,complete_counted_area_mm2=None,SoC_energy_uJ_per_task=None,
            missing_for_complete_throughput=['new full encoder RTL/controller', '13 packets/CRC/CPU/bus timing and cold-cache protocol', 'qualified operating frequency'],
            missing_for_complete_area=missing_area,missing_for_complete_power=missing_power,
            core_MODEL=dict(tasks=len(cases),classes=report['classes'],cycles=[m['cycles'] for m in cases],total_cycles=cycles,assumed_frequency_Hz=frequency,
                ideal_core_frequency_conversion_tasks_per_second=len(cases)/seconds,same_class0_cycles=cases[0]['cycles'],same_class0_core_frequency_conversion=frequency/cases[0]['cycles'],peak_register_bytes=max(m['total_register_peak_bytes'] for m in cases),includes='modeled input/common/parameter word transfers and final writeback',excludes='real packet/CPU/bus overhead, clock qualification'),
            component_estimates=dict(area=partitions,known_component_mixed_estimate_subtotal_mm2=sum(partitions.values()),subtotal_is_not_complete_area=True,
                private_SRAM_dynamic_mW=private_dynamic_mW,private_SRAM_standby_mW=private_leak,private_SRAM_average_mW=private_avg,private_SRAM_energy_uJ_per_task=private_task_uJ,
                SRAM_energy_scope='CACTI event-energy times actual MODEL bank transactions + full-window analytical leakage, no clock/reset/CPU/shared-SRAM/logic power',
                model_technology=sram['technology'],model_temperature_K=300,SRAM_PVT_not_characterized_with_Nangate_cells=True),
            fixed_platform_area=dict(E203_mm2=None,shared_512KiB_SRAM_mm2=None,fixed_bus_and_peripherals_mm2=None,excluded_from_scoring_budget=True)))
    accuracy=read(ROOT/'testdata/accuracy_point1_20261104/input16_only','metrics.json');assert accuracy['accuracy_drop_pp']<=.1
    result=dict(passed=True,policy=p,accuracy=dict(partition='Validation',samples=4445,drop_pp=accuracy['accuracy_drop_pp'],hard_limit_pp=.1,new_full_RTL_accuracy_proven=False,official_600=False),
        candidates=rows,complete_scoring_PPA_available=False,partial_results_never_substituted_for_required_metrics=True,
        area_limit_mm2=2.25,official_area_library='designated library and macro data still unavailable; only public references used',
        optimization='same units/precision, bounded graph windows and two-row LN scheduling',selection='retain compact/balanced; reject slower two-row Softmax fusion')
    (out/'metrics.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'verification.json').write_text(json.dumps(dict(passed=True,mandatory_metric_keys_present=True,missing_metrics_explicit_null=True,complete_area_not_partition_sum=True,candidates=2),indent=2))
    sources.append(ROOT.parent/'docs/architecture/evidence/competition_original.txt')
    (out/'source_bindings.json').write_text(json.dumps({os.path.relpath(p,ROOT).replace('\\','/'):sha(p) for p in sources},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps({r['candidate']:dict(core_MODEL_cycles=r['core_MODEL']['cycles'],core_only_frequency_conversion=r['core_MODEL']['ideal_core_frequency_conversion_tasks_per_second'],full_throughput=r['throughput_tasks_per_second'],full_power_mW=r['SoC_average_power_mW'],full_area_mm2=r['complete_counted_area_mm2']) for r in rows},indent=2))


if __name__=='__main__':main()
