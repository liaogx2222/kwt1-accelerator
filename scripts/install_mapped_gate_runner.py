"""Python 3.6: add a source-bound external mapped validation entry."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha(data):
    return hashlib.sha256(data).hexdigest()


def install(root, capsule):
    metadata = json.loads((capsule/'metadata.json').read_text())
    manifest = (root/'manifest.json').read_bytes()
    runner = (capsule/'run_mapped_gate.sh').read_bytes()
    if sha(manifest) != metadata['source_manifest_sha256'] or sha(runner) != metadata['runner_sha256']:
        raise SystemExit('MAPPED_GATE_INSTALL_HASH_MISMATCH')
    p = subprocess.run([sys.executable, str(root/'flow/project.py'), 'check-dc'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if p.returncode or 'KWT_NETLIST_VERIFIED ' not in p.stdout:
        raise SystemExit('MAPPED_GATE_NETLIST_REJECTED\n'+p.stdout+p.stderr)
    target = root/'review_tools/run_mapped_gate.sh'
    if target.exists() and target.read_bytes() != runner:
        raise SystemExit('MAPPED_GATE_RUNNER_REFUSE_OVERWRITE')
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(runner)
    print(p.stdout.strip())
    print('MAPPED_GATE_RUNNER_INSTALLED production_unchanged=1 netlist_unchanged=1')


if __name__ == '__main__':
    install(Path.cwd(), Path(__file__).resolve().parent)
