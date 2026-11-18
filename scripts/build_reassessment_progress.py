"""Assemble a same-scope progress ledger for the P0/P1/P2 work packages."""
import argparse
import json
from pathlib import Path

from local_tools import ROOT, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    out = parser.parse_args().output.resolve()
    out.mkdir(parents=True)
    base = ROOT / 'testdata/input16_rtl_20261105'
    evidence = {}

    def read(name, filename='verification.json'):
        path = base / name / filename
        manifest = path.parent / 'manifest.json'
        if manifest.exists():
            assert sha(path) == json.loads(manifest.read_text())[path.name], path
        evidence[path.relative_to(ROOT).as_posix()] = sha(path)
        return json.loads(path.read_text())

    frozen = read('p0_frozen_configuration', 'baseline.json')
    original_ppa = read('metrics', 'metrics.json')['candidates'][1]
    assert original_ppa['candidate'] == 'trimmed_24_macro'
    reset = read('p1_reset12_fixed')
    drive = read('p1_sizing_all')
    final_sta = read('p1_sizing_electrical')
    rtl = read('p1_icb_rtl_control')
    assert rtl['passed'] and not rtl['mapped']
    assert final_sta['WNS_ns'] >= 0 and final_sta['TNS_ns'] == 0
    assert final_sta['negative_setup_endpoints'] == final_sta['max_transition_violators'] == 0
    p2 = read('p2_block_contract')
    gate = None
    gate_folder = base / 'p1_icb_mapped_final'
    if (gate_folder / 'verification.json').exists():
        gate = read('p1_icb_mapped_final')
        assert gate['passed'] and gate['mapped'] and gate['mismatches'] == 0
        assert gate['cold_tasks'] == 2 and gate['in_flight_cancel'] == gate['in_flight_reset'] == 1
    area_increment = sum(record['area_increment_mm2'] for record in [reset, drive, final_sta])
    report = {
        'P0_complete': True,
        'P1_reference_sta_complete': True,
        'P1_full_mapped_gate_complete': gate is not None,
        'P1_mapped_functional_result': gate,
        'P2_portable_frontend_verified': p2['passed'],
        'P2_actual_E203_block_path_complete': False,
        'P3_P4_P5_complete': False,
        'compact_full_window_budget_cycles': 4000000,
        'compact_full_window_cycles_measured': None,
        'official_150MHz_verified': False,
        'official_counted_area_mm2': None,
        'frozen_reference': {
            'full_E203_cycles': frozen['cycles'],
            'tasks_per_second_assuming_150MHz': 150000000 / frozen['cycles'],
            'mean_SoC_power_mW': None,
            'private_SRAM_power_analytical_mW': original_ppa['private_SRAM_only_analytical_power']['mean_mW'],
            'complete_counted_area_reference_mm2': frozen['complete_area_reference_mm2'],
        },
        'P1_electrical_revision': {
            'full_E203_cycles': None, 'tasks_per_second': None, 'mean_SoC_power_mW': None,
            'complete_counted_area_reference_mm2': frozen['complete_area_reference_mm2'] + area_increment,
            'standard_cell_area_increment_mm2': area_increment,
            'reference_WNS_ns': final_sta['WNS_ns'], 'reference_TNS_ns': final_sta['TNS_ns'],
            'reference_max_transition_violators': final_sta['max_transition_violators'],
        },
        'P2_isolated_transport': p2['measured'],
        'evidence_sha256': evidence,
    }
    (out / 'metrics.json').write_text(json.dumps(report, indent=2))
    (out / 'manifest.json').write_text(json.dumps({'metrics.json': sha(out / 'metrics.json')}, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != 'evidence_sha256'}, indent=2))


if __name__ == '__main__':
    main()
