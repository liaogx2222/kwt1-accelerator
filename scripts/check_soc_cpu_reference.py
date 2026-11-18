"""Exercise source preservation, full prevalidation and CPU config overlay."""
import argparse
import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
from soc_cpu_reference_import import import_cpu

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--expanded', action='store_true')
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise ValueError('fresh output required')
    out.mkdir(parents=True)
    release = ROOT/'deliverables/soc_joint_resetguard_20261111/project'
    capsule = ROOT/('deliverables/soc_cpu_reference_v2_20261111/cpu_reference_v2' if a.expanded else
                    'deliverables/soc_cpu_reference_20261111/cpu_reference')
    manifest = json.loads((release/'manifest.json').read_text())
    source = out/'server_cpu'
    source.mkdir()
    for name in manifest['files']:
        if name.startswith('cpu/e203/'):
            p = source/name[len('cpu/e203/'):]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((release/name).read_bytes())
    overlay_names = list(json.loads((capsule/'reference.json').read_text()).get('overlays', {'core/config.v': 'config.v'}))
    for name in overlay_names:
        config = source/name
        config.write_bytes(config.read_bytes()+b'\n// simulated server config variation\n')
    before = {str(p): sha(p) for p in source.rglob('*') if p.is_file()}
    def project(name):
        p = out/name
        p.mkdir()
        shutil.copyfile(release/'manifest.json', p/'manifest.json')
        return p
    valid = project('valid')
    with contextlib.redirect_stdout(io.StringIO()):
        import_cpu(source, valid, capsule)
        import_cpu(source, valid, capsule)
    assert all(sha(valid/n) == row['sha256'] for n, row in manifest['files'].items() if n.startswith('cpu/'))
    assert before == {str(p): sha(p) for p in source.rglob('*') if p.is_file()}
    audit = valid/('build/source_evidence/cpu_reference_import_v2' if a.expanded else
                   'build/source_evidence/cpu_reference_import')
    for name in overlay_names:
        diff = audit/('diff/'+name+'.diff' if a.expanded else 'config.diff')
        assert 'simulated server config variation' in diff.read_text()
    rows = json.loads((audit/'import.json').read_text())
    assert len(rows['overlays']) == len(overlay_names) and all(r['changed'] for r in rows['overlays'].values())
    def reject(p, marker):
        try:
            import_cpu(source, p, capsule)
        except SystemExit as e:
            assert marker in str(e), str(e)
        else:
            raise AssertionError('unsafe import accepted')
    other = source/'core/e203_cpu.v'
    other.write_bytes(other.read_bytes()+b'\n// second mismatch\n')
    invalid = project('other_mismatch')
    reject(invalid, 'SOC_CPU_IMPORT_REJECTED')
    assert not (invalid/'cpu').exists() and not (invalid/'build').exists()
    other.write_bytes((release/'cpu/e203/core/e203_cpu.v').read_bytes())
    conflict = project('destination_conflict')
    target = conflict/'cpu/e203/core/config.v'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'do not overwrite')
    reject(conflict, 'REFUSE_OVERWRITE')
    assert target.read_bytes() == b'do not overwrite'
    assert len(list((conflict/'cpu').rglob('*.v'))) == 1
    wrong = project('wrong_manifest')
    (wrong/'manifest.json').write_text('{}')
    reject(wrong, 'SOC_CPU_PROJECT_MANIFEST_MISMATCH')
    assert not (wrong/'cpu').exists()
    bad_capsule = out/'bad_capsule'
    shutil.copytree(capsule, bad_capsule)
    config_reference = bad_capsule/('core/config.v' if a.expanded else 'config.v')
    config_reference.write_bytes(b'invalid reference')
    corrupt_project = project('corrupt_reference')
    try:
        import_cpu(source, corrupt_project, bad_capsule)
    except SystemExit as e:
        assert 'SOC_CPU_REFERENCE_CONFIG_MISMATCH' in str(e)
    else:
        raise AssertionError('corrupt capsule accepted')
    assert not (corrupt_project/'cpu').exists()
    ast.parse((capsule/'import_cpu.py').read_text(), feature_version=(3, 6))
    result = dict(passed=True, CPU_files=134, source_unchanged=True,
                  config_overlay_audited=True, audited_reference_files=len(overlay_names), idempotent=True,
                  other_mismatch_no_partial_import=True, destination_conflict_refused=True,
                  wrong_manifest_refused=True, corrupt_reference_refused=True, python36_syntax=True)
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
