"""Synthesis/system assessment. Explicit pending gates, no manufactured PPA."""
import argparse,json,re
from pathlib import Path
from local_tools import ROOT,sha
def read(p):return json.loads(p.read_text())
def verify(base,values):
    for name,digest in values.items():assert sha(base/name)==digest,name
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists(),'Use a new analysis revision';out.mkdir(parents=True)
    sw=ROOT/'testdata/e203_combined_20261104';verify(sw,read(sw/'evidence_manifest.json')['sha256']);verify(ROOT,read(sw/'source_manifest.json'));software=read(sw/'verification.json');assert software['passed']
    sta=ROOT/'testdata/nangate45_reference/sta_valid_20261104';steady=ROOT/'testdata/nangate45_reference/sta_steady_diagnostic_20261104';mapping=ROOT/'testdata/nangate45_reference/native_compat_20261104'
    for base in [sta,steady,mapping]:verify(base,read(base/'manifest.json'))
    for name,digest in read(sta/'source_bindings.json').items():assert sha(ROOT/name)==digest,name
    timing=read(sta/'summary.json');diagnostic=read(steady/'summary.json');mapped=read(mapping/'summary.json')
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib';text=lib.read_text();defs=list(re.finditer(r'(?m)^\s*cell\s*\(\s*(\w+)\s*\)\s*\{',text));cells={}
    for i,m in enumerate(defs):cells[m[1]]=text[m.start():defs[i+1].start() if i+1<len(defs) else len(text)]
    areas={name:float(re.search(r'\barea\s*:\s*([\d.]+)',block)[1]) for name,block in cells.items()}
    counts=mapped['counts'];area=sum(count*areas[name] for name,count in counts.items());seq=sum(count*areas[name] for name,count in counts.items() if name.startswith('DFF'));assert abs(area-475862.296)<1e-5
    buf=cells['BUF_X1'];maxcap=float(re.search(r'max_capacitance\s*:\s*([\d.]+)',buf)[1]);maxslew=float(re.search(r'default_max_transition\s*:\s*([\d.]+)',text)[1]);index2=max(float(v) for s in re.findall(r'index_2\s*\(\s*"([^"]+)"',buf) for v in s.split(','))
    abc=read(sw/'compare_abc/summary.json')['jobs'][0];ac=read(sw/'compare_ac/summary.json')['jobs'][0];phase=abc['phase_cycles'];whole=abc['main']['cycles'];other=whole-phase['packet_owned'];allowed=9000000-other
    budget=dict(main_cycles=whole,phase_cycles=phase,phase_percent={k:100*v/whole for k,v in phase.items()},packet_owned_cycles_per_parameter_word=phase['packet_owned']/189328,non_packet_phase_cycles=other,packet_owned_budget_if_other_phases_unchanged=allowed,required_packet_owned_reduction_percent=100*(1-allowed/phase['packet_owned']),allowed_cycles_per_parameter_word_including_handoffs=allowed/189328,scope='conditional remaining budget only; not measured performance of a proposed block engine')
    coverage=(sta/'check_setup.txt').read_text();coverage_counts={name:int(re.search(pattern,coverage)[1]) for name,pattern in [('input_bits_without_input_delay',r'There are (\d+) input ports missing'),('output_bits_without_output_delay',r'There are (\d+) output ports missing'),('reported_unconstrained_endpoints',r'There are (\d+) unconstrained endpoints')]}
    critical=(sta/'setup_paths.txt').read_text().split('\n\nStartpoint:',1)[0]
    highfan=dict(net='accel.task_rst_n',driver='_327406_/Z BUF_X1',fanout=4794,reported_load_fF=12757.795898,reported_output_slew_ns=29.120903,library_max_capacitance_fF=maxcap,library_max_table_index2_fF=index2,library_default_max_transition_ns=maxslew,capacitance_over_max_ratio=12757.795898/maxcap,slew_over_max_ratio=29.120903/maxslew,numeric_delay_uses_out_of_range_extrapolation=True,interpretation='violations demonstrate missing high-fanout/reset distribution repair; do not derive silicon Fmax from this extrapolated number')
    net=read(mapping/'mapped.json')['modules']['kwt1_mmio'];assert sum(c['type']=='kwt_tech_sram_4096x16' for c in net['cells'].values())==20
    del net
    # Yosys writer-renamed instance IDs are not JSON cell names. Cross-check
    # pin expressions in BOTH emitted netlists instead of assuming name identity.
    original_verilog=(mapping/'mapped.v').read_text();sta_verilog=(ROOT/'testdata/nangate45_reference/sta_compat_20261104/mapped_simple.v').read_text();endpoints={}
    for cellname in ['_617031_','_611874_','_612096_','_611918_']:
        pattern=r'\b(\w+)\s+'+re.escape(cellname)+r'\s*\((.*?)\);'
        left=re.search(pattern,original_verilog,re.S);right=re.search(pattern,sta_verilog,re.S);assert left and right and left.group(0)==right.group(0)
        pins=dict(re.findall(r'\.(\w+)\s*\(\s*(.*?)\s*\)',left[2],re.S));endpoints[cellname]=dict(type=left[1],pins=pins,Q_net_aliases=[pins['Q']])
    gate=ROOT/'testdata/nangate45_reference/full_gate_20261104';gate_result=read(gate/'verification.json') if (gate/'verification.json').exists() else None
    if gate_result:verify(gate,read(gate/'evidence_manifest.json')['sha256']);assert gate_result['passed']
    gate_log=(gate/'run/live.log').read_text() if (gate/'run/live.log').exists() else '';progress=re.findall(r'GATE PROGRESS ticks=(\d+)',gate_log)
    p3=dict(complete=bool(gate_result),scope='actual mapped top + same-library functional models + 20 SRAM contracts; no SDF, host driver',last_logged_tick=int(progress[-1]) if progress else 0,complete_cold_tasks_logged=len(re.findall(r'CASE \d+ .* PASS',gate_log)),inflight_reset_logged='GATE RESET PASS' in gate_log,result=gate_result)
    report=dict(analysis_complete=True,architecture=dict(integer='v1',PE='8x8',SRAM='20x4096x16',internal_register_declaration_bytes=3808),software=software,conditional_9M_budget=budget,area=dict(reference='Nangate45 typical ONLY',standard_cell_count=310005,standard_cell_area_um2=area,sequential_area_um2=seq,combinational_and_buffer_area_um2=area-seq,external_SRAM_macro_count=20,external_SRAM_capacity_bytes=163840,SRAM_area=None,platform_adapter_area=None,total_area=None,formula='A_ref45=0.475862296mm2 + 20*A_SRAM_ref45 + A_actual_adapter_ref45; not SMIC40'),timing=dict(baseline=timing,steady_diagnostic=diagnostic,high_fanout=highfan,critical_register_aliases=endpoints,coverage=coverage_counts,complete_signoff=False),mapped_functional_gate=p3,energy=dict(measured=False,reason='no designated macro power, activity-complete mapped whole system or platform energy model; runtime/instruction reduction is not an energy percentage'),next_proposal=dict(first='repair/reference-map high-fanout reset/control distribution, retain same architecture; rerun functional and timing checks',software='evaluate bounded platform block-stream transport; preserve first error, CRC/lease/abort/reset quarantine. No DMA implemented.',block_engine_state_reservation_bytes=[64,128],state_reservation_scope='proposal budget only, includes descriptor/handshake/error/timeout/epoch; excludes unmeasured arbitration/FIFO implementation; must inventory and map before approval',extra_SRAM_macros_proposed=0,architecture_approval_required=True),physical_signoff=False,SOURCE_E01='OPEN',LN_E01='unchanged approved exception')
    (out/'analysis.json').write_text(json.dumps(report,indent=2));(out/'critical_path.txt').write_text(critical)
    bindings={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),sw/'verification.json',sta/'summary.json',steady/'summary.json',mapping/'summary.json',lib,ROOT/'scripts/validate_e203_combinations.py']};(out/'bindings.json').write_text(json.dumps(bindings,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(dict(analysis_complete=True,software_passed=True,cycles=software['normal_outer_cycle_range'],budget=budget,area=report['area'],highfan=highfan,critical_aliases=endpoints,P3_complete=p3['complete']),indent=2))
if __name__=='__main__':main()
