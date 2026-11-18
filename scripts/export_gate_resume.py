"""Small ASCII VNC transfer; install outside the frozen production file table."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    out = args.output.resolve()
    if out.exists():
        raise ValueError('fresh output required')
    data = (ROOT/'scripts/install_gate_resume.py').read_bytes().replace(b'\r\n', b'\n')
    h = hashlib.sha256(data).hexdigest()
    encoded = base64.b64encode(zlib.compress(data, 9)).decode()
    parts = [encoded[i:i+800] for i in range(0, len(encoded), 800)]
    folder = 'vnc_gate_resume_20261112'
    commands = ['mkdir '+folder]
    for i, part in enumerate(parts):
        commands.append('python3 -c "open(\'%s/part%04d\',\'w\').write(\'%s\')"' % (folder, i, part))
    commands.append('python3 -c "import base64,zlib,hashlib;b=zlib.decompress(base64.b64decode(\'\'.join(open(\'%s/part%%04d\'%%i).read() for i in range(%d))));assert len(b)==%d and hashlib.sha256(b).hexdigest()==\'%s\';open(\'%s/install_gate_resume.py\',\'xb\').write(b);print(\'GATE_RESUME_TRANSFER_VERIFIED\')"' % (folder, len(parts), len(data), h, folder))
    commands.append('python3 '+folder+'/install_gate_resume.py')
    out.mkdir(parents=True)
    (out/'VNC_INSTALL.csh.txt').write_text('\n'.join(commands)+'\n', encoding='ascii')
    (out/'install_gate_resume.py').write_bytes(data)
    result = dict(source_revision=subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
                  installer_bytes=len(data), installer_sha256=h, parts=len(parts), commands=len(commands),
                  requires_source_revision='2b2dc17', changes_frozen_files=False, recompiles_model=False)
    (out/'transfer_manifest.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
