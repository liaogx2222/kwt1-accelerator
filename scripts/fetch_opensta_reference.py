"""Fetch a versioned official Ubuntu binary into workspace, no system install."""
import hashlib,json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
URL='https://archive.ubuntu.com/ubuntu/pool/universe/o/opensta/opensta_0~20191111gitc018cb2+dfsg-1build1_amd64.deb'
EXPECTED_SHA256='b1272a4816bc2c67098872f39820f27b4dddf640205e09a31444c71c9fe41e9e'
def main():
    out=ROOT/'tools/opensta_reference';out.mkdir(parents=True,exist_ok=True);package=out/'opensta_jammy_amd64.deb'
    if not package.exists():
        with urllib.request.urlopen(URL,timeout=60) as response:package.write_bytes(response.read())
    digest=hashlib.sha256(package.read_bytes()).hexdigest()
    assert digest==EXPECTED_SHA256,'Official reference package differs from the pinned artifact'
    (out/'provenance.json').write_text(json.dumps(dict(url=URL,package_version='0~20191111gitc018cb2+dfsg-1build1',distribution='Ubuntu jammy amd64, executed only as workspace-local reference on Ubuntu24.04 WSL',sha256=digest,source_commit='c018cb2',license='upstream/packaged GPL notices retained in extracted usr/share/doc/opensta',system_install=False,source='https://packages.ubuntu.com/jammy/opensta'),indent=2))
    print(json.dumps(dict(path=str(package),bytes=package.stat().st_size,sha256=digest),indent=2))
if __name__=='__main__':main()
