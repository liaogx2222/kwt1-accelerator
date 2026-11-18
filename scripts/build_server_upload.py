"""Build a self-contained, hash-manifested upload bundle for the SMIC40 server.

The bundle keeps `<REPO>/keyword-transformer/` and `<REPO>/docs/architecture/`
as siblings, because scripts resolve paths relative to those two directories
(finalize_signoff_metrics.py uses ROOT.parent/docs/architecture, and
check_technology.py resolves the frozen source manifest from ROOT).

Deliberately EXCLUDED (see docs/architecture/SERVER_UPLOAD_GUIDE_20261106.md):
  * training corpora / wav datasets / model checkpoints  (multi-GB)
  * bulk testdata evidence trees (r1r2, rtl_v2, resident_core, integer_v1 npy)
  * third_party Nangate45 public reference library
  * deliverables/e203_reference_20261103/tools/zig-cache (2009 build artifacts)
  * __pycache__, *.pyc, *.obj, *.o, *.vvp

Nothing is modified at the source: files are copied byte-for-byte.
"""
import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BUNDLE_NAME = 'server_signoff_20261106'
GENERATED = {'manifest.json', 'sha256sum.txt', 'verify_upload.sh'}
JUNK_DIRS = {'__pycache__', 'zig-cache', '.git'}
JUNK_SUFFIXES = {'.pyc', '.pyo', '.obj', '.o', '.vvp', '.so', '.dll', '.exe', '.class'}

ROOT_FILES = ['progress.md', 'findings.md', 'task_plan.md']
KT_ROOT_FILES = ['README.md', 'LICENSE.txt', 'requirements.txt',
                 'requirements-r1r2.lock', 'environment_kwt_ref.txt']
# Small, signoff-relevant evidence. Anything multi-GB is transferred separately.
TESTDATA_DIRS = [
    'testdata/resident_core_20261105/toolchain',
    'testdata/full_scope_20261105',
    'testdata/p4a/hw_params_verified',
    'testdata/integration_v1/release/candidate_system',
]
TESTDATA_FILES = [
    'testdata/rtl_v2/release/source_manifest.json',
    'testdata/r1r2/release/rtl/vectors.txt',
    'testdata/r1r2/release/provenance.json',
    'testdata/r1r2/release/toolchain_components.json',
    'testdata/integer_v1/params/manifest.json',
    'testdata/integer_v1/fixture/manifest.json',
    'testdata/integer_v1/evidence_bundle_manifest.json',
]


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def usable(p):
    if not p.is_file():
        return False
    if any(part in JUNK_DIRS for part in p.parts):
        return False
    if p.suffix.lower() in JUNK_SUFFIXES:
        return False
    return True


def add(mapping, src_root, rel):
    """rel is POSIX relative to the bundle root."""
    src = src_root / rel
    if not src.exists():
        raise SystemExit('required source missing: ' + str(src))
    if not src.is_file():
        return
    if rel in mapping:
        return
    mapping[rel] = src


def collect(src_root):
    m = {}
    kt = src_root / 'keyword-transformer'

    for name in ROOT_FILES:
        add(m, src_root, name)
    for name in KT_ROOT_FILES:
        add(m, src_root, 'keyword-transformer/' + name)

    # Top-level architecture documents only (no scripts, no evidence trees).
    arch = src_root / 'docs/architecture'
    for p in sorted(arch.iterdir()):
        if p.is_file() and p.suffix.lower() in {'.md', '.json'}:
            add(m, src_root, 'docs/architecture/' + p.name)

    # Curated project subtrees.
    for sub in ['flow', 'rtl', 'firmware', 'manifest', 'integer_model']:
        base = kt / sub
        for p in sorted(base.rglob('*')):
            if usable(p):
                add(m, src_root, 'keyword-transformer/' + p.relative_to(kt).as_posix())

    # Top-level scripts only (no __pycache__).
    for p in sorted((kt / 'scripts').iterdir()):
        if p.is_file() and p.suffix == '.py':
            add(m, src_root, 'keyword-transformer/scripts/' + p.name)

    for d in TESTDATA_DIRS:
        base = kt / d
        if not base.exists():
            continue
        for p in sorted(base.rglob('*')):
            if usable(p):
                add(m, src_root, 'keyword-transformer/' + p.relative_to(kt).as_posix())
    for f in TESTDATA_FILES:
        p = kt / f
        if p.is_file():
            add(m, src_root, 'keyword-transformer/' + f)

    # Hash-bound delivery packages. E203 package: ONLY manifested files + docs.
    lp = kt / 'deliverables/local_port_20261103'
    for p in sorted(lp.rglob('*')):
        if usable(p):
            add(m, src_root, 'keyword-transformer/' + p.relative_to(kt).as_posix())

    er = kt / 'deliverables/e203_reference_20261103'
    er_manifest = json.loads((er / 'manifest.json').read_text(encoding='utf-8'))['sha256']
    for name in list(er_manifest) + ['manifest.json', 'README.md']:
        src = er / name.replace('\\', '/')
        if not src.is_file():
            raise SystemExit('E203 reference package is incomplete: ' + name)
        add(m, src_root, 'keyword-transformer/' + (er / name.replace('\\', '/')).relative_to(kt).as_posix())

    # Upload guide becomes the bundle's README_UPLOAD.md.
    guide = arch / 'SERVER_UPLOAD_GUIDE_20261106.md'
    if not guide.is_file():
        raise SystemExit('upload guide not found: ' + str(guide))
    m['README_UPLOAD.md'] = guide
    return m


def main():
    default_root = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-root', type=Path, default=default_root)
    ap.add_argument('--output', type=Path, default=None, help='staging directory')
    ap.add_argument('--zip', type=Path, default=None, help='output .zip path')
    ap.add_argument('--no-zip', action='store_true')
    ap.add_argument('--force', action='store_true', help='replace an existing staging dir / zip')
    a = ap.parse_args()

    src_root = a.source_root.resolve()
    out = (a.output or src_root / BUNDLE_NAME).resolve()
    zpath = (a.zip or src_root / (BUNDLE_NAME + '.zip')).resolve()

    if out.exists():
        if not a.force:
            raise SystemExit('staging directory exists (use --force): ' + str(out))
        shutil.rmtree(out)
    if zpath.exists() and not a.force:
        raise SystemExit('zip exists (use --force): ' + str(zpath))

    mapping = collect(src_root)
    out.mkdir(parents=True)
    for rel, src in sorted(mapping.items()):
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # Hash every delivered file except the generated bookkeeping files.
    hashed = {}
    for p in sorted(out.rglob('*')):
        if not p.is_file():
            continue
        rel = p.relative_to(out).as_posix()
        if rel in GENERATED:
            continue
        hashed[rel] = {'sha256': sha256(p), 'size': p.stat().st_size}

    manifest = {
        'bundle': BUNDLE_NAME,
        'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source_root': src_root.as_posix(),
        'file_count': len(hashed),
        'total_bytes': sum(v['size'] for v in hashed.values()),
        'sha256': {k: v['sha256'] for k, v in hashed.items()},
        'size': {k: v['size'] for k, v in hashed.items()},
        'groups': dict(sorted(Counter(k.split('/')[0] for k in hashed).items())),
    }
    (out / 'manifest.json').write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8', newline='\n')
    (out / 'sha256sum.txt').write_text(
        ''.join('%s  %s\n' % (v['sha256'], k) for k, v in hashed.items()),
        encoding='utf-8', newline='\n')
    (out / 'verify_upload.sh').write_text(
        '#!/bin/sh\n# Run from the extracted bundle root.\n'
        'set -e\ncd "$(dirname "$0")"\nsha256sum -c sha256sum.txt\n'
        'python3 - <<\'PY\'\n'
        'import json,pathlib\n'
        'm=json.loads(pathlib.Path("manifest.json").read_text())\n'
        'print("manifest files:",m["file_count"],"bytes:",m["total_bytes"])\n'
        'PY\n', encoding='utf-8', newline='\n')

    result = dict(bundle_root=out.as_posix(), files=len(hashed),
                  total_MB=round(manifest['total_bytes'] / 1e6, 2),
                  groups=manifest['groups'])
    if not a.no_zip:
        with zipfile.ZipFile(zpath, 'w', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as z:
            for p in sorted(out.rglob('*')):
                if p.is_file():
                    z.write(p, (Path(BUNDLE_NAME) / p.relative_to(out).as_posix()).as_posix())
        result['zip'] = zpath.as_posix()
        result['zip_MB'] = round(zpath.stat().st_size / 1e6, 2)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
