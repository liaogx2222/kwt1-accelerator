"""Python 3.6: materialize isolated projects from a verified base and asset pool."""
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha(data):
    return hashlib.sha256(data).hexdigest()


def install(base, capsule):
    base = base.resolve()
    meta = json.loads((capsule/'install.json').read_text())
    raw = (base/'manifest.json').read_bytes()
    if sha(raw) != meta['base_manifest_sha256']:
        raise SystemExit('PARALLEL_BASE_MANIFEST_MISMATCH')
    pool = {}
    for name, row in json.loads(raw)['files'].items():
        data = (base/name).read_bytes()
        if sha(data) != row['sha256']:
            raise SystemExit('PARALLEL_BASE_SOURCE_MISMATCH '+name)
        pool[row['sha256']] = data
    for h, length in meta['assets'].items():
        if len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
            raise SystemExit('PARALLEL_ASSET_KEY_REJECTED')
        data = (capsule/'assets'/h).read_bytes()
        if sha(data) != h or len(data) != length:
            raise SystemExit('PARALLEL_ASSET_HASH_MISMATCH '+h)
        pool[h] = data
    planned = {}
    for name, row in meta['files'].items():
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or name.startswith('/'):
            raise SystemExit('PARALLEL_TARGET_PATH_REJECTED')
        data = pool[row['sha256']]
        if len(data) != row['bytes']:
            raise SystemExit('PARALLEL_FILE_SIZE_MISMATCH '+name)
        planned[name] = data
    name = meta['directory']
    if '/' in name or '\\' in name or not name.startswith('kwt_parallel_max_20261112_'):
        raise SystemExit('PARALLEL_DIRECTORY_REJECTED')
    target = (base.parent/name).resolve()
    if target.parent != base.parent or target.exists():
        raise SystemExit('PARALLEL_TARGET_EXISTS_OR_OUTSIDE_PARENT '+str(target))
    target.mkdir()
    for name, data in planned.items():
        path = target/name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
    print('KWT_PARALLEL_BATCH_INSTALLED '+str(target))
    print('KWT_PARALLEL_SCOPE accelerator_partition_only hold_remediation_OFF original_tasks_untouched')
    return target


if __name__ == '__main__':
    install(Path.cwd(), Path(__file__).resolve().parent)
