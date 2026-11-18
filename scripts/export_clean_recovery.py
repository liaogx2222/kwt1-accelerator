"""Make a small, hash-bound flow-only recovery installer for VNC transfer."""
import argparse
import base64
import difflib
import hashlib
import json
from pathlib import Path
import re
import zlib

INSTALLER = '''# Python 3.6; flow-only repair with source and failed-build backup.
import base64, hashlib, json, os, shutil, subprocess, sys, zlib
from pathlib import Path
payload = json.loads(zlib.decompress(base64.b64decode("PAYLOAD_DATA")).decode())
root = Path.cwd().resolve()
manifest = root/"manifest.json"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
current = sha(manifest)
if current not in [payload["old_manifest"], payload["new_manifest"]]:
    raise SystemExit("FLOWFIX_BASE_MISMATCH")
for var in ["KWT_PDK_ROOT", "KWT_SRAM_DB_DIR"]:
    if not os.environ.get(var) or not Path(os.environ[var]).is_dir():
        raise SystemExit("FLOWFIX_MISSING_ENV_OR_DIR " + var)
subprocess.run([sys.executable, "flow/project.py", "check"], check=True)
if current == payload["new_manifest"]:
    subprocess.run([sys.executable, "flow/project.py", "preflight"], check=True)
    print("KWT_FLOWFIX_ALREADY_APPLIED")
    raise SystemExit(0)
if os.name == "posix":
    processes = subprocess.check_output(["ps", "-u", str(os.getuid()), "-o", "comm="]).decode().splitlines()
    if any(p.strip() in ["dc_shell", "pt_shell"] for p in processes):
        raise SystemExit("FLOWFIX_WAIT_FOR_OWN_DC_PT_TO_EXIT")
backup = root/payload["backup_name"]
if backup.exists():
    raise SystemExit("FLOWFIX_BACKUP_ALREADY_EXISTS")
updated = {}
for name, change in payload["files"].items():
    if name != "manifest.json" and not name.startswith("flow/"):
        raise SystemExit("FLOWFIX_REFUSE_NON_FLOW_CHANGE")
    if ".." in Path(name).parts or Path(name).is_absolute():
        raise SystemExit("FLOWFIX_INVALID_PATH")
    original = (root/name).read_bytes() if (root/name).is_file() else b""
    if hashlib.sha256(original).hexdigest() != change["old_sha256"]:
        raise SystemExit("FLOWFIX_FILE_BASE_MISMATCH " + name)
    lines = original.splitlines(True)
    for first, last, encoded in reversed(change["edits"]):
        lines[first:last] = base64.b64decode(encoded).splitlines(True)
    data = b"".join(lines)
    if hashlib.sha256(data).hexdigest() != change["new_sha256"]:
        raise SystemExit("FLOWFIX_FILE_PATCH_MISMATCH " + name)
    updated[name] = data
backup.mkdir()
for name in payload["files"]:
    p = root/name
    if p.is_file():
        saved = backup/"source"/name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, saved)
if (root/"build").exists():
    (root/"build").rename(backup/"build")
for name, data in updated.items():
    (root/name).parent.mkdir(parents=True, exist_ok=True)
    (root/name).write_bytes(data)
if sha(manifest) != payload["new_manifest"]:
    raise SystemExit("FLOWFIX_MANIFEST_MISMATCH")
subprocess.run([sys.executable, "flow/project.py", "check"], check=True)
subprocess.run([sys.executable, "flow/project.py", "preflight"], check=True)
(root/"build").mkdir(exist_ok=True)
(backup/"recovery.json").write_text(json.dumps(dict(old_manifest=payload["old_manifest"],new_manifest=payload["new_manifest"],changed=list(payload["files"])), indent=2))
print("KWT_FLOWFIX_READY")
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, type=Path)
    ap.add_argument("--updated", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--backup-name", default="recovery_missing_pdk_20261111")
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise ValueError("choose a fresh recovery output")
    if not re.fullmatch(r"[A-Za-z0-9_]+", a.backup_name):
        raise ValueError("backup name must be one simple directory name")
    old = json.loads((a.base/"manifest.json").read_text())
    new = json.loads((a.updated/"manifest.json").read_text())
    changed = [n for n in new["files"] if old["files"].get(n) != new["files"][n]]
    assert changed and all(n.startswith("flow/") for n in changed), changed
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    files = {}
    for name in changed+["manifest.json"]:
        old_data = (a.base/name).read_bytes() if (a.base/name).is_file() else b""
        new_data = (a.updated/name).read_bytes()
        old_lines, new_lines = old_data.splitlines(True), new_data.splitlines(True)
        edits = [[i,j,base64.b64encode(b"".join(new_lines[k:l])).decode()]
                 for tag,i,j,k,l in difflib.SequenceMatcher(None,old_lines,new_lines,autojunk=False).get_opcodes() if tag != "equal"]
        files[name] = dict(old_sha256=hashlib.sha256(old_data).hexdigest(),new_sha256=sha(a.updated/name),edits=edits)
    payload = dict(old_manifest=sha(a.base/"manifest.json"), new_manifest=sha(a.updated/"manifest.json"),
                   backup_name=a.backup_name, files=files)
    data = INSTALLER.replace("PAYLOAD_DATA", base64.b64encode(zlib.compress(json.dumps(payload).encode(),9)).decode()).encode()
    out.mkdir(parents=True)
    (out/"apply_flowfix.py").write_bytes(data)
    encoded = base64.b64encode(zlib.compress(data,9)).decode()
    parts = [encoded[n:n+800] for n in range(0,len(encoded),800)]
    commands = []
    for n, part in enumerate(parts):
        name = "kwt_flowfix.part%04d" % n
        commands.append('python3 -c "open(\'%s\',\'w\').write(\'%s\')"' % (name,part))
        (out/(name+".txt")).write_text(part, encoding="ascii")
    commands.append('python3 -c "import glob,base64,zlib;open(\'apply_flowfix.py\',\'xb\').write(zlib.decompress(base64.b64decode(\'\'.join(open(p).read() for p in sorted(glob.glob(\'kwt_flowfix.part[0-9][0-9][0-9][0-9]\'))))))"')
    commands.extend(["wc -c apply_flowfix.py", "sha256sum apply_flowfix.py"])
    (out/"commands.csh.txt").write_text("\n".join(commands)+"\n", encoding="ascii")
    report = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), chunks=len(parts),
                  base_revision=old["git_revision"], revision=new["git_revision"], changed=changed,
                  old_manifest=payload["old_manifest"], new_manifest=payload["new_manifest"])
    (out/"recovery_manifest.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
