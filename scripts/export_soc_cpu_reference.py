"""Make a small, hash-bound CPU config overlay for the 0e308fd SoC release."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import zlib
from export_clean_project import archive

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--expanded', action='store_true', help='include the five observed CPU reference files')
    a = ap.parse_args()
    if a.output.exists():
        raise ValueError('fresh output required')
    project = ROOT/'deliverables/soc_joint_resetguard_20261111/project'
    raw = (project/'manifest.json').read_bytes()
    manifest = json.loads(raw)
    config = (project/'cpu/e203/core/config.v').read_bytes()
    assert hashlib.sha256(config).hexdigest() == manifest['files']['cpu/e203/core/config.v']['sha256']
    metadata = dict(project_manifest_sha256=hashlib.sha256(raw).hexdigest(),
                    revision=manifest['revision'], cpu_files=134)
    files = {'cpu_reference/import_cpu.py': (ROOT/'scripts/soc_cpu_reference_import.py').read_bytes().replace(b'\r\n', b'\n'),
             'cpu_reference/config.v': config,
             'cpu_reference/reference.json': (json.dumps(metadata, indent=2)+'\n').encode()}
    if a.expanded:
        overlays = ['core/config.v', 'core/e203_clkgate.v', 'core/e203_dtcm_ram.v',
                    'core/e203_exu_decode.v', 'core/e203_itcm_ram.v']
        metadata['overlays'] = {n: n for n in overlays}
        files = {'cpu_reference_v2/import_cpu.py': files['cpu_reference/import_cpu.py']}
        for name in overlays:
            payload = (project/'cpu/e203'/name).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == manifest['files']['cpu/e203/'+name]['sha256']
            files['cpu_reference_v2/'+name] = payload
        files['cpu_reference_v2/reference.json'] = (json.dumps(metadata, indent=2)+'\n').encode()
    data = archive(files)
    digest = hashlib.sha256(data).hexdigest()
    encoded = base64.b64encode(zlib.compress(data, 9)).decode()
    parts = [encoded[i:i+800] for i in range(0, len(encoded), 800)]
    commands = ['python3 -c "open(\'cpu_ref.part%04d\',\'w\').write(\'%s\')"' % (i, p) for i, p in enumerate(parts)]
    commands.append('python3 -c "import base64,zlib,hashlib;b=zlib.decompress(base64.b64decode(\'\'.join(open(\'cpu_ref.part%%04d\'%%i).read() for i in range(%d))));assert len(b)==%d and hashlib.sha256(b).hexdigest()==\'%s\';open(\'cpu_reference.tar.gz\',\'wb\').write(b);print(\'CPU_REFERENCE_TRANSFER_OK\')"' % (len(parts), len(data), digest))
    commands += ['tar xzf cpu_reference.tar.gz',
                 'python3 %s/import_cpu.py /tmp/e203chk/e203_hbirdv2-master/rtl/e203' % ('cpu_reference_v2' if a.expanded else 'cpu_reference'),
                 'python3 flow/project.py check']
    if a.expanded:
        commands = [c.replace('cpu_ref.part', 'cpu_ref2.part').replace('cpu_reference.tar.gz', 'cpu_reference_v2.tar.gz').replace('CPU_REFERENCE_TRANSFER_OK', 'CPU_REFERENCE_V2_TRANSFER_OK') for c in commands]
    a.output.mkdir(parents=True)
    for name, payload in files.items():
        p = a.output/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload)
    (a.output/('cpu_reference_v2.tar.gz' if a.expanded else 'cpu_reference.tar.gz')).write_bytes(data)
    (a.output/'commands.csh.txt').write_text('\n'.join(commands)+'\n', encoding='ascii')
    report = dict(metadata, bytes=len(data), sha256=digest, parts=len(parts))
    (a.output/'transfer_manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
