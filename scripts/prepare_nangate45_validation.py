"""Bind actual mapped inputs and enumerate pending STA coverage, no timing claim."""
import argparse,collections,json,re,shutil
from pathlib import Path
from local_tools import ROOT,sha

def read(p):return json.loads(p.read_text())
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists(),'Use new output';out.mkdir(parents=True)
    mapped=ROOT/'testdata/nangate45_reference/native_compat_20261104';math=ROOT/'testdata/nangate45_reference/math_linux_20261104'
    for folder in [mapped,math]:
        for name,digest in read(folder/'manifest.json').items():assert sha(folder/name)==digest,name
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    library=read(ROOT/'third_party/nangate45_reference/provenance.json')
    for name,entry in library['files'].items():assert sha(lib.parent.parent/name)==entry['sha256'],name
    result=read(mapped/'summary.json');assert result['mapping_passed']
    for name,digest in result['generic_source_manifest'].items():assert sha(ROOT/name)==digest,name
    net=read(mapped/'mapped.json')['modules']['kwt1_mmio'];counts=collections.Counter(c['type'] for c in net['cells'].values())
    macros={name:dict(type=c['type'],pins=c['connections'],directions=c['port_directions']) for name,c in net['cells'].items() if c['type']=='kwt_tech_sram_4096x16'}
    assert len(macros)==20 and sum(counts.values())==310025
    pins={p['direction'] for p in net['ports'].values()};assert pins=={'input','output'}
    gaps=[]
    for name,port in net['ports'].items():
        if name=='clk':continue
        gaps.append(dict(port=name,direction=port['direction'],width=len(port['bits']),missing='reset assertion/deassertion recovery/removal/source policy' if name=='rst_n' else 'sourced input delay and drive' if port['direction']=='input' else 'sourced output delay and load'))
    assert len(gaps)==15
    text=lib.read_text();units={name:re.search(pattern,text).group(1) for name,pattern in [('time',r'time_unit\s*:\s*"([^"]+)"'),('voltage',r'voltage_unit\s*:\s*"([^"]+)"')]}
    (out/'clock_only_reference.sdc').write_text('# Preparation only; deliberately incomplete I/O/reset/macro timing.\ncreate_clock -name accel_clk -period 6.666667 [get_ports clk]\n# No zero I/O delays, blanket false paths or guessed uncertainty are inserted.\n')
    sources=[mapped/'mapped.v',mapped/'mapped.json',lib,math/'functional_cells.v',ROOT/'rtl/integration/tech_sram_model.sv',ROOT/'rtl/integration/sim_gate.cpp',ROOT/'rtl/v2/driver/kwt1.c',Path(__file__)]
    bindings={p.relative_to(ROOT).as_posix():sha(p) for p in sources}
    report=dict(preparation_checks_passed=True,top='kwt1_mmio',standard_cells=310005,SRAM_macros=20,flop_cells=sum(v for k,v in counts.items() if k.startswith('DFF')),library=dict(name='Nangate45 typical',voltage_V=1.10,temperature_C=25,units=units,sha256=sha(lib)),mapped_functional_inputs=dict(netlist='mapped.v',cell_models='math_linux_20261104/functional_cells.v',SRAM_contract='20 single-port 4096x16, synchronous read/hold, no reset clearing'),P3_full_cold_task_and_inflight_reset_executed=False,port_constraint_gaps=gaps,clock_uncertainty=None,clock_tree='not implemented; propagation assumptions must be declared',parasitics=None,macro_timing_models_available=False,macro_area=None,STA_executed=False,STA_tool_available=bool(shutil.which('sta') or shutil.which('openroad')),WNS_ns=None,TNS_ns=None,unconstrained_timing_paths=None,planned_report_scope='standard-cell register paths only if explicit ideal-clock/reference assumptions are provided; all macro, I/O and reset timing stays separately pending',physical_signoff=False,source_sha256=bindings)
    (out/'macro_boundaries.json').write_text(json.dumps(macros,indent=2));(out/'coverage.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps({k:report[k] for k in ['preparation_checks_passed','standard_cells','SRAM_macros','flop_cells','STA_executed','WNS_ns','TNS_ns']},indent=2))

if __name__=='__main__':main()
