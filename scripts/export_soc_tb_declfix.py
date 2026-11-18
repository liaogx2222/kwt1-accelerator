"""Export the small VCS declaration-order patch for the frozen SoC project."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import zlib
from export_clean_project import archive
from apply_soc_tb_declfix import updated_manifest

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    if a.output.exists():
        raise ValueError('fresh output required')
    relative = 'rtl/soc_joint/tb_soc_joint.sv'
    if subprocess.check_output(['git', 'status', '--porcelain', '--', relative], cwd=ROOT):
        raise ValueError('commit testbench before exporting')
    revision = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', relative], cwd=ROOT, text=True).strip()
    old = (ROOT/'deliverables/soc_joint_resetguard_20261111/project/manifest.json').read_bytes()
    tb = (ROOT/relative).read_bytes().replace(b'\r\n', b'\n')
    new = updated_manifest(old, tb, revision)
    meta = dict(revision=revision, base_manifest_sha256=sha(old),
                new_manifest_sha256=sha(new), new_tb_sha256=sha(tb))
    files = {'tb_declfix/apply.py': (ROOT/'scripts/apply_soc_tb_declfix.py').read_bytes().replace(b'\r\n', b'\n'),
             'tb_declfix/tb_soc_joint.sv': tb,
             'tb_declfix/patch.json': (json.dumps(meta, indent=2)+'\n').encode()}
    data = archive(files)
    encoded = base64.b64encode(zlib.compress(data, 9)).decode()
    parts = [encoded[i:i+800] for i in range(0, len(encoded), 800)]
    commands = ['python3 -c "open(\'tb_declfix.part%04d\',\'w\').write(\'%s\')"' % (i, p) for i, p in enumerate(parts)]
    commands.append('python3 -c "import base64,zlib,hashlib;b=zlib.decompress(base64.b64decode(\'\'.join(open(\'tb_declfix.part%%04d\'%%i).read() for i in range(%d))));assert len(b)==%d and hashlib.sha256(b).hexdigest()==\'%s\';open(\'tb_declfix.tar.gz\',\'wb\').write(b);print(\'SOC_TB_DECLFIX_TRANSFER_OK\')"' % (len(parts), len(data), sha(data)))
    commands += ['tar xzf tb_declfix.tar.gz', 'python3 tb_declfix/apply.py', 'python3 flow/project.py check']
    a.output.mkdir(parents=True)
    for name, payload in files.items():
        p = a.output/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload)
    (a.output/'tb_declfix.tar.gz').write_bytes(data)
    (a.output/'commands.csh.txt').write_text('\n'.join(commands)+'\n', encoding='ascii')
    report = dict(meta, bytes=len(data), sha256=sha(data), parts=len(parts))
    (a.output/'transfer_manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
