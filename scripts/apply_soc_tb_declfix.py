"""Python 3.6: preserve failed VCS artifacts and apply a hash-bound TB fix."""
import hashlib
import json
from pathlib import Path
import sys


def sha(data):
    return hashlib.sha256(data).hexdigest()


def updated_manifest(data, tb, revision):
    m = json.loads(data)
    m['base_revision'] = m['revision']
    m['revision'] = revision
    m['files']['soc/tb_soc_joint.sv'] = dict(bytes=len(tb), sha256=sha(tb))
    return (json.dumps(m, indent=2, sort_keys=True)+'\n').encode('utf-8')


def apply(project, capsule):
    project = project.resolve()
    meta = json.loads((capsule/'patch.json').read_text())
    original = (project/'manifest.json').read_bytes()
    tb = (capsule/'tb_soc_joint.sv').read_bytes()
    if sha(tb) != meta['new_tb_sha256']:
        raise SystemExit('SOC_TB_PATCH_PAYLOAD_MISMATCH')
    if sha(original) not in (meta['base_manifest_sha256'], meta['new_manifest_sha256']):
        raise SystemExit('SOC_TB_PATCH_SOURCE_MANIFEST_MISMATCH')
    m = json.loads(original)
    failures = [n for n, row in m['files'].items()
                if not (project/n).is_file() or sha((project/n).read_bytes()) != row['sha256']]
    if failures:
        raise SystemExit('SOC_TB_PATCH_SOURCE_MISMATCH '+', '.join(failures[:8]))
    if sha(original) == meta['new_manifest_sha256']:
        print('SOC_TB_DECLFIX_ALREADY_VERIFIED revision='+m['revision'])
        return
    if (project/'build/rtl/simv').exists():
        raise SystemExit('SOC_TB_PATCH_REFUSE_EXISTING_SIMV')
    new = updated_manifest(original, tb, meta['revision'])
    if sha(new) != meta['new_manifest_sha256']:
        raise SystemExit('SOC_TB_PATCH_TARGET_MANIFEST_MISMATCH')
    moves = []
    for name in ['case0', 'rtl']:
        source = project/'build'/name
        destination = project/'build'/(name+'_before_tb_declfix')
        for p in [source, destination]:
            if project not in p.resolve().parents or p.is_symlink():
                raise SystemExit('SOC_TB_PATCH_PATH_REJECTED '+str(p))
        if source.exists():
            if destination.exists():
                raise SystemExit('SOC_TB_PATCH_ARCHIVE_EXISTS '+str(destination))
            moves.append((source, destination))
    audit = project/'build/tb_declfix_audit'
    backups = {'base.manifest.json': original,
               'base.tb_soc_joint.sv': (project/'soc/tb_soc_joint.sv').read_bytes(),
               'patch.json': (capsule/'patch.json').read_bytes()}
    for name, data in backups.items():
        if (audit/name).exists() and (audit/name).read_bytes() != data:
            raise SystemExit('SOC_TB_PATCH_AUDIT_CONFLICT '+name)
    audit.mkdir(parents=True, exist_ok=True)
    for name, data in backups.items():
        (audit/name).write_bytes(data)
    for source, destination in moves:
        source.rename(destination)
    (project/'soc/tb_soc_joint.sv').write_bytes(tb)
    (project/'manifest.json').write_bytes(new)
    print('SOC_TB_DECLFIX_VERIFIED files=%d revision=%s archived_builds=%d' %
          (len(m['files']), meta['revision'], len(moves)))


if __name__ == '__main__':
    apply(Path.cwd(), Path(__file__).resolve().parent)
