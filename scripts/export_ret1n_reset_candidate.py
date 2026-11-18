"""Small VNC delta installer for the fresh RET1N/reset-distribution project."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import zlib
from export_clean_project import archive

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target-bundle', required=True, type=Path)
    ap.add_argument('--base-bundle', type=Path, help='existing verified candidate to use as source parent')
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--allow-dirty', action='store_true')
    a = ap.parse_args()
    if a.output.exists():
        raise ValueError('fresh output required')
    base = a.base_bundle.resolve()/'project' if a.base_bundle else ROOT/'deliverables/rtl_v2_python_env_project_20261111/project'
    target = a.target_bundle.resolve()/'project'
    old_raw = (base/'manifest.json').read_bytes()
    old = json.loads(old_raw)
    new_raw = (target/'manifest.json').read_bytes()
    new = json.loads(new_raw)
    if new['development_dirty'] and not a.allow_dirty:
        raise ValueError('clean committed candidate required')
    overrides = {n: row for n, row in new['files'].items() if old['files'].get(n) != row}
    removed = sorted(set(old['files'])-set(new['files']))
    for n in set(overrides)|set(removed):
        if n.startswith(('rtl/v2/', 'rtl/micro/')):
            raise ValueError('numerical RTL changed: '+n)
    if old['files']['flow/constraints.sdc'] != new['files']['flow/constraints.sdc']:
        raise ValueError('original timing constraints changed')
    metadata = dict(base_manifest_sha256=sha(old_raw), target_manifest_sha256=sha(new_raw),
        target_header={k: v for k, v in new.items() if k != 'files'}, overrides=overrides,
        removed=removed, directory='kwt_ret1n_reset_'+new['git_revision'][:7]+'_20261111')
    files = {'ret1n_reset_fix/install.py': (ROOT/'scripts/install_ret1n_reset_candidate.py').read_bytes().replace(b'\r\n', b'\n'),
             'ret1n_reset_fix/metadata.json': (json.dumps(metadata, indent=2)+'\n').encode()}
    for n, row in overrides.items():
        payload = (target/n).read_bytes()
        assert sha(payload) == row['sha256']
        files['ret1n_reset_fix/delta/'+n] = payload
    data = archive(files)
    encoded = base64.b64encode(zlib.compress(data, 9)).decode()
    parts = [encoded[i:i+800] for i in range(0, len(encoded), 800)]
    commands = ['python3 -c "open(\'ret1n_reset.part%04d\',\'w\').write(\'%s\')"' % (i, p) for i, p in enumerate(parts)]
    commands.append('python3 -c "import base64,zlib,hashlib;b=zlib.decompress(base64.b64decode(\'\'.join(open(\'ret1n_reset.part%%04d\'%%i).read() for i in range(%d))));assert len(b)==%d and hashlib.sha256(b).hexdigest()==\'%s\';open(\'ret1n_reset_fix.tar.gz\',\'wb\').write(b);print(\'RET1N_RESET_TRANSFER_OK\')"' % (len(parts), len(data), sha(data)))
    commands += ['tar xzf ret1n_reset_fix.tar.gz', 'python3 ret1n_reset_fix/install.py']
    a.output.mkdir(parents=True)
    for name, payload in files.items():
        p = a.output/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload)
    (a.output/'ret1n_reset_fix.tar.gz').write_bytes(data)
    (a.output/'commands.csh.txt').write_text('\n'.join(commands)+'\n', encoding='ascii')
    report = dict(bytes=len(data), sha256=sha(data), parts=len(parts), directory=metadata['directory'],
                  revision=new['git_revision'], replaced_or_added=sorted(overrides), removed=removed,
                  files=len(new['files']), target_manifest_sha256=sha(new_raw))
    (a.output/'transfer_manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
