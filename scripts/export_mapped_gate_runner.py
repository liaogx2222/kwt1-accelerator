"""Make a small VNC installer; keep the mapped baseline and source proof intact."""
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
    ap.add_argument('--output', required=True, type=Path)
    a = ap.parse_args()
    if a.output.exists():
        raise ValueError('fresh output required')
    base = ROOT/'deliverables/rtl_v2_python_env_project_20261111/project'
    runner = (ROOT/'flow/review/run_mapped_gate.sh').read_bytes().replace(b'\r\n', b'\n')
    metadata = dict(source_manifest_sha256=sha((base/'manifest.json').read_bytes()), runner_sha256=sha(runner))
    files = {'mapped_gate_fix/install.py': (ROOT/'scripts/install_mapped_gate_runner.py').read_bytes().replace(b'\r\n', b'\n'),
             'mapped_gate_fix/run_mapped_gate.sh': runner,
             'mapped_gate_fix/metadata.json': (json.dumps(metadata, indent=2)+'\n').encode()}
    data = archive(files)
    encoded = base64.b64encode(zlib.compress(data, 9)).decode()
    parts = [encoded[i:i+800] for i in range(0, len(encoded), 800)]
    commands = ['python3 -c "open(\'mapped_gate.part%04d\',\'w\').write(\'%s\')"' % (i, p) for i, p in enumerate(parts)]
    commands.append('python3 -c "import base64,zlib,hashlib;b=zlib.decompress(base64.b64decode(\'\'.join(open(\'mapped_gate.part%%04d\'%%i).read() for i in range(%d))));assert len(b)==%d and hashlib.sha256(b).hexdigest()==\'%s\';open(\'mapped_gate_fix.tar.gz\',\'wb\').write(b);print(\'MAPPED_GATE_TRANSFER_OK\')"' % (len(parts), len(data), sha(data)))
    commands += ['tar xzf mapped_gate_fix.tar.gz', 'python3 mapped_gate_fix/install.py']
    a.output.mkdir(parents=True)
    for name, payload in files.items():
        p = a.output/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload)
    (a.output/'mapped_gate_fix.tar.gz').write_bytes(data)
    (a.output/'commands.csh.txt').write_text('\n'.join(commands)+'\n', encoding='ascii')
    report = dict(metadata, bytes=len(data), sha256=sha(data), parts=len(parts))
    (a.output/'transfer_manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
