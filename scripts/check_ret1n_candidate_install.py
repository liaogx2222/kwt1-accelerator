"""Verify a fresh source-only candidate and reject stale/unsafe inputs."""
import argparse
import ast
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zlib
from install_ret1n_reset_candidate import create

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bundle', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--base-bundle', type=Path)
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise ValueError('fresh output required')
    out.mkdir(parents=True)
    bundle = a.bundle.resolve()
    m = json.loads((bundle/'transfer_manifest.json').read_text())
    capsule = bundle/'ret1n_reset_fix'
    lines = (bundle/'commands.csh.txt').read_text().splitlines()
    parts = [re.search(r"write\('([^']+)'\)", l).group(1) for l in lines[:m['parts']]]
    data = zlib.decompress(base64.b64decode(''.join(parts)))
    assert data == (bundle/'ret1n_reset_fix.tar.gz').read_bytes()
    assert hashlib.sha256(data).hexdigest() == m['sha256']
    source = out/'parent'
    base = a.base_bundle.resolve()/'project' if a.base_bundle else ROOT/'deliverables/rtl_v2_python_env_project_20261111/project'
    shutil.copytree(base, source)
    (source/'build/old').mkdir(parents=True)
    (source/'build/old/never_copy').write_text('old build excluded')
    (source/'unlisted.tmp').write_text('not part of source')
    old = json.loads((source/'manifest.json').read_text())
    before = {n: sha(source/n) for n in old['files']}
    with contextlib.redirect_stdout(io.StringIO()):
        target = create(source, capsule)
    assert not (target/'build').exists() and not (target/'unlisted.tmp').exists()
    assert before == {n: sha(source/n) for n in old['files']}
    new = json.loads((target/'manifest.json').read_text())
    assert len(new['files']) == m['files'] and sha(target/'manifest.json') == m['target_manifest_sha256']
    assert not (target/'flow/sram_contract_9pin.v').exists()
    for name, row in old['files'].items():
        if name.startswith(('rtl/v2/', 'rtl/micro/')) or name == 'flow/constraints.sdc':
            assert sha(target/name) == row['sha256']
    p = subprocess.run([sys.executable, str(target/'flow/project.py'), 'check'], capture_output=True, text=True)
    assert p.returncode == 0 and m['revision'] in p.stdout, p.stdout+p.stderr
    manifest_before = sha(target/'manifest.json')
    try:
        create(source, capsule)
    except SystemExit as e:
        assert 'DIRECTORY_EXISTS_OR_OUTSIDE_PARENT' in str(e)
    else:
        raise AssertionError('existing candidate overwritten')
    assert sha(target/'manifest.json') == manifest_before
    bad = out/'bad_capsule'
    shutil.copytree(capsule, bad)
    meta_path = bad/'metadata.json'
    meta = json.loads(meta_path.read_text())
    model = next(iter(meta['overrides']))
    (bad/'delta'/model).write_text('corrupt model')
    try:
        create(source, bad)
    except SystemExit as e:
        assert 'ASSET_HASH_MISMATCH' in str(e)
    else:
        raise AssertionError('corrupt delta accepted')
    (source/'rtl/v2/kwt_math.sv').write_text('source drift')
    try:
        create(source, capsule)
    except SystemExit as e:
        assert 'PARENT_SOURCE_MISMATCH' in str(e)
    else:
        raise AssertionError('source drift accepted')
    ast.parse((capsule/'install.py').read_text(), feature_version=(3, 6))
    result = dict(passed=True, copied_verified_source_only=True, old_build_excluded=True,
        parent_unchanged=True, numerical_RTL_unchanged=True, original_SDC_unchanged=True,
        manifest_matches_target=True, fresh_project_source_check=True, existing_candidate_refused=True,
        corrupt_delta_rejected=True, source_drift_rejected=True, transfer_reconstruction=True,
        python36=True, real_vendor_macro_or_synthesis_executed=False)
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
