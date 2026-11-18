"""Independent integer replay and consistency checks for the S16 integration."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess

import numpy as np

from local_tools import ROOT, sha
import validate_competitive_components as component
import validate_competitive_resident_core as original


FOLDERS = (
    'derivation', 'sign_extension', 'layer_smoke', 'layer_all', 'layer_stress',
    'full_native', 'e203', 'trim_derivation', 'trim_label_fix', 'trim2_native',
    'trim2_e203', 'trim_leaf', 'trim_leaf_gate', 'trim_bank_activity',
    'mapping_full', 'mapping_trim', 'sta_full_simple', 'sta_trim_simple', 'metrics',
)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify(folder):
    manifest = read(folder / 'manifest.json')
    for file, digest in manifest.items():
        assert sha(folder / file) == digest, (folder, file)
    sources = read(folder / 'source_bindings.json')
    for file, digest in sources.items():
        assert sha(ROOT / file) == digest, (folder, file)
    return len(manifest), len(sources)


def compare_hex(path, expected):
    data = b''.join(int(word, 16).to_bytes(4, 'little')
                    for word in path.read_text().split())
    assert data == expected.tobytes(), path
    return len(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    out = parser.parse_args().output.resolve()
    base = ROOT / 'testdata/input16_rtl_20261105'
    counts = [verify(base / name) for name in FOLDERS]
    if (out / 'verification.json').exists():
        verify(out)
        print((out / 'verification.json').read_text())
        return

    reports = {name: read(base / name / 'verification.json') for name in FOLDERS}
    assert all(report['passed'] for report in reports.values())
    bound = {}

    def bind(path):
        bound[os.path.relpath(path, ROOT).replace('\\', '/')] = sha(path)

    for name in FOLDERS:
        for filename in ('manifest.json', 'source_bindings.json'):
            bind(base / name / filename)

    inputs, _ = original.inputs(12)
    parameters = dict(np.load(component.BASE / 'run/params/parameters.npz'))
    reference = [component.reference_stages(inputs[i:i+1], parameters) for i in range(12)]
    codes = Counter()
    for name in ('layer_smoke', 'layer_all', 'layer_stress', 'full_native', 'trim2_native'):
        report = reports[name]
        for case in report['cases']:
            layer = case['profile'] if report['stage'] == 'layer' else 11
            expected = reference[case['label']][f'layer_{layer:02d}/layernorm2_output'][0]
            codes['native'] += compare_hex(base / name / f'observed_{case["case"]:03d}.hex', expected)
    assert reports['full_native']['metrics'] == reports['trim2_native']['metrics']
    assert 'STRESS PASS rejected=7 packet_resets=3 input_resets=1 execution_resets=8' in reports['layer_stress']['summary']

    for name in ('e203', 'trim2_e203', 'trim_bank_activity'):
        subdirs = ('',) if name == 'trim_bank_activity' else ('', 'faults')
        for subdir in subdirs:
            folder = base / name / subdir
            rows = [[int(field) for field in line.split()]
                    for line in (folder / 'cpu_metrics.txt').read_text().splitlines()]
            for row in rows:
                if row[3] == 0:
                    expected = reference[row[1]]['layer_11/layernorm2_output'][0]
                    group = 'observer' if name == 'trim_bank_activity' else 'e203'
                    codes[group] += compare_hex(folder / f'cpu_observed_job_{row[0]:02d}.hex', expected)
            if subdir:
                assert [row[3] for row in rows] == [-3, 0, -7, 0]
            else:
                assert len(rows) == 12 and all(row[4] == 9634904 for row in rows)
                assert all(row[8:12] == [189328, 13, 13, 0] for row in rows)
    assert reports['e203']['windows'] == reports['trim2_e203']['windows']
    for banks in reports['trim_bank_activity']['cases']:
        weight_tail = [bank for bank in banks if bank['bank'] in (1, 3, 5, 7)]
        assert sum(bank['reads'] for bank in weight_tail) == 1277952
        assert sum(bank['writes'] for bank in weight_tail) == 98304

    library = ROOT / 'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    areas = {name: float(value) for name, value in re.findall(
        r'cell\s*\(\s*(\w+)\s*\)\s*\{.*?area\s*:\s*([\d.]+)',
        library.read_text(), re.S)}
    macro_models = read(ROOT / 'testdata/full_scope_20261105/sram_cacti/verification.json')['models']
    reference_areas = []
    for name, large, small in [('mapping_full', 20, 0), ('mapping_trim', 16, 8)]:
        design = read(base / name / 'mapped.json')
        cells = design['modules']['kwt_input16_icb_top']['cells']
        usage = Counter(cell['type'] for cell in cells.values())
        assert usage.pop('kwt_tech_sram_4096x16', 0) == large
        assert usage.pop('kwt_tech_sram_1024x16', 0) == small
        logic_area = sum(areas[cell] * number for cell, number in usage.items()) / 1e6
        macro_area = large * macro_models['4096x16']['area_mm2'] + small * macro_models['1024x16']['area_mm2']
        total = reports[name]['complete_counted_area_open_reference_mm2']
        assert abs(logic_area + macro_area - total) < 1e-12
        reference_areas.append(total)
        del cells, design
    assert reference_areas[1] < reference_areas[0]
    ledger = read(base / 'metrics/metrics.json')
    assert all(row['SoC_average_power_mW'] is None for row in ledger['candidates'])
    assert all(row['complete_counted_area_mm2'] is None for row in ledger['candidates'])

    docs = ROOT.parent / 'docs/architecture'
    previous = ROOT / 'testdata/full_scope_20261105/delivery'
    for name, digest in read(previous / 'source_bindings.json').items():
        path = ROOT / name
        if name in ('../docs/architecture/README.md', '../docs/architecture/IMPLEMENTATION_ROADMAP.md'):
            path = out / 'previous_navigation' / Path(name).name
        assert sha(path) == digest, name
    for filename in ('manifest.json', 'source_bindings.json'):
        bind(previous / filename)
    for filename in ('INPUT16_E203_PPA_20261105.md', 'README.md', 'IMPLEMENTATION_ROADMAP.md'):
        bind(docs / filename)
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT.parent / 'e203_hbirdv2', text=True).strip()
    patch = subprocess.check_output(['git', 'diff', '--numstat', '--', 'kws_streaming/data/input_data.py'], cwd=ROOT, text=True)
    assert patch.split()[:2] == ['3', '3']
    for name in ('e203', 'trim2_e203'):
        for filename in ('model/Vreference_top', 'firmware.elf', 'firmware.bin'):
            bind(base / name / filename)
    for folder in ('trim_native', 'trim_e203', 'sta_full'):
        bind(base / folder / ('execution.log' if folder == 'sta_full' else 'build.log'))
    bind(Path(__file__))
    assert sum(codes.values()) == 494208, codes
    result = dict(passed=True, evidence_files=sum(c[0] for c in counts), source_bindings=sum(c[1] for c in counts),
                  independent_integer_codes=dict(codes), mismatches=0, same_cpu_window=True,
                  full_reference_areas_mm2=reference_areas, bank_activity_scope_verified=True,
                  official_area_timing_and_SoC_power_pending=True)
    (out / 'verification.json').write_text(json.dumps(result, indent=2))
    (out / 'source_bindings.json').write_text(json.dumps(bound, indent=2))
    manifest = {p.relative_to(out).as_posix(): sha(p) for p in out.rglob('*')
                if p.is_file() and p.name != 'manifest.json'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
