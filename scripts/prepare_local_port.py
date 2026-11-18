"""Export a relative-path, technology-neutral handoff without altering releases.

Only Python's standard library is required. This is a source/fixture export,
not a physical design run or an assertion that SMIC libraries are available.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(base, mapping):
    for name, digest in mapping.items():
        if sha(base / name) != digest:
            raise ValueError(f'Source/evidence hash mismatch: {name}')


def check_target(path):
    cfg = read(path)
    missing = []
    for key in ['standard_cell_liberty', 'sram_liberty', 'sram_simulation_models',
                'sram_wrapper_rtl', 'pvt_corners', 'io_constraints_sdc',
                'sram_area_per_instance_um2']:
        if not cfg.get(key):
            missing.append(key)
    for key in ['standard_cell_liberty', 'sram_liberty', 'sram_simulation_models',
                'sram_wrapper_rtl', 'io_constraints_sdc']:
        values = cfg.get(key) or []
        if isinstance(values, str):
            values = [values]
        for value in values:
            file = Path(value)
            if not file.is_absolute():
                file = path.parent / file
            if not file.is_file():
                missing.append(f'{key}: file not found: {value}')
    print(json.dumps({'target': cfg['target'], 'required_files_and_fields_present': not missing,
                      'missing': missing, 'physical_signoff': False,
                      'scope': 'presence check only; no library/model/constraint semantics validated'}, indent=2))
    return 2 if missing else 0


def export(destination):
    release = ROOT / 'testdata/integration_v1/release'
    base = ROOT / 'testdata/rtl_v2/release'
    result = read(release / 'verification.json')
    if not result['passed']:
        raise ValueError('Integration closure must pass before export')
    verify(release, read(release / 'evidence_manifest.json')['sha256'])
    verify(ROOT, read(release / 'source_manifest.json'))
    verify(ROOT, read(base / 'source_manifest.json'))
    if destination.exists():
        raise ValueError('Choose a new output directory; published exports are not overwritten')
    files = {'rtl/v2/files.f', 'rtl/v2/generated/kwt_profile.svh', 'rtl/v2/generated/profile.json',
             'rtl/v2/clock_template.sdc', 'rtl/v2/kwt_tech_sram_blackbox.sv',
             'rtl/integration/tech_sram_model.sv', 'rtl/integration/tb_mmio.sv',
             'rtl/integration/tb_sram.sv', 'rtl/integration/INTERFACE_CONTRACT.md',
             'rtl/integration/test_initial_bus_failure.cpp', 'rtl/v2/requirements.lock',
             'flow/targets/smic40.pending.json', 'flow/README.md',
             'scripts/prepare_local_port.py'}
    for line in (ROOT / 'rtl/v2/files.f').read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('+'):
            files.add(line)
    for path in (ROOT / 'rtl/integration/driver').glob('*'):
        if path.is_file():
            files.add(path.relative_to(ROOT).as_posix())
    # Check all inputs before writing the bundle.
    for relative in files:
        if not (ROOT / relative).is_file():
            raise FileNotFoundError(relative)
    fixtures = release / 'candidate_system'
    packets = read(ROOT / 'rtl/v2/generated/profile.json')['packets']
    for name, digest in packets.items():
        data = b''.join(int(x, 16).to_bytes(4, 'little') for x in (fixtures / (name + '.hex')).read_text().split())
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'Packet digest mismatch: {name}')
    destination.mkdir(parents=True)
    for relative in sorted(files):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    fixture_out = destination / 'fixtures'
    fixture_out.mkdir()
    for path in fixtures.iterdir():
        if path.suffix == '.hex' and path.name.startswith(('input_', 'expected_', 'common.bin', 'layer_')) or path.name in ['cases.json', 'cases.txt']:
            shutil.copyfile(path, fixture_out / path.name)
    provenance = {
        'hardware': 'rtl/v2', 'driver': 'rtl/integration/driver',
        'integer_profile': 'INTEGER_NUMERICS_V1', 'target': 'SMIC 40nm (unbound)',
        'integration_verification_sha256': sha(release / 'verification.json'),
        'integration_manifest_sha256': sha(release / 'evidence_manifest.json'),
        'hardware_manifest_sha256': sha(base / 'source_manifest.json'),
        'formal_equivalence': False, 'physical_signoff': False,
        'fixtures_scope': 'Frozen Validation development cases, host verification only; not DUT ROM',
    }
    (destination / 'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    mapping = {p.relative_to(destination).as_posix(): sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    (destination / 'manifest.json').write_text(json.dumps({'sha256': mapping}, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(destination), 'files': len(mapping), 'packet_hashes_verified': len(packets),
                      'local_compile': 'iverilog -g2012 -s kwt1_mmio -o smoke.vvp -f rtl/v2/files.f',
                      'target_library_bound': False}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path)
    group.add_argument('--check-target', type=Path)
    args = parser.parse_args()
    if args.check_target:
        raise SystemExit(check_target(args.check_target.resolve()))
    export(args.output.resolve())
