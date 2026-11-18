"""Fetch only public reference-library data, pinned to an upstream commit.

No project data is uploaded. This deliberately does not bind the SMIC40 target.
"""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'c9ac73efc603ec3b830caecd7874b1419c1b7d41'
BASE = f'https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD-flow-scripts/{COMMIT}/flow/platforms/nangate45/'
FILES = ['LICENSE', 'README.md', 'config.mk', 'lib/NangateOpenCellLibrary_typical.lib']


def main():
    dest = ROOT / 'third_party/nangate45_reference'
    if dest.exists():
        raise SystemExit('Refusing to replace existing library directory')
    # Fetch before creating destination so network failure leaves no partial library.
    data = {name: urllib.request.urlopen(BASE + name, timeout=60).read() for name in FILES}
    assert b'library (' in data[FILES[-1]] or b'library(' in data[FILES[-1]]
    for name, value in data.items():
        path = dest / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    manifest = dict(upstream='The-OpenROAD-Project/OpenROAD-flow-scripts', commit=COMMIT,
                    scope='Non-manufacturable Nangate45 reference; not SMIC40',
                    files={name: dict(url=BASE + name, sha256=hashlib.sha256(value).hexdigest(),
                                      bytes=len(value)) for name, value in data.items()})
    (dest / 'provenance.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
