"""Competition-scoped metrics: measured references and explicit missing official gates."""
import argparse
import json
import shutil
from pathlib import Path
import numpy as np
from local_tools import ROOT, sha


def read(path):
    return json.loads(path.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campaign', type=Path, required=True)
    ap.add_argument('--review', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    base, review, out = args.campaign.resolve(), args.review.resolve(), args.output.resolve()
    assert not out.exists(), 'Use new metrics output'
    for name, digest in read(review / 'manifest.json').items():
        assert sha(review / name) == digest, name
    for name, digest in read(review / 'source_bindings.json').items():
        assert sha(ROOT / name) == digest, name
    checked = read(review / 'verification.json')
    assert checked['passed']
    full = read(base / 'full_classes/summary.json')
    selected = read(base / 'selection.json')
    jobs = full['jobs']
    validation = ROOT / 'testdata/integer_v1/validation'
    fixture = ROOT / 'testdata/integer_v1/fixture'
    labels = np.load(fixture / 'labels.npy')
    fp = np.load(fixture / 'fp_logits.npy')
    integer = np.load(validation / 'logits.npy')
    assert len(labels) == 4445 and fp.shape == integer.shape == (4445, 12)
    assert np.isfinite(fp).all() and np.isfinite(integer).all()
    fp_correct = int(np.count_nonzero(np.argmax(fp, axis=1) == labels))
    int_correct = int(np.count_nonzero(np.argmax(integer, axis=1) == labels))
    assert (fp_correct, int_correct) == (4348, 4338)
    decode = read(ROOT / 'testdata/integer_v1/params/manifest.json')['decode_scales']
    assert all(np.isfinite(value) and value > 0 for value in decode.values())
    for name, digest in read(fixture / 'manifest.json')['source_sha256'].items():
        assert sha(ROOT / name.replace('\\', '/')) == digest, name
    missing = read(base / 'smic40_preflight.json')
    assert not missing['preflight_passed'] and len(missing['missing']) == 31 and not missing['errors']
    mapping = ROOT / 'testdata/nangate45_reference/native_compat_20261104'
    sta = ROOT / 'testdata/nangate45_reference/sta_valid_20261104'
    for folder in [mapping, sta]:
        for name, digest in read(folder / 'manifest.json').items():
            assert sha(folder / name) == digest, name
    mapped_report=read(mapping/'summary.json')
    assert mapped_report['standard_cell_area_mm2']==0.475862296 and mapped_report['sram_macros']==20
    assert read(sta/'summary.json')['register_to_register_setup_worst_slack_ns']==-31.45647
    clocks = [job['main']['cycles'] for job in jobs]
    retires = [job['main']['retired'] for job in jobs]
    total = sum(clocks)
    pre = jobs[0]['pre_job'][0]
    abc = read(ROOT / 'testdata/e203_combined_20261104/verification.json')
    phase = jobs[0]['phase_cycles']
    transactions = [{line.split()[0]: int(line.split()[1]) for line in
                     (base / 'full_classes' / f'transactions_job_{i:02d}.txt').read_text().splitlines()} for i in range(12)]
    report = dict(
        engineering_implementation='complete integer encoder RTL and reference E203 PIO firmware; designated platform/library acceptance pending',
        official_submission_complete=False, official_efficiency_scoring_eligibility_proven=False,
        official_requirements=dict(group='graduate', layers=12, tensor=[99, 64], frequency_MHz=150,
            area_limit_mm2=2.25, area_scope='new accelerator + interface + internal SRAM macros; fixed CPU/shared SRAM/bus separately listed',
            accuracy_samples=600, max_accuracy_drop_pp=2,
            performance_tasks=12, performance_window='input/parameter loading through final output writeback, including E203 and bus waits; task data/parameter state cold',
            minimum_tasks_per_second=None, maximum_power_mW=None, maximum_energy_J_per_task=None,
            place_and_route_required=False,
            power_scope='CPU + accelerator + interconnect + SRAM dynamic/static, same-window mapped activity'),
        official_metrics=dict(accuracy_percent=None, accuracy_drop_pp=None, throughput_tasks_per_second=None,
            verified_150MHz=False, achieved_frequency_MHz=None, total_counted_area_mm2=None,
            mean_power_mW=None, energy_J_per_task=None, efficiency_scores=None),
        validation_reference=dict(samples=4445, partition='validation', fp_correct=fp_correct, integer_correct=int_correct,
            fp_accuracy_percent=100*fp_correct/4445, integer_accuracy_percent=100*int_correct/4445,
            accuracy_drop_pp=100*(fp_correct-int_correct)/4445,
            logits_and_decode_scales_finite=True, official_600_result=False,
            parameters_changed=False, testing_used_for_tuning=False),
        software_reference=dict(configuration=selected['selected_variant'], CPU='Hummingbirdv2 E203 9f3e34f3',
            model='actual CPU RTL instructions + frozen accelerator RTL, no SDF',
            clock_assumption_Hz=150000000, actual_silicon_frequency_verified=False,
            measured_task_cycles=clocks, twelve_task_cycles=total, main_retired=retires,
            twelve_task_seconds_at_assumed_150MHz=total/150000000,
            throughput_at_assumed_150MHz=12*150000000/total,
            first_preparation_cycles=pre, preparation_plus_twelve_windows_cycles=pre+total,
            throughput_including_first_preparation_at_assumed_150MHz=12*150000000/(pre+total),
            report_tail_cycles=[job['report_tail']['cycles'] for job in jobs],
            official_task_selection=False, all_12_classes_in_one_CPU_object=True,
            parameter_packets_per_task=13, parameter_words_per_task=189328,
            parameter_packet_bytes_per_task=757312, input_bytes_per_task=6336, output_bytes_per_task=6336,
            host_supply_bytes_per_second_at_150MHz=100000000, packet_latency_cycles=1024,
            packet_lease_peak_bytes=61728, phase_cycles_first=phase,
            packet_owned_percent=100*phase['packet_owned']/clocks[0],
            cycles_reduction_vs_ABC_percent=100*(1-clocks[0]/abc['ABC_cycles']),
            cycles_reduction_vs_original_percent=100*(1-clocks[0]/abc['baseline_cycles']),
            compute_cycles_per_task=5058532, SRAM_reads_per_task=[t['SRAM_reads'] for t in transactions],
            SRAM_writes_per_task=[t['SRAM_writes'] for t in transactions],
            SRAM_read_transactions_twelve_tasks=sum(t['SRAM_reads'] for t in transactions),
            SRAM_write_transactions_twelve_tasks=sum(t['SRAM_writes'] for t in transactions),
            immediate_ACC_error_queries_per_task=[t['error_queries'] for t in transactions],
            DMA=False, hardware_state_added_bits=0,
            shared_memory_bytes=524288, occupied_shared_with_16KiB_reserved_stack_bytes=98992,
            measured_stack_highwater_bytes=checked['stack_highwater_bytes'], ITCM_used_bytes=full['ITCM_bytes'],
            reference_CPU_ITCM_capacity_bytes=65536, final_platform_ITCM_availability_confirmed=False,
            internal_SRAM=dict(macros=20, depth=4096, width_bits=16, bytes=163840),
            declared_accelerator_register_bytes=3808, internal_9M_target_met=max(clocks)<=9000000),
        public_library_reference=dict(library='Nangate45 typical 1.10V 25C, not SMIC40',
            standard_cell_area_mm2=0.475862296, SRAM_macro_area_mm2=None, total_counted_area_mm2=None,
            original_mapped_gate_output_codes=12672, original_mapped_gate_reset_recovery=True,
            original_partial_STA_WNS_ns=-31.45647,
            separate_buffer_diagnostic_partial_STA_WNS_ns=-0.03760059,
            buffer_diagnostic_production_adopted=False, complete_STA=False,
            same_CPU_software_plus_mapped_whole_system_run=False),
        pending_acceptance=[
            'designated organizer SoC/bus/provider binding; reference CPU repository is not the complete designated platform',
            'official 600-sample result and frozen-submission 12-task selection by organizer',
            'SMIC40 cell library/PVT and SRAM simulation/timing/area/power models and wrapper',
            'complete valid 150MHz synthesis STA including macro and I/O arcs and approved interconnect estimates',
            'counted total area including 20 internal macros and actual added platform interface',
            'same-configuration CPU/accelerator/interconnect/SRAM activity coverage and average power/energy',
            'SOURCE-E01 historical source identity remains OPEN'],
        missing_technology_fields=missing['missing'], LN_E01='unchanged approved fixed-profile exception',
        innovation_and_relative_efficiency_scores='not computable without eligible-design peer baselines and judging',
        scope='development evidence and submission-readiness ledger; no invented official or SMIC40 PPA results')
    out.mkdir(parents=True)
    (out / 'metrics.json').write_text(json.dumps(report, indent=2))
    package = out / 'reference_firmware'
    package.mkdir()
    folder = base / 'full_classes'
    for name in ['main.c', 'driver.c', 'word_access.h', 'firmware.elf', 'firmware.bin',
                 'firmware.map', 'firmware.nm', 'disassembly.log', 'compiler_command.json']:
        shutil.copyfile(folder / name, package / name)
    for name in ['start_itcm.S', 'link_itcm.ld']:
        shutil.copyfile(ROOT / 'firmware/e203_experiments_20261104' / name, package / name)
    shutil.copyfile(ROOT / 'rtl/integration/driver/kwt1.h', package / 'kwt1.h')
    (package / 'README.md').write_text('''# Reference E203 synchronous PIO firmware

Selected software-only backend; integer v1 / 8x8 / 20 macros unchanged. Uses GCC 15.2 -O2 -flto, original CPU ITCM startup, fixed reference ACC 0x10000000 and testbench mailbox 0x10010000. Not a portable organizer-SoC binary.

Device ABI remains 40 bytes on RV32. All public entries require exact platform read/write callbacks and no cancellation source; otherwise KWT1_ARGUMENT. Keep the generic rtl/integration/driver for other platforms and cancellation sources. Each DATA store has an immediate error query; no posted batch, deferred error or DMA. Provider lease, frame/last, CRC, bounded waits, ABORT failure quarantine and confirmed hard-reset recovery are retained.

The packaged ELF/bin/map are the actual full-class regression image. Reproduce from the project root using scripts/run_e203_pio_metrics.py with variant unroll8_likely and the source-bound transaction model. The original compiler command records historical paths; source files and linker/startup are included for inspection and rebuilding. Rebuild with scripts/rebuild_e203_pio_package.py into a fresh output directory and require identical firmware.bin.
''')
    evidence = [review / 'verification.json', base / 'selection.json', base / 'smic40_preflight.json',
                validation / 'metrics.json', validation / 'logits.npy', fixture / 'labels.npy',
                fixture / 'fp_logits.npy', fixture / 'manifest.json', ROOT / 'testdata/integer_v1/params/manifest.json',
                mapping / 'summary.json', sta / 'summary.json', Path(__file__)]
    bindings = {path.relative_to(ROOT).as_posix(): sha(path) for path in evidence}
    original = ROOT.parent / 'docs/architecture/evidence/competition_original.txt'
    (out / 'source_bindings.json').write_text(json.dumps(bindings, indent=2))
    (out / 'competition_source.json').write_text(json.dumps(dict(
        extracted_text=original.relative_to(ROOT.parent).as_posix(), extracted_text_sha256=sha(original),
        original_pdf='f8732a6ebb0442b1986eeec83a4bf6db.pdf',
        original_pdf_sha256=sha(ROOT.parent / 'f8732a6ebb0442b1986eeec83a4bf6db.pdf'),
        official_pages='body 3/4/7/10/11/12, PDF page offset +1'), indent=2))
    (out / 'manifest.json').write_text(json.dumps({path.relative_to(out).as_posix(): sha(path)
        for path in out.rglob('*') if path.is_file() and path.name != 'manifest.json'}, indent=2))
    print(json.dumps(dict(official_submission_complete=False, twelve_task_cycles=total,
        reference_throughput_at_assumed_150MHz=12*150000000/total,
        validation_accuracy_percent=100*int_correct/4445, pending=len(report['pending_acceptance'])), indent=2))


if __name__ == '__main__':
    main()
