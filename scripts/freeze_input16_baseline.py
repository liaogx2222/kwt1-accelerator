"""Bind the unique current performance and resource comparison baseline."""
import json
import os

from local_tools import ROOT, sha


def read(path):
    return json.loads(path.read_text())


def main():
    base = ROOT / 'testdata/input16_rtl_20261105'
    cpu = base / 'trim2_e203'
    profile = base / 'p0_baseline'
    area = base / 'mapping_trim'
    activity = base / 'trim_bank_activity'
    out = base / 'p0_frozen_configuration'
    out.mkdir()
    for folder in [cpu, profile, area, activity]:
        for name, digest in read(folder / 'manifest.json').items():
            assert sha(folder / name) == digest, (folder, name)
        for name, digest in read(folder / 'source_bindings.json').items():
            assert sha(ROOT / name) == digest, (folder, name)

    p0 = read(profile / 'verification.json')
    assert p0['passed'] and p0['cycles'] == 9634904
    compute = int((cpu / 'cpu_metrics.txt').read_text().splitlines()[0].split()[15])
    windows = read(cpu / 'verification.json')['windows']
    assert windows[0][2] - windows[0][1] == p0['cycles']
    sram = read(activity / 'verification.json')['cases'][0]
    mapped = read(area / 'verification.json')
    assert sum(bank['reads'] for bank in sram) == windows[0][8]
    assert sum(bank['writes'] for bank in sram) == windows[0][9]
    phases = p0['phase_cycles']
    retired = p0['phase_retired']
    baseline = dict(configuration='S16/trim2, 8x8, E203 PIO, 16x4096 + 8x1024 private SRAM',
                    cycles=p0['cycles'], core_compute_counter=compute, exclusive_phase_cycles=phases,
                    exclusive_phase_retired=retired,
                    parameter_move_retired_baseline=retired['packet_lease'],
                    parameter_move_retired_definition='all retirements between provider lease acquisition and release, including protocol handling',
                    accepted_parameter_words=p0['accepted_parameter_words'],
                    data_request_wait_cycles=p0['parameter_data_request_stall_cycles'],
                    report_tail_cycles=windows[0][3]-windows[0][2],
                    report_tail_shared_ram_reads=windows[0][6],
                    private_logical_bank_events=sram,
                    physical_sram_macro_counts={'4096x16': 16, '1024x16': 8},
                    private_sram_bytes=147456,
                    standard_cell_area_mm2=mapped['standard_cell_area_mm2'],
                    private_sram_area_analytical_mm2=mapped['private_SRAM_analytical_area_mm2'],
                    complete_area_reference_mm2=mapped['complete_counted_area_open_reference_mm2'],
                    official_area_mm2=None, official_frequency_Hz=None, mean_SoC_power_mW=None)
    paths = [profile / 'verification.json', profile / 'window_job_00.txt', cpu / 'firmware.elf',
             cpu / 'firmware.bin', cpu / 'firmware_symbols.log', cpu / 'compiler_command.json',
             cpu / 'model/Vreference_top__ALL.a', cpu / 'model/Vreference_top', cpu / 'build.log',
             cpu / 'source_bindings.json', area / 'mapped.json', area / 'verification.json',
             activity / 'verification.json', ROOT / 'rtl/input16_trim2/generated/kwt_profile.svh',
             ROOT / 'testdata/full_scope_20261105/sram_cacti/verification.json',
             ROOT / 'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib']
    baseline['identity_sha256'] = {os.path.relpath(path, ROOT).replace('\\', '/'): sha(path) for path in paths}
    (out / 'baseline.json').write_text(json.dumps(baseline, indent=2))
    print(json.dumps({k: baseline[k] for k in ['cycles', 'core_compute_counter', 'parameter_move_retired_baseline', 'complete_area_reference_mm2']}, indent=2))


if __name__ == '__main__':
    main()
