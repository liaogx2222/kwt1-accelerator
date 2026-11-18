"""Read-only audit of the separately owned arch60 handoff; no model rebuild."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--candidate', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--variant', choices=['overlap', 'refine', 'writeback'], default='overlap')
    args = ap.parse_args()
    candidate, out = args.candidate.resolve(), args.output.resolve()
    if out == candidate or candidate in out.parents or out.exists():
        raise ValueError('fresh output outside candidate worktree required')
    out.mkdir(parents=True)
    git = lambda *a: subprocess.check_output(['git', *a], cwd=candidate)
    before = git('status', '--porcelain', '--untracked-files=no')
    head = git('rev-parse', 'HEAD').decode().strip()
    refined = args.variant == 'refine'
    writeback = args.variant == 'writeback'
    delivery = {'overlap':'7055832a734a98f4ee5155e14db0b17510273d60',
                'refine':'c4fa9f2051c801b5fe37f844686f02d3bfefd4d1',
                'writeback':'71233647e9d27ea21acba9a0dc6bd249f95ae94e'}[args.variant]
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', delivery, head], cwd=candidate)
    manifest_path = 'deliverables/arch60_refine_01f5ca2/manifest.json' if refined else 'manifest/arch60_overlap_a691cc7.json'
    if writeback:
        manifest_path = 'deliverables/arch60_writeback_693ffde/manifest.json'
    manifest = json.loads((candidate/manifest_path).read_text())
    archive = candidate/manifest['archive']
    assert archive.stat().st_size == manifest['archive_bytes']
    assert digest(archive) == manifest['archive_sha256']
    seen = set()
    with tarfile.open(archive, 'r:gz') as stream:
        for entry in stream.getmembers():
            name = entry.name
            path = PurePosixPath(name)
            assert entry.isfile() and not path.is_absolute() and '..' not in path.parts
            assert name in manifest['canonical_git_blob_sha256'] and name not in seen
            data = stream.extractfile(entry).read()
            assert hashlib.sha256(data).hexdigest() == manifest['canonical_git_blob_sha256'][name]
            assert data == git('show', manifest['source_revision']+':'+name)
            assert data == (candidate/name).read_bytes().replace(b'\r\n', b'\n')
            seen.add(name)
    assert len(seen) == manifest['RTL_files'] == 22
    campaign = candidate/('testdata/arch60_refine_20261112' if refined else 'testdata/arch60_overlap_20261112')
    soc_dir = campaign/('final_soc12' if refined else 'full_soc12')
    if writeback:
        campaign = candidate/'testdata/arch60_writeback_20261112'
        soc_dir = campaign/'soc12'
    summary = json.loads((campaign/'summary.json').read_text())
    assert summary['passed']
    cycles = summary['task_cycles']
    assert cycles == (2391817 if writeback else 2470147)
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', manifest['source_revision'], summary['source_revision']], cwd=candidate)
    checked = {}
    reports = {}
    for name, expected in summary['source_summary_sha256'].items():
        path = campaign/name/'summary.json'
        assert digest(path) == expected, name
        report = json.loads(path.read_text())
        assert report['passed'], name
        reports[name] = report
        sources = dict(report.get('source_sha256', {}))
        source_hashes = campaign/name/'source_hashes.json'
        if source_hashes.exists():
            sources.update(json.loads(source_hashes.read_text()))
        for value, expected_source in sources.items():
            p = Path(value)
            if not p.is_absolute():
                p = candidate/p
            key = str(p.resolve())
            if key not in checked:
                checked[key] = digest(p)
            assert checked[key] == expected_source, (name, value)
    rows = [list(map(int, line.split())) for line in (soc_dir/'soc_metrics.txt').read_text().splitlines()]
    assert rows == summary['soc_metrics'] and [row[0] for row in rows] == list(range(12))
    assert all(row[1] == cycles and row[5:9] == [189328, 13, 1584, 190924] for row in rows)
    log = (soc_dir/'native.log').read_text()
    for i in range(12):
        assert 'PASS SOC case=%d cycles=%d ' % (i, cycles) in log
        expected = candidate.parent/'rtl-opt/deliverables/local_port_20261103/fixtures'/('expected_%03d.hex' % i)
        observed = soc_dir/('soc_observed_%03d.hex' % i)
        assert observed.read_text().split() == expected.read_text().split(), i
        assert len(observed.read_text().split()) == 1584
    prefetch_pattern = r'PREFETCH_METRICS frames=11 write_cycles=291720 stall_cycles=143852' if writeback else r'PREFETCH_METRICS frames=11 write_cycles=291720 stall_cycles=143872'
    assert len(re.findall(prefetch_pattern, log)) == 12
    # Execute this single trusted project module without a SourceFileLoader,
    # which could create/update __pycache__ in the separately owned worktree.
    assembly_path = candidate/'firmware/soc_joint/assemble.py'
    namespace = {'__name__': 'arch60_readonly_assembler', '__file__': str(assembly_path)}
    exec(compile(assembly_path.read_text(), str(assembly_path), 'exec'), namespace)
    rom = out/'bootrom.hex'
    info = namespace['assemble'](candidate/'rtl/arch60_block/generated/task.S', rom)
    assert info['bytes'] == 500
    assert rom.read_text().split() == (soc_dir/'bootrom.hex').read_text().split()
    refine_results = {}
    if refined:
        frozen = json.loads((campaign/'frozen_files.json').read_text())
        for name, entry in frozen.items():
            p = candidate/name
            assert p.stat().st_size == entry['bytes'] and digest(p) == entry['sha256'], name
        parent = json.loads(git('show', '7055832:testdata/arch60_overlap_20261112/summary.json'))
        assert rows == parent['soc_metrics']
        primitive = reports['primitive_reuse']
        assert primitive['reused_read_only'] and not primitive['rerun_claimed']
        for evidence in primitive['reports'].values():
            assert hashlib.sha256(git('show', '7055832:'+evidence['committed_report'])).hexdigest() == evidence['report_Git_blob_sha256']
            for name, value in evidence['canonical_source_sha256'].items():
                data = (candidate/name).read_bytes().replace(b'\r\n', b'\n')
                assert hashlib.sha256(data).hexdigest() == value
                assert data == git('show', 'a691cc7:'+name)
        structure = reports['structure']['comparison']
        for name, value in structure['candidate']['source_sha256'].items():
            assert digest(candidate/name) == value
        old = structure['parent']['flip_flop_bit_cells']
        new = structure['candidate']['flip_flop_bit_cells']
        assert (old, new, new-old) == (36534, 31414, -5120)
        assert summary['register_bits'] == 31970 and (31970+172+7)//8 == 4018
        fixed_rom = (candidate/'rtl/arch60_block/generated/sirv_mrom_top.v').read_text()
        code = re.sub(r'//[^\n]*|/\*.*?\*/', '', fixed_rom, flags=re.S)
        assert not re.search(r'\b(?:initial|string)\b|\$(?:readmemh|value\$plusargs)', code)
        instructions = {int(i): int(h, 16) for i, h in re.findall(r"(\d+):boot_word=32'h([0-9a-fA-F]+);", code)}
        words = [int(word, 16) for word in rom.read_text().split()]
        assert len(instructions) == len(words) == 125
        assert [instructions[i] for i in range(125)] == words
        assert reports['rom_unit']['binary_interface_checks'] == 65736
        proof = (campaign/'rom_equivalence/proof.log').read_text()
        assert '35 are proven and 0 are unproven' in proof and 'Equivalence successfully proven!' in proof
        refine_results = dict(frozen_evidence_files_verified=len(frozen), generic_FF_before=old, generic_FF_after=new,
                              generic_FF_delta=-5120, declared_accelerator_state_bytes=3997,
                              combined_custom_declared_state_bytes=4018, fixed_ROM_125_words_verified=True,
                              prior_all_14_SoC_metrics_unchanged=True, ROM_binary_proof_outputs=35,
                              primitive_evidence_reused_not_rerun=True)
    if writeback:
        frozen = json.loads((campaign/'frozen_files.json').read_text())
        for name, entry in frozen.items():
            p = candidate/name
            assert p.stat().st_size == entry['bytes'] and digest(p) == entry['sha256'], name
        reused = reports['unchanged_proofs']
        assert reused['reused_read_only'] and not reused['rerun_claimed']
        for evidence in reused['ROM_reports'].values():
            assert hashlib.sha256(git('show', 'c4fa9f2:'+evidence['committed_report'])).hexdigest() == evidence['report_Git_blob_sha256']
            for name, value in evidence['canonical_source_sha256'].items():
                data = (candidate/name).read_bytes().replace(b'\r\n', b'\n')
                assert hashlib.sha256(data).hexdigest() == value
                assert data == git('show', 'c4fa9f2:'+name)
        structure = reports['structure_hier_final']['comparison']
        for name, value in structure['candidate']['source_sha256'].items():
            assert digest(candidate/name) == value
        assert structure['parent']['flip_flop_bit_cells'] == structure['candidate']['flip_flop_bit_cells'] == 31476
        # Reported totals count the leaf logic/macros, not the single hierarchy
        # reference to kwt1_accel in the surrounding MMIO module.
        assert all(structure[label]['generic_cell_types']['kwt1_accel'] == 1 for label in ['parent','candidate'])
        totals = [sum(count for name, count in structure[label]['generic_cell_types'].items() if name != 'kwt1_accel')
                  for label in ['parent','candidate']]
        assert totals == [1264020, 1390885], totals
        assert reports['inventory']['register_bits'] == reports['inventory_block1']['register_bits'] == 31970
        assert reports['inventory_block1']['BLOCK_STREAM'] == 1
        assert reports['writeback_fault']['scenarios'] == 4 and reports['writeback_fault']['no_fault_edge_or_late_SRAM_writes']
        assert reports['writeback_cancel']['scenarios'] == 2 and reports['writeback_cancel']['software_abort_ACK_then_100_cycles_no_late_write']
        old = json.loads(git('show','c4fa9f2:testdata/arch60_refine_20261112/summary.json'))['soc_metrics']
        for previous, current in zip(old, rows):
            assert previous[0] == current[0] and previous[4:] == current[4:]
            assert previous[1]-current[1] == 78330 and previous[2]-current[2] == 13396 and previous[3]-current[3] == 1891
        refine_results = dict(frozen_evidence_files_verified=len(frozen), generic_FF_before=31476, generic_FF_after=31476,
                              generic_cell_before=totals[0], generic_cell_after=totals[1],
                              generic_cell_increase_percent=100*(totals[1]/totals[0]-1),
                              physical_area_increase_not_proven=True, declared_state_BLOCK_STREAM0_and_1=31970,
                              post_fault_layer_recovery_codes=25344, post_cancel_network_recovery_codes=12672,
                              primitive_and_ROM_proofs_reused_not_rerun=True, parent_cycles=2470147,
                              cycles_saved=78330, candidate_priority='PPA tradeoff comparator; not forced replacement for refine')
    assert git('status', '--porcelain', '--untracked-files=no') == before
    assert git('rev-parse', 'HEAD').decode().strip() == head, 'candidate HEAD changed during audit'
    result = dict(passed=True, variant=args.variant, candidate_head=head, delivery_commit=delivery, RTL_source_revision=manifest['source_revision'],
                  archive_sha256=digest(archive), archive_Git_LF_files_verified=22,
                  child_reports_verified=len(reports), unique_source_or_model_hashes_verified=len(checked),
                  full_soc_output_codes_verified=76032, NICE_firmware_bytes=500,
                  task_cycles=cycles, source_supply_period=6,
                  conditional_task_s_at_unverified_150MHz=150000000/cycles,
                  frequency_Hz_needed_for_60_task_s=cycles*60,
                  candidate_tracked_status_unchanged=True, candidate_files_written=False,
                  functional_simulation_rerun=False, actual_EDA_executed=False,
                  physical_signoff=False, whole_SoC_area_mm2=None, power_mW=None, energy_uJ=None,
                  disposition='CONDITIONAL_ACCEPT_FOR_ISOLATED_PHYSICAL_VALIDATION; not production replacement')
    result.update(refine_results)
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
