"""Parse first full-SoC reference metrics, retaining all qualification limits."""
import json
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
SCALE={'W':1.,'mW':1e-3,'uW':1e-6,'nW':1e-9,'pW':1e-12,'fW':1e-15}


def power(text,label,kind):
    match=re.search(re.escape(label)+r'\s*=\s*([-+0-9.eE]+)\s*([munpf]?W)?',text)
    assert match,'POWER_FIELD_MISSING '+label
    if match.group(2):return float(match.group(1))*SCALE[match.group(2)]
    units=re.search(kind+r' Power Units\s*=\s*([0-9.eE+-]+)\s*([munpf]?W)',text)
    assert units,'POWER_UNITS_MISSING '+kind
    return float(match.group(1))*float(units.group(1))*SCALE[units.group(2)]


def collect():
    log=(ROOT/'build/gate/cold/run.log').read_text(errors='replace')
    assert 'PASS SOC_INPUT16_GATE recovery=0' in log
    cycles=int(re.search(r'SOC_GATE_METRICS cycles=(\d+)',log).group(1))
    report=(ROOT/'build/pt/power_soc_tt.rpt').read_text(errors='replace')
    dynamic=power(report,'Total Dynamic Power','Dynamic');leakage=power(report,'Cell Leakage Power','Leakage')
    assert dynamic>=0 and leakage>=0
    with (ROOT/'build/gate/cold/task.saif').open(errors='replace') as f:header=f.read(65536)
    duration=re.search(r'\(DURATION\s+([0-9.eE+-]+)\s*\)',header)
    unit=re.search(r'\(TIMESCALE\s+([0-9.eE+-]+)\s+(s|ms|us|ns|ps|fs)\s*\)',header)
    assert duration and unit,'SAIF_WINDOW_MISSING'
    seconds=float(duration.group(1))*float(unit.group(1))*dict(s=1,ms=1e-3,us=1e-6,ns=1e-9,ps=1e-12,fs=1e-15)[unit.group(2)]
    window_ok=abs(seconds-cycles/150e6)<max(1e-9,seconds*1e-5)
    ledger={k:float(v)/1e6 for k,v in (line.split() for line in (ROOT/'build/dc/reports/area_ledger.tsv').read_text().splitlines())}
    whole_area=sum(ledger.values())
    area_text=(ROOT/'build/dc/reports/area.rpt').read_text()
    reported=float(re.search(r'Total cell area:\s+([0-9.eE+-]+)',area_text).group(1))/1e6
    assert abs(whole_area-reported)<1e-5,'AREA_LEDGER_NOT_EQUAL_FULL_DESIGN'
    scored=sum(ledger[n] for n in ['accelerator','added_shared_controller','added_interface_glue'])
    result=dict(scope='full digital reference SoC, TT post-synthesis estimate; not final timing/coverage signoff',
        RTL_revision='595724b88858b142a407f6a5c4761945252d523b',tasks=1,case=0,cycles=cycles,
        declared_operating_PVT=dict(corner='TT',voltage_V=1.1,temperature_C=25),
        throughput_at_assumed_150MHz=150e6/cycles,latency_ms_at_assumed_150MHz=cycles/150e3,
        same_window_SAIF_duration_seconds=seconds,SAIF_vs_cycle_window_matches=window_ok,
        SoC_dynamic_power_mW=dynamic*1000,SoC_leakage_power_mW=leakage*1000,
        SoC_average_power_mW=(dynamic+leakage)*1000,
        SoC_energy_uJ_per_task=(dynamic+leakage)*seconds*1e6 if window_ok else None,
        whole_SoC_cell_and_macro_area_mm2=whole_area,added_scored_area_conservative_mm2=scored,
        area_partitions_mm2=ledger,macros=dict(private=20,shared=64,ITCM=8,DTCM=8,total=100),
        clock_gating='same FPGA_SOURCE bypass reference; no power benefit assumed',
        power_includes='CPU, new NICE, interconnect/controller, ROM, TCM and all private/shared SRAM',
        excluded='analog PLL/pads and off-chip test equipment',
        precision_validation=dict(samples=4445,accuracy_percent=97.75028121484814,drop_pp=.06749156355455568,official_600=False),
        coverage_review_required=True,SRAM_library_power_review_required=True,
        interconnect_wire_model_review_required=True,
        frequency_150MHz_signed_off=False,hold_remediation='deferred by user',
        performance_twelve_task_gate_campaign_complete=False,qualification_complete=False)
    path=ROOT/'build/metrics_reference.json';assert not path.exists(),'PRESERVE_METRICS'
    path.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':collect()
