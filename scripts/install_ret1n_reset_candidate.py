"""Python 3.6: materialize a fresh candidate from verified source plus delta.

No old netlist, build directory, tool cache or SAIF is copied.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def sha(data):
    return hashlib.sha256(data).hexdigest()


def create(root, capsule):
    root = root.resolve()
    meta = json.loads((capsule/'metadata.json').read_text())
    raw = (root/'manifest.json').read_bytes()
    if sha(raw) != meta['base_manifest_sha256']:
        raise SystemExit('CANDIDATE_PARENT_MANIFEST_MISMATCH')
    old = json.loads(raw)
    planned = {}
    for name, row in old['files'].items():
        data = (root/name).read_bytes()
        if sha(data) != row['sha256']:
            raise SystemExit('CANDIDATE_PARENT_SOURCE_MISMATCH '+name)
        planned[name] = data
    for key in ['numerical_contract', 'private_macros', 'private_sram_bytes']:
        if meta['target_header'][key] != old[key]:
            raise SystemExit('CANDIDATE_NUMERICAL_OR_MEMORY_CONTRACT_CHANGED '+key)
    for name in meta['removed']:
        del planned[name]
    for name, row in meta['overrides'].items():
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts:
            raise SystemExit('CANDIDATE_ASSET_PATH_REJECTED')
        data = (capsule/'delta'/name).read_bytes()
        if len(data) != row['bytes'] or sha(data) != row['sha256']:
            raise SystemExit('CANDIDATE_ASSET_HASH_MISMATCH '+name)
        planned[name] = data
    for name, row in old['files'].items():
        if name.startswith(('rtl/v2/', 'rtl/micro/')) or name == 'flow/constraints.sdc':
            if name not in planned or sha(planned[name]) != row['sha256']:
                raise SystemExit('CANDIDATE_PROTECTED_SOURCE_CHANGED '+name)
    manifest = dict(meta['target_header'])
    manifest['files'] = {n: dict(bytes=len(b), sha256=sha(b)) for n, b in sorted(planned.items())}
    encoded = (json.dumps(manifest, indent=2, sort_keys=True)+'\n').encode('utf-8')
    if sha(encoded) != meta['target_manifest_sha256']:
        raise SystemExit('CANDIDATE_TARGET_MANIFEST_MISMATCH')
    name = meta['directory']
    if not re.match(r'^kwt_ret1n_reset_[0-9a-f]{7}_20261111$', name):
        raise SystemExit('CANDIDATE_DIRECTORY_REJECTED')
    target = (root.parent/name).resolve()
    if target.parent != root.parent or target == root or target.exists():
        raise SystemExit('CANDIDATE_DIRECTORY_EXISTS_OR_OUTSIDE_PARENT '+str(target))
    target.mkdir()
    for name, data in planned.items():
        p = target/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (target/'manifest.json').write_bytes(encoded)
    origin = dict(parent=str(root), parent_manifest_sha256=sha(raw),
                  target_manifest_sha256=sha(encoded), removed=meta['removed'],
                  replaced_or_added=sorted(meta['overrides']), old_build_copied=False,
                  numerical_RTL_unchanged=True)
    (target/'SOURCE_PARENT.json').write_text(json.dumps(origin, indent=2)+'\n')
    print('KWT_CANDIDATE_CREATED '+str(target))
    print('KWT_CANDIDATE_SOURCE files=%d revision=%s' % (len(planned), manifest['git_revision']))
    return target


if __name__ == '__main__':
    create(Path.cwd(), Path(__file__).resolve().parent)
