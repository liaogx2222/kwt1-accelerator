"""New immutable assessment revision with live-gate snapshot and provenance."""
import argparse,json,shutil,sys
from pathlib import Path
from local_tools import ROOT,sha
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve()
    import analyze_combined_system
    sys.argv=[str(ROOT/'scripts/analyze_combined_system.py'),'--output',str(out)];analyze_combined_system.main()
    gate=ROOT/'testdata/nangate45_reference/full_gate_20261104';report=json.loads((out/'analysis.json').read_text())
    for name,source in [('mapped_gate_progress_snapshot.log',gate/'run/live.log'),('mapped_gate_sources.json',gate/'source_bindings.json'),('mapped_gate_command.json',gate/'run/command.json')]:
        if source.exists():shutil.copyfile(source,out/name)
    log=(out/'mapped_gate_progress_snapshot.log').read_text() if (out/'mapped_gate_progress_snapshot.log').exists() else ''
    report['mapped_functional_gate']['status']='passed' if report['mapped_functional_gate']['complete'] else 'failed' if 'FAIL' in log else 'running'
    coverage=ROOT/'testdata/nangate45_reference/coverage_cones_20261104'
    for name,digest in json.loads((coverage/'manifest.json').read_text()).items():assert sha(coverage/name)==digest,name
    report['timing']['structural_coverage']=json.loads((coverage/'summary.json').read_text())
    report['timing']['reset_scope_note']='External reset/abort are fixed inactive in running mode. Baseline includes software sw_abort-to-D paths; D-only setup totals exclude RN/SN recovery/removal checks. Steady diagnostic additionally fixes sw_abort Q=0 and is not a signoff mode.'
    # Mapping repair is a separate diagnostic variant: never inherit the original
    # mapped-top functional pass for a netlist that was not simulated.
    repair=ROOT/'testdata/nangate45_reference/reset_buffer_diagnostic_v2_20261104'
    repaired_sta=ROOT/'testdata/nangate45_reference/sta_buffered_diagnostic_20261104'
    for folder in [repair,repaired_sta]:
        for name,digest in json.loads((folder/'manifest.json').read_text()).items():
            assert sha(folder/name)==digest,name
    for name,digest in json.loads((repaired_sta/'source_bindings.json').read_text()).items():
        assert sha(ROOT/name)==digest,name
    repair_result=json.loads((repair/'summary.json').read_text())
    timing_result=json.loads((repaired_sta/'summary.json').read_text())
    assert repair_result['passed'] and repair_result['projection_unchanged']
    assert repair_result['SRAM_macros']==timing_result['SRAM_macros']==20
    assert timing_result['source_sha256'][(repair/'mapped_buffered.v').relative_to(ROOT).as_posix()]==repair_result['netlist_sha256']
    assert sha(ROOT/'scripts/experiment_reset_buffer_tree.py')==repair_result['script_sha256']
    report['timing']['buffer_tree_diagnostic']=dict(
        structure=repair_result,timing=timing_result,
        unchanged_baseline_constraints=True,software_abort_path_kept=True,
        production_adopted=False,full_task_variant_regression=False,
        interpretation='Non-inverting mapping-only repair removes the high-fanout root cause under the same reference assumptions; 3 arithmetic D endpoints still violate setup. No complete timing or physical signoff.')
    audit=ROOT/'testdata/nangate45_reference/full_gate_review_20261104'
    if report['mapped_functional_gate']['complete']:
        for name,digest in json.loads((audit/'manifest.json').read_text()).items():
            assert sha(audit/name)==digest,name
        review=json.loads((audit/'verification.json').read_text())
        assert review['passed'] and review['output_codes_independently_recomputed']==12672
        assert review['gate_verification_sha256']==sha(gate/'verification.json')
        assert review['script_sha256']==sha(ROOT/'scripts/check_nangate45_gate.py')
        report['mapped_functional_gate']['independent_review']=review
        report['mapped_functional_gate']['variant']='original native_compat mapped.v, not buffer-tree variant'
    report['acceptance']=dict(
        software_full_regression='passed',original_mapped_function='passed' if report['mapped_functional_gate']['complete'] else 'pending',
        internal_9M_performance='not_met',reference_150MHz_setup='not_met_in_declared_scope',
        full_STA='pending_macro_IO_physical_constraints',SMIC40='pending_designated_library_platform',
        total_area='unknown_SRAM_and_adapter',energy='unmeasured')
    report['scope']='complete engineering assessment with explicit pass/fail/pending gates; not a claim that all signoff gates passed'
    functions=ROOT/'testdata/e203_combined_functions_20261104'
    for name,digest in json.loads((functions/'manifest.json').read_text()).items():
        assert sha(functions/name)==digest,name
    function_result=json.loads((functions/'function_comparison.json').read_text())
    assert function_result['passed'] and function_result['script_sha256']==sha(ROOT/'scripts/analyze_e203_combination_functions.py')
    for name,digest in function_result['source_sha256'].items():
        assert sha(ROOT/name)==digest,name
    report['software_function_PC_attribution']=function_result
    (out/'analysis.json').write_text(json.dumps(report,indent=2));bindings={name.replace('\\','/'):digest for name,digest in json.loads((out/'bindings.json').read_text()).items()};bindings[Path(__file__).relative_to(ROOT).as_posix()]=sha(Path(__file__));bindings['scripts/run_nangate45_gate.py']=sha(ROOT/'scripts/run_nangate45_gate.py');bindings['scripts/analyze_timing_coverage.py']=sha(ROOT/'scripts/analyze_timing_coverage.py');bindings[coverage.relative_to(ROOT).as_posix()+'/summary.json']=sha(coverage/'summary.json');(out/'bindings.json').write_text(json.dumps(bindings,indent=2))
    extra=[repair/'summary.json',repair/'manifest.json',repaired_sta/'summary.json',
           repaired_sta/'manifest.json',ROOT/'scripts/experiment_reset_buffer_tree.py',
           functions/'function_comparison.json',functions/'manifest.json',
           ROOT/'scripts/analyze_e203_combination_functions.py']
    if report['mapped_functional_gate']['complete']:
        extra += [gate/'verification.json',gate/'evidence_manifest.json',audit/'verification.json',
                  audit/'manifest.json',ROOT/'scripts/check_nangate45_gate.py']
    bindings.update({p.relative_to(ROOT).as_posix():sha(p) for p in extra})
    (out/'bindings.json').write_text(json.dumps(bindings,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'},indent=2))
    print(json.dumps(report['acceptance'],indent=2))
if __name__=='__main__':main()
