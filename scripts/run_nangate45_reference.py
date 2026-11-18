"""Map the hash-bound generic accelerator to Nangate45, preserving SRAM macros.

Reference standard-cell area only: no SRAM area, timing signoff, or SMIC40 claim.
"""
import argparse
import collections
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--generic', type=Path, default=Path('testdata/local_flow_20261103/final2/synth'))
    ap.add_argument('--native', action='store_true', help='Use native yosys/ABC on PATH (including Linux)')
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise SystemExit('Use a new output directory; previous evidence is immutable')
    rel = out.relative_to(ROOT).as_posix()
    generic = a.generic.resolve()
    prior = json.loads((generic / 'result.json').read_text())
    assert prior['passed'] and prior['stage'] == 'synth'
    for name, digest in prior['source_sha256'].items():
        assert sha(ROOT / name) == digest, name
    for name, digest in prior['evidence_sha256'].items():
        assert sha(generic / name) == digest, name
    library = ROOT / 'third_party/nangate45_reference'
    provenance = json.loads((library / 'provenance.json').read_text())
    for name, entry in provenance['files'].items():
        assert sha(library / name) == entry['sha256'], name
    lib = (library / 'lib/NangateOpenCellLibrary_typical.lib').relative_to(ROOT).as_posix()
    gpath = (generic / 'generic.json').relative_to(ROOT).as_posix()
    out.mkdir(parents=True)
    metadata_removed = 0
    if a.native:
        # Modern Yosys emits $scopeinfo hierarchy metadata unsupported by 0.33.
        # It has no ports/connections. Remove ONLY these metadata cells in a
        # separately hashed frontend copy, never edit the source/generic release.
        compatible = json.loads((generic / 'generic.json').read_text())
        for module in compatible['modules'].values():
            cells = module.get('cells', {})
            for name in list(cells):
                if cells[name]['type'] == '$scopeinfo':
                    assert not cells[name].get('connections')
                    assert not cells[name].get('port_directions')
                    del cells[name]
                    metadata_removed += 1
        (out / 'generic_compat.json').write_text(json.dumps(compatible, separators=(',', ':')))
        del compatible
        gpath = f'{rel}/generic_compat.json'
    # Same reference pin driver/load used by the upstream Nangate45 flow. These
    # are mapping assumptions, not the board or SRAM interface constraints.
    (out / 'abc.constr').write_text('set_driving_cell BUF_X1\nset_load 3.898\n')
    # Yosys 0.33 has no abc -dont_use option. The library's own dont_use
    # attributes still apply; extra ORFS congestion exclusions are optional
    # and are reported separately for this logical-only reference.
    exclusions = '' if a.native else ' -dont_use AOI211_X1 -dont_use OAI211_X1'
    script = f'''read_json {gpath}
read_liberty -lib {lib}
hierarchy -check -top kwt1_mmio
dfflibmap -liberty {lib}
abc -liberty {lib} -constr {rel}/abc.constr -D 6667{exclusions}
clean
check -assert
tee -o {rel}/stat.json stat -json -liberty {lib} -top kwt1_mmio
write_json {rel}/mapped.json
write_verilog -noattr -noexpr {rel}/mapped.v
'''
    (out / 'map.ys').write_text(script)
    engine = [shutil.which('yosys')] if a.native else [sys.executable, 'scripts/run_yosys_v2.py']
    assert all(engine), 'Yosys unavailable'
    command = [*engine, '-Q', '-T', '-l', f'{rel}/yosys.log', '-s', f'{rel}/map.ys']
    started = time.time()
    with (out / 'console.log').open('w', encoding='utf-8') as log:
        proc = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if proc.returncode:
        raise SystemExit(f'Mapping failed ({proc.returncode}); inspect {out / "console.log"}')
    net = json.loads((out / 'mapped.json').read_text())
    cells = net['modules']['kwt1_mmio']['cells']
    counts = collections.Counter(c['type'] for c in cells.values())
    assert counts.pop('kwt_tech_sram_4096x16', 0) == 20
    libtext = (ROOT / lib).read_text()
    areas = {name: float(area) for name, area in re.findall(r'cell\s*\(\s*(\w+)\s*\)\s*\{.*?area\s*:\s*([\d.]+)', libtext, re.S)}
    assert set(counts) <= set(areas), ('Unmapped/unknown cells', set(counts) - set(areas))
    area = sum(count * areas[name] for name, count in counts.items())
    stat = json.loads((out / 'stat.json').read_text())
    yosys_area = stat['modules']['\\kwt1_mmio']['area']
    assert abs(area - yosys_area) < 0.02, (area, yosys_area)
    sequential = sum(n for name, n in counts.items() if name.startswith(('DFF', 'SDFF', 'DLH', 'DLL')))
    report = dict(mapping_passed=True, technology='Nangate45 non-manufacturable reference',
                  top='kwt1_mmio', library_corner='typical, 1.10 V, 25 C',
                  standard_cell_count=sum(counts.values()), sequential_cell_count=sequential,
                  standard_cell_area_um2=area, standard_cell_area_mm2=area / 1e6,
                  sram_macros=20, sram_shape='4096x16 single-port', sram_area=None,
                  total_area=None, timing_signoff=False, physical_signoff=False,
                  smic40_signoff=False, power=None, mapped_functional_equivalence='pending',
                  abc_delay_target_ps=6667, elapsed_seconds=time.time() - started,
                  extra_ORFS_congestion_exclusions=not a.native,
                  frontend_scope_metadata_removed=metadata_removed,
                  counts=dict(sorted(counts.items())), command=command,
                  generic_source_manifest=prior['source_sha256'],
                  generic_json_sha256=sha(generic / 'generic.json'), library=provenance,
                  script_sha256=sha(Path(__file__)),
                  tool_sha256={str(p): sha(p) for p in
                               ([Path(engine[0]), Path(shutil.which('yosys-abc') or shutil.which('berkeley-abc'))] if a.native else
                                [ROOT / 'scripts/run_yosys_v2.py', ROOT / 'tools/rtl_v2_python/yowasp_yosys/yosys.wasm'])})
    for name, digest in prior['source_sha256'].items():
        assert sha(ROOT / name) == digest, 'Source changed during mapping: ' + name
    (out / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    evidence = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    (out / 'manifest.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps({k: report[k] for k in ['mapping_passed', 'standard_cell_count', 'standard_cell_area_um2', 'sram_macros', 'elapsed_seconds']}, indent=2))


if __name__ == '__main__':
    main()
