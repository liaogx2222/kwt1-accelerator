"""Export the independent, source-bound diagnostic review installer."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import zlib
from export_clean_project import archive
from pt_review_install import make_pt, make_dc, make_runner

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
    tools = {'pt_review.tcl': make_pt((base/'flow/pt.tcl').read_text()).encode(),
             'dc_mapped_review.tcl': make_dc().encode(), 'run_pt_review.sh': make_runner().encode()}
    metadata = dict(source_manifest_sha256=sha((base/'manifest.json').read_bytes()),
                    review_sha256={n: sha(b) for n, b in tools.items()})
    files = {'pt_review_fix/install.py': (ROOT/'scripts/pt_review_install.py').read_bytes().replace(b'\r\n', b'\n'),
             'pt_review_fix/metadata.json': (json.dumps(metadata, indent=2)+'\n').encode()}
    data = archive(files)
    encoded = base64.b64encode(zlib.compress(data, 9)).decode()
    parts = [encoded[i:i+800] for i in range(0, len(encoded), 800)]
    commands = ['python3 -c "open(\'pt_review.part%04d\',\'w\').write(\'%s\')"' % (i, p) for i, p in enumerate(parts)]
    commands.append('python3 -c "import base64,zlib,hashlib;b=zlib.decompress(base64.b64decode(\'\'.join(open(\'pt_review.part%%04d\'%%i).read() for i in range(%d))));assert len(b)==%d and hashlib.sha256(b).hexdigest()==\'%s\';open(\'pt_review_fix.tar.gz\',\'wb\').write(b);print(\'PT_REVIEW_TRANSFER_OK\')"' % (len(parts), len(data), sha(data)))
    commands += ['tar xzf pt_review_fix.tar.gz', 'python3 pt_review_fix/install.py']
    a.output.mkdir(parents=True)
    for name, payload in files.items():
        p = a.output/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload)
    for name, payload in tools.items():
        p = a.output/'generated'/name
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(payload)
    (a.output/'pt_review_fix.tar.gz').write_bytes(data)
    (a.output/'commands.csh.txt').write_text('\n'.join(commands)+'\n', encoding='ascii')
    report = dict(metadata, bytes=len(data), sha256=sha(data), parts=len(parts))
    (a.output/'transfer_manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
