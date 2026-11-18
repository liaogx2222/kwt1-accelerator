"""Python 3.6: import reference CPU with a bounded, audited reference overlay.

Run this capsule from the existing SoC project directory. Never edits source CPU.
"""
import difflib
import hashlib
import json
from pathlib import Path
import sys


def sha(data):
    return hashlib.sha256(data).hexdigest()


def import_cpu(source, project, capsule):
    metadata = json.loads((capsule/'reference.json').read_text())
    manifest_bytes = (project/'manifest.json').read_bytes()
    if sha(manifest_bytes) != metadata['project_manifest_sha256']:
        raise SystemExit('SOC_CPU_PROJECT_MANIFEST_MISMATCH')
    manifest = json.loads(manifest_bytes)
    allowed = {'core/config.v', 'core/e203_clkgate.v', 'core/e203_dtcm_ram.v',
               'core/e203_exu_decode.v', 'core/e203_itcm_ram.v'}
    overlay_names = metadata.get('overlays', {'core/config.v': 'config.v'})
    if not set(overlay_names) <= allowed or 'core/config.v' not in overlay_names:
        raise SystemExit('SOC_CPU_OVERLAY_SCOPE_REJECTED')
    overlays = {}
    for name, file in overlay_names.items():
        if file not in (name, 'config.v' if name == 'core/config.v' else name):
            raise SystemExit('SOC_CPU_OVERLAY_PATH_REJECTED')
        data = (capsule/file).read_bytes()
        if sha(data) != manifest['files']['cpu/e203/'+name]['sha256']:
            raise SystemExit('SOC_CPU_REFERENCE_CONFIG_MISMATCH '+name)
        overlays[name] = data
    planned = {}
    errors = []
    originals = {}
    for name, row in sorted(manifest['files'].items()):
        if not name.startswith('cpu/e203/'):
            continue
        relative = name[len('cpu/e203/'):]
        p = source/relative
        if not p.is_file():
            errors.append('MISSING '+str(p))
            continue
        raw = p.read_bytes()
        data = raw.replace(b'\r\n', b'\n')
        if relative in overlays:
            originals[relative] = raw
            data = overlays[relative]
        if sha(data) != row['sha256']:
            errors.append('HASH '+str(p)+' actual='+sha(data)+' expected='+row['sha256'])
            continue
        target = project/name
        if target.exists() and target.read_bytes() != data:
            errors.append('REFUSE_OVERWRITE '+str(target))
        planned[name] = data
    if errors:
        raise SystemExit('SOC_CPU_IMPORT_REJECTED\n'+'\n'.join(errors))
    if len(planned) != metadata['cpu_files'] or set(originals) != set(overlays):
        raise SystemExit('SOC_CPU_SOURCE_COUNT_MISMATCH')
    expanded = 'overlays' in metadata
    audit = project/('build/source_evidence/cpu_reference_import_v2' if expanded else
                     'build/source_evidence/cpu_reference_import')
    records = {}
    rows = {}
    for relative, original in sorted(originals.items()):
        data = overlays[relative]
        original_lf = original.replace(b'\r\n', b'\n')
        diff = ''.join(difflib.unified_diff(
            original_lf.decode('utf-8', errors='replace').splitlines(True),
            data.decode('utf-8').splitlines(True),
            fromfile='server-source/'+relative, tofile='validated-reference/'+relative))
        records['source/'+relative if expanded else 'source.config.v'] = original
        records['diff/'+relative+'.diff' if expanded else 'config.diff'] = diff.encode('utf-8')
        rows[relative] = dict(changed=original_lf != data,
            source_raw_sha256=sha(original), source_LF_sha256=sha(original_lf),
            imported_sha256=sha(data))
    records['import.json'] = (json.dumps(dict(source=str(source.resolve()),
        reference_cpu_revision=manifest['cpu_revision'], overlays=rows,
        cpu_files=len(planned), project_manifest_sha256=sha(manifest_bytes)),
        indent=2)+'\n').encode('utf-8')
    for name, data in records.items():
        if (audit/name).exists() and (audit/name).read_bytes() != data:
            raise SystemExit('SOC_CPU_AUDIT_REFUSE_OVERWRITE '+str(audit/name))
    # Only write after validating ALL source, destination, and audit files.
    audit.mkdir(parents=True, exist_ok=True)
    for name, data in records.items():
        (audit/name).parent.mkdir(parents=True, exist_ok=True)
        (audit/name).write_bytes(data)
    for name, data in planned.items():
        target = project/name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
    if expanded:
        print('SOC_CPU_IMPORTED_VERIFIED files=%d reference_files=%d changed_files=%d source_untouched=1' %
              (len(planned), len(rows), sum(int(r['changed']) for r in rows.values())))
    else:
        print('SOC_CPU_IMPORTED_VERIFIED files=%d config_overlay=%d source_untouched=1' %
              (len(planned), int(rows['core/config.v']['changed'])))
    print('SOC_CPU_IMPORT_AUDIT '+str(audit/'import.json'))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: python3 cpu_reference/import_cpu.py <source rtl/e203>')
    import_cpu(Path(sys.argv[1]), Path.cwd(), Path(__file__).resolve().parent)
