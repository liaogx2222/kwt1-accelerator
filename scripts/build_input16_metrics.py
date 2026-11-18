"""Same-configuration full area reference and actual E203 windows; scope power."""
import argparse
import json
import os
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);base=ROOT/'testdata/input16_rtl_20261105';bound=[Path(__file__)];rows=[]
    def read(folder,name='verification.json'):
        p=folder/name;bound.append(p);return json.loads(p.read_text())
    policy=read(ROOT.parent/'docs/architecture','METRICS_SCOPE_AND_REPORTING_20261105.json');acc=read(ROOT/'testdata/accuracy_point1_20261104/input16_only','metrics.json');sram=read(ROOT/'testdata/full_scope_20261105/sram_cacti')['models'];activity=read(base/'trim_bank_activity')['cases']
    for name,cpu_dir,map_dir,sta_dir,geom in [('20_macro','e203','mapping_full','sta_full_simple',{'4096x16':20}),('trimmed_24_macro','trim2_e203','mapping_trim','sta_trim_simple',{'4096x16':16,'1024x16':8})]:
        cpu=read(base/cpu_dir);m=read(base/map_dir);timing=read(base/sta_dir);assert cpu['passed'] and m['complete_area_scope_included'] and timing['passed']
        seconds=cpu['total_cycles']/150000000;dynamic=0
        if name=='20_macro':
            v=sram['4096x16'];dynamic=sum(w[8]*v['read_energy_nJ']+w[9]*v['write_energy_nJ'] for w in cpu['windows'])
        else:
            for task in activity:
                for bank in task:
                    v=sram['1024x16' if bank['bank'] in [1,3,5,7] else '4096x16'];dynamic+=bank['reads']*v['read_energy_nJ']+bank['writes']*v['write_energy_nJ']
        leak=sum(n*sram[g]['leakage_mW'] for g,n in geom.items());pd=dynamic*1e-6/seconds;power=leak+pd
        private_area=sum(n*sram[g]['area_mm2'] for g,n in geom.items());assert abs(private_area+m['standard_cell_area_mm2']-m['complete_counted_area_open_reference_mm2'])<1e-12
        rows.append(dict(candidate=name,configuration='actual E203 RTL + S16-input 8x8 whole accelerator + exact ICB/MMIO and 13 CRC packets',
            throughput_tasks_per_second=None,SoC_average_power_mW=None,complete_counted_area_mm2=None,SoC_energy_uJ_per_task=None,
            full_window_reference=dict(task_cycles=cpu['task_cycles'],total_cycles=cpu['total_cycles'],assumed_clock_Hz=150000000,throughput_tasks_per_second_at_assumed_150MHz=cpu['throughput_at_assumed_150MHz'],actual_CPU_RTL_cycles=True,qualified_frequency=False,stats_tail_excluded=True),
            reference_area_full_scope=dict(total_mm2=m['complete_counted_area_open_reference_mm2'],all_new_logic_mapped_mm2=m['standard_cell_area_mm2'],private_SRAM_analytical_mm2=private_area,private_macro_counts=geom,
                includes_full_encoder_packet_MMIO_ICB=True,uses_characterized_official_macro=False,technology='Nangate45 typical plus CACTI 45nm analytic macros, not a homogeneous characterized PVT',
                fixed_platform_area_separate=dict(CPU=None,shared_512KiB_SRAM=None,fixed_bus=None)),
            private_SRAM_only_analytical_power=dict(mean_mW=power,dynamic_mW=pd,leakage_mW=leak,energy_uJ_per_task=power*seconds*1000/12,
                method='same actual B0/B1 accesses times CACTI event energy, full window standby leakage; 150MHz assumption',full_SoC_power=False),
            partial_reference_STA=dict(WNS_ns=timing['reference_reg2reg_WNS_ns'],TNS_ns=timing['reference_reg2reg_TNS_ns'],negative_endpoints=timing['negative_setup_endpoints'],scope=timing['scope']),
            missing_for_full_SoC_power=['mapped CPU and interconnect same-window activity and loads','complete mapped accelerator activity coverage','shared and private characterized SRAM power/idle/clock models'],
            missing_for_official_area=['designated mapping library and macro area data'],missing_for_official_throughput=['qualified 150MHz timing','designated competition platform and official samples']))
    assert rows[0]['full_window_reference']['task_cycles']==rows[1]['full_window_reference']['task_cycles']
    assert acc['accuracy_drop_pp']<=policy['accuracy_drop_hard_limit_pp'];reduction=rows[0]['reference_area_full_scope']['total_mm2']-rows[1]['reference_area_full_scope']['total_mm2'];assert reduction>0
    report=dict(passed=True,policy=policy,candidates=rows,reference_area_reduction_mm2=reduction,reference_area_reduction_percent=100*reduction/rows[0]['reference_area_full_scope']['total_mm2'],
        accuracy_validation_drop_pp=acc['accuracy_drop_pp'],precision_limit_pp=.1,official_600=False,full_SoC_power_measured=False,official_PPA_available=False,
        current_selection='trimmed geometry at identical actual E203 cycles, subject to real macro and complete timing/power validation',not_the_16x16_fast_model=True)
    (out/'metrics.json').write_text(json.dumps(report,indent=2));(out/'verification.json').write_text(json.dumps(dict(passed=True,scope_keys_complete=True,full_reference_area_includes_every_added_block=True,official_measurements_not_claimed=True),indent=2));(out/'source_bindings.json').write_text(json.dumps({os.path.relpath(p,ROOT).replace('\\','/'):sha(p) for p in bound},indent=2));(out/'manifest.json').write_text(json.dumps({f.name:sha(f) for f in out.iterdir() if f.is_file()},indent=2));print(json.dumps({r['candidate']:dict(throughput_ref=r['full_window_reference']['throughput_tasks_per_second_at_assumed_150MHz'],complete_open_area_ref=r['reference_area_full_scope']['total_mm2'],SRAM_only_power=r['private_SRAM_only_analytical_power']['mean_mW'],full_SoC_power=None) for r in rows},indent=2))


if __name__=='__main__':main()
