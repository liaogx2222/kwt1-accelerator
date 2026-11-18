"""Read-only delivery gate for the measured system/synthesis assessment."""
import argparse
import ast
import json
import re
import subprocess
from pathlib import Path
from local_tools import ROOT, sha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--analysis', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    analysis = args.analysis.resolve()
    out = args.output.resolve()
    assert not out.exists(), 'Use a new delivery directory'
    counts = {'evidence_hashes': 0, 'source_hashes': 0}
    bindings = {}

    def check_paths(base, values, category):
        for name, digest in values.items():
            path = base / name.replace('\\', '/')
            assert sha(path) == digest, path
            counts[category] += 1
        return len(values)

    def manifest(folder, name='manifest.json'):
        path = folder / name
        values = json.loads(path.read_text())
        check_paths(folder, values.get('sha256', values), 'evidence_hashes')
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)

    groups = ['e203_combined_20261104', 'e203_factors_20261104',
              'reference_e203/parallel_20261103', 'integration_v1/release',
              'rtl_v2/release', 'rtl_v1/release', 'next_stage_v1']
    for name in groups:
        folder = ROOT / 'testdata' / name
        manifest(folder, 'evidence_manifest.json')
        path = folder / 'source_manifest.json'
        check_paths(ROOT, json.loads(path.read_text()), 'source_hashes')
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)

    folders = ['native_compat_20261104', 'math_linux_20261104',
               'sta_compat_20261104', 'sta_valid_20261104',
               'sta_steady_diagnostic_20261104', 'coverage_cones_20261104',
               'reset_buffer_diagnostic_v2_20261104',
               'sta_buffered_diagnostic_20261104', 'full_gate_review_20261104']
    for name in folders:
        folder = ROOT / 'testdata/nangate45_reference' / name
        manifest(folder)
        path = folder / 'source_bindings.json'
        if path.exists():
            check_paths(ROOT, json.loads(path.read_text()), 'source_hashes')
    gate = ROOT / 'testdata/nangate45_reference/full_gate_20261104'
    manifest(gate, 'evidence_manifest.json')
    check_paths(ROOT, json.loads((gate / 'source_bindings.json').read_text()), 'source_hashes')
    manifest(analysis)
    check_paths(ROOT, json.loads((analysis / 'bindings.json').read_text()), 'source_hashes')
    report = json.loads((analysis / 'analysis.json').read_text())
    assert report['analysis_complete'] and report['mapped_functional_gate']['complete']
    assert report['mapped_functional_gate']['independent_review']['passed']
    assert report['software']['passed'] and not report['software']['internal_9M_target_met']
    assert not report['timing']['complete_signoff'] and not report['physical_signoff']
    assert not report['timing']['buffer_tree_diagnostic']['full_task_variant_regression']

    workspace = ROOT.parent
    docs = [workspace / 'docs/architecture' / name for name in [
        'COMPREHENSIVE_SYNTHESIS_ANALYSIS_20261104.md',
        'PARAMETER_BLOCK_TRANSFER_PROPOSAL_20261104.md',
        'README.md', 'IMPLEMENTATION_ROADMAP.md', 'PLATFORM_HANDOFF.md']]
    docs.append(ROOT / 'flow/NANGATE45_REFERENCE_STA_20261104.md')
    links = 0
    document_hashes = {}
    for path in docs:
        text = path.read_text(encoding='utf-8')
        assert len(re.findall(r'^```', text, re.M)) % 2 == 0, path
        for target in re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)', text):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target):
                continue
            target = target.split('#', 1)[0].strip('<>')
            if target:
                assert (path.parent / target).exists(), (path, target)
                links += 1
        document_hashes[path.relative_to(workspace).as_posix()] = sha(path)

    scripts = ['run_e203_combinations.py', 'summarize_e203_combinations.py',
               'check_e203_combinations.py', 'validate_e203_combinations.py',
               'fetch_opensta_reference.py', 'prepare_opensta_netlist.py',
               'run_nangate45_sta.py', 'run_nangate45_steady_diagnostic.py',
               'analyze_timing_coverage.py', 'experiment_reset_buffer_tree.py',
               'run_nangate45_gate.py', 'check_nangate45_gate.py',
               'analyze_combined_system.py', 'finalize_system_analysis.py',
               'analyze_e203_factor_functions.py', 'analyze_e203_combination_functions.py', Path(__file__).name]
    for name in scripts:
        path = ROOT / 'scripts' / name
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)

    def git(folder, *arguments):
        return subprocess.check_output(['git', '-c', 'safe.directory=' + folder.as_posix(),
                                        '-C', str(folder), *arguments], text=True).strip()
    cpu = workspace / 'e203_hbirdv2'
    assert git(cpu, 'rev-parse', 'HEAD') == '9f3e34f337f5d0a1236a285871ffa2032491617a'
    assert not git(cpu, 'status', '--porcelain'), 'CPU repository was modified'
    patch = git(ROOT, 'diff', '--numstat', '--', 'kws_streaming/data/input_data.py')
    assert patch.split()[:2] == ['3', '3'], patch
    patch_digest = sha(ROOT / 'kws_streaming/data/input_data.py')
    function_result = ROOT / 'testdata/e203_factor_analysis_reproduced_20261104'
    manifest(function_result)
    assert json.loads((function_result / 'function_comparison.json').read_text())['passed']
    result = dict(passed=True, scope='delivery/provenance consistency, not performance or physical signoff',
                  **counts, markdown_files=len(docs), local_links_checked=links,
                  Python_sources_parsed=len(scripts), CPU_repository_clean=True,
                  existing_user_sort_patch_insertions=3, existing_user_sort_patch_deletions=3,
                  user_source_sha256=patch_digest, software_output_codes=101376,
                  mapped_output_codes=12672, full_mapped_reset_recovery=True,
                  function_reproducer_previously_deferred_now_executed=True,
                  internal_9M_target_met=False, complete_STA_signoff=False,
                  buffered_variant_full_functional_regression=False, physical_signoff=False,
                  analysis_sha256=sha(analysis / 'analysis.json'), document_sha256=document_hashes)
    out.mkdir(parents=True)
    (out / 'verification.json').write_text(json.dumps(result, indent=2))
    (out / 'bindings.json').write_text(json.dumps(bindings, indent=2))
    (out / 'manifest.json').write_text(json.dumps({p.name: sha(p) for p in out.iterdir()
                                                if p.is_file()}, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
