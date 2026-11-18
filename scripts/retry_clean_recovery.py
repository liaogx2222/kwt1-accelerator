"""Retry VNC transfer under fresh names; verify bytes before replacing output."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import zlib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True, type=Path)
    ap.add_argument("--retry", required=True)
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_]+", a.retry):
        raise ValueError("retry name must be alphanumeric")
    original = a.bundle/"apply_flowfix.py"
    data = original.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    manifest = json.loads((a.bundle/"recovery_manifest.json").read_text())
    assert len(data) == manifest["bytes"] and digest == manifest["sha256"]
    encoded = base64.b64encode(zlib.compress(data,9)).decode()
    parts = [encoded[n:n+800] for n in range(0,len(encoded),800)]
    prefix = "kwt_flowfix_%s.part" % a.retry
    filename = "apply_flowfix_%s.py" % a.retry
    commands = []
    for n, part in enumerate(parts):
        commands.append('python3 -c "open(\'%s%04d\',\'w\').write(\'%s\')"' % (prefix,n,part))
    # Decode and check before opening the output. Exact filenames exclude old
    # parts; repeated successful execution recreates only this transfer artifact.
    commands.append('python3 -c "import base64,zlib,hashlib;b=zlib.decompress(base64.b64decode(\'\'.join(open(\'%s%%04d\'%%i).read() for i in range(%d))));assert len(b)==%d and hashlib.sha256(b).hexdigest()==\'%s\',\'TRANSFER_HASH_MISMATCH\';open(\'%s\',\'wb\').write(b);print(\'KWT_FLOWFIX_TRANSFER_OK\')"' % (prefix,len(parts),len(data),digest,filename))
    commands += ["wc -c " + filename, "sha256sum " + filename]
    path = a.bundle/("commands_%s.csh.txt" % a.retry)
    with path.open("x",encoding="ascii") as f:
        f.write("\n".join(commands)+"\n")
    assert zlib.decompress(base64.b64decode("".join(parts))) == data
    # Negative check: missing parts fail before the destination is opened.
    try:
        zlib.decompress(base64.b64decode("".join(parts[:-1])))
        raise AssertionError("truncated transfer was accepted")
    except (zlib.error, ValueError):
        pass
    report = dict(retry=a.retry, parts=len(parts), bytes=len(data), sha256=digest,
                  remote_filename=filename, command_file=path.name,
                  command_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  reconstructed=True, truncation_rejected=True, installer_unchanged=True)
    (a.bundle/("retry_%s.json" % a.retry)).write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
