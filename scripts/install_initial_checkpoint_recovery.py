"""Python 3.6 installer; preserve parent, copy one explicit DDC to a fresh project."""
import hashlib
import json
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def create(parent, capsule):
    parent = parent.resolve()
    meta = json.loads((capsule/'metadata.json').read_text())
    raw = (parent/'manifest.json').read_bytes()
    if sha(raw) != meta['base_manifest_sha256']:
        raise SystemExit('RECOVERY_PARENT_MANIFEST_MISMATCH')
    source = json.loads(raw)
    files = {}
    for name, row in source['files'].items():
        data = (parent/name).read_bytes()
        if sha(data) != row['sha256']:
            raise SystemExit('RECOVERY_PARENT_SOURCE_MISMATCH '+name)
        files[name] = data
    tools = {}
    for name, value in meta['tools'].items():
        if name not in ['export_initial.tcl', 'run.sh', 'verify.py']:
            raise SystemExit('RECOVERY_TOOL_NAME_REJECTED')
        data = (capsule/name).read_bytes()
        if sha(data) != value:
            raise SystemExit('RECOVERY_TOOL_HASH_MISMATCH '+name)
        tools[name] = data
    checkpoint_path = parent/'build/dc/initial_mapped.ddc'
    checkpoint = checkpoint_path.read_bytes()
    if not checkpoint:
        raise SystemExit('RECOVERY_EMPTY_CHECKPOINT')
    target = parent.parent/'kwt_initialmap_2b2dc17_20261111'
    if target.exists():
        raise SystemExit('RECOVERY_TARGET_EXISTS '+str(target))
    record = dict(scope='INITIAL_MAPPING_ONLY', hold_signed_off=False,
                  source_project=str(parent), source_manifest_sha256=sha(raw),
                  source_revision=source['git_revision'], checkpoint_stage='INITIAL',
                  checkpoint_source=str(checkpoint_path), checkpoint_bytes=len(checkpoint),
                  checkpoint_sha256=sha(checkpoint), old_logs_or_other_build_files_copied=False)
    files['manifest.json'] = raw
    files['RECOVERY_INPUT.json'] = (json.dumps(record, indent=2)+'\n').encode()
    files['recovery/metadata.json'] = (capsule/'metadata.json').read_bytes()
    files['build/recovery_input/initial_mapped.ddc'] = checkpoint
    for name, data in tools.items():
        files['recovery/'+name] = data
    target.mkdir()
    for name, data in files.items():
        path = target/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print('KWT_RECOVERY_PROJECT_CREATED '+str(target))
    print('KWT_RECOVERY_CHECKPOINT_SHA256 '+record['checkpoint_sha256'])
    print('KWT_RECOVERY_SCOPE INITIAL_MAPPING_ONLY HOLD_NOT_SIGNED_OFF')
    return target


if __name__ == '__main__':
    create(Path.cwd(), Path(__file__).resolve().parent)
