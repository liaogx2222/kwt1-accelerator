"""Python 3.6: bind initial DDC, frozen source and recovery output evidence."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_input():
    record = json.loads((ROOT/'RECOVERY_INPUT.json').read_text())
    meta = json.loads((ROOT/'recovery/metadata.json').read_text())
    if sha(ROOT/'manifest.json') != meta['base_manifest_sha256']:
        raise SystemExit('RECOVERY_SOURCE_MANIFEST_MISMATCH')
    subprocess.check_call([sys.executable, str(ROOT/'flow/project.py'), 'check'])
    for name, value in meta['tools'].items():
        if sha(ROOT/'recovery'/name) != value:
            raise SystemExit('RECOVERY_TOOL_MISMATCH '+name)
    checkpoint = ROOT/'build/recovery_input/initial_mapped.ddc'
    if checkpoint.stat().st_size == 0 or sha(checkpoint) != record['checkpoint_sha256']:
        raise SystemExit('RECOVERY_CHECKPOINT_MISMATCH')
    if record['scope'] != 'INITIAL_MAPPING_ONLY' or record['source_manifest_sha256'] != meta['base_manifest_sha256']:
        raise SystemExit('RECOVERY_SCOPE_OR_SOURCE_MISMATCH')
    print('KWT_RECOVERY_INPUT_VERIFIED '+record['checkpoint_sha256'])
    return record


def output_record(record):
    subprocess.check_call([sys.executable, str(ROOT/'flow/project.py'), 'check-dc'])
    return dict(scope='INITIAL_MAPPING_ONLY', hold_signed_off=False,
                source_manifest_sha256=record['source_manifest_sha256'],
                checkpoint_sha256=record['checkpoint_sha256'],
                input_record_sha256=sha(ROOT/'RECOVERY_INPUT.json'),
                outputs={name: sha(ROOT/'build/dc'/name) for name in
                         ['mapped.v', 'mapped.ddc', 'mapped.sdc', 'netlist_manifest.json']})


if __name__ == '__main__':
    record = check_input()
    if sys.argv[1:] == ['attest-output']:
        result = output_record(record)
        with (ROOT/'build/dc/recovery_manifest.json').open('x') as stream:
            json.dump(result, stream, indent=2)
        print('KWT_RECOVERY_OUTPUT_ATTESTED INITIAL_MAPPING_ONLY')
    elif sys.argv[1:] == ['check-output']:
        expected = json.loads((ROOT/'build/dc/recovery_manifest.json').read_text())
        if expected != output_record(record):
            raise SystemExit('RECOVERY_OUTPUT_MISMATCH')
        print('KWT_RECOVERY_OUTPUT_VERIFIED INITIAL_MAPPING_ONLY')
    elif sys.argv[1:] != ['check-input']:
        raise SystemExit('usage: verify.py check-input | attest-output | check-output')
