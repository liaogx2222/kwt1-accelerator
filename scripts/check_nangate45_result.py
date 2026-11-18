"""Independent mapped-cell/LEF/provenance audit and native compile smoke."""
import argparse
import collections
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mapping', type=Path, required=True)
    ap.add_argument('--math', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    base, math, out = a.mapping.resolve(), a.math.resolve(), a.output.resolve()
    assert not out.exists(), 'Use new output'
    out.mkdir(parents=True)
    for directory in [base, math]:
        for name, digest in read(directory / 'manifest.json').items():
            assert sha(directory / name) == digest, name
    result = read(base / 'summary.json')
    assert result['mapping_passed']
    for name, digest in result['generic_source_manifest'].items():
        assert sha(ROOT / name) == digest, name
    libdir = ROOT / 'third_party/nangate45_reference'
    lib = libdir / 'lib/NangateOpenCellLibrary_typical.lib'
    assert sha(lib) == result['library']['files']['lib/NangateOpenCellLibrary_typical.lib']['sha256']
    areas = {name: float(area) for name, area in re.findall(
        r'cell\s*\(\s*(\w+)\s*\)\s*\{.*?area\s*:\s*([\d.]+)', lib.read_text(), re.S)}
    lef = libdir / 'lef/NangateOpenCellLibrary.macro.mod.lef'
    assert sha(lef) == read(lef.with_suffix('.provenance.json'))['sha256']
    dimensions = {name: float(x) * float(y) for name, x, y in re.findall(
        r'MACRO\s+(\w+)\s+.*?SIZE\s+([\d.]+)\s+BY\s+([\d.]+)', lef.read_text(), re.S)}
    net = read(base / 'mapped.json')['modules']['kwt1_mmio']
    counts = collections.Counter(c['type'] for c in net['cells'].values())
    macros = counts.pop('kwt_tech_sram_4096x16')
    assert macros == 20 and set(counts) <= set(areas)
    assert set(counts) <= set(dimensions)
    assert not any('LATCH' in name.upper() or name.startswith(('DLH', 'DLL', 'TLAT')) for name in counts)
    assert all(abs(areas[name] - dimensions[name]) < 1e-6 for name in counts)
    assert counts.get('FILLCELL_X2', 0) == 0
    area_lib = sum(count * areas[name] for name, count in counts.items())
    area_lef = sum(count * dimensions[name] for name, count in counts.items())
    assert abs(area_lib - result['standard_cell_area_um2']) < 0.02
    # Compile the actual complete mapped top using the same functional library
    # and SRAM contract. This is elaboration only, not a task simulation.
    command = [shutil.which('iverilog'), '-g2012', '-s', 'kwt1_mmio', '-o', str(out / 'mapped_compile.vvp'),
               str(base / 'mapped.v'), str(math / 'functional_cells.v'),
               str(ROOT / 'rtl/integration/tech_sram_model.sv')]
    p = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (out / 'compile.log').write_text(p.stdout + p.stderr)
    assert p.returncode == 0, p.stderr[-2000:]
    # Compare the modern generic input against the old-frontend copy, removing
    # ONLY zero-port metadata in both. Hardware logic must compare identically.
    original = read(ROOT / 'testdata/local_flow_20261103/final2/synth/generic.json')
    compatible = read(base / 'generic_compat.json')
    removed = 0
    for module in original['modules'].values():
        for name in list(module.get('cells', {})):
            cell = module['cells'][name]
            if cell['type'] == '$scopeinfo':
                assert not cell.get('connections') and not cell.get('port_directions')
                del module['cells'][name]
                removed += 1
    assert original == compatible
    summary = dict(passed=True, mapped_top_compile=True, standard_cell_count=sum(counts.values()),
                   standard_cell_area_um2_liberty=area_lib, standard_cell_area_um2_lef=area_lef,
                   standard_cell_area_mm2=area_lib / 1e6, sram_macros=macros,
                   metadata_only_frontend_changes=removed, source_hardware_unchanged=True,
                   unused_library_discrepancies={name: dict(liberty=areas[name], lef=dimensions[name])
                                                for name in areas if abs(areas[name] - dimensions[name]) > 1e-6},
                   total_area=None, macro_area=None, physical_signoff=False,
                   full_mapped_task_simulation=False, formal_equivalence=False,
                   math_vectors_passed=read(math / 'summary.json')['mapped_math_vectors'],
                   mapped_summary_sha256=sha(base / 'summary.json'), lef_sha256=sha(lef),
                   compile_command=command, script_sha256=sha(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2))
    (out / 'manifest.json').write_text(json.dumps({p.name: sha(p) for p in out.iterdir() if p.is_file()}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
