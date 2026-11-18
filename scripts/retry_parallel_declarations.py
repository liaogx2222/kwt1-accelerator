"""Python 3.6: immutable three-project retry for DC declaration-order errors."""
import hashlib
import json
from pathlib import Path, PurePosixPath

PARENT_HASH = '413ae9d066a7bf0eddc73ffc5feadcae9d57bd154746ad27251435d9bba3015c'
VERSIONS = ('overlap', 'refine', 'writeback')
FIX_ID = 'DC_DECL_ORDER_V1'
RTL = 'rtl/v2/kwt_layer_banked.sv'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True)+'\n').encode()


def fix_declarations(data):
    """Relocate two whole declaration lines; preserve every other byte."""
    assert b'\r' not in data, 'EXPECTED_FROZEN_LF_SOURCE'
    lines = data.splitlines(True)
    mac = [x for x in lines if x.startswith(b' reg mac_load,mac_en,mac_unsigned;')]
    integers = [x for x in lines if x.startswith(b' integer rows,kdim,ndim,')]
    assert len(mac) == len(integers) == 1, 'DECLARATION_MATCH_FAILED'
    assert b'wire [ROWS*16*32-1:0] acc;' in mac[0], 'ACC_WIDTH_CHANGED'
    anchor = b' localparam ROWS=8;\n'
    assert lines.count(anchor) == 1, 'ROWS_ANCHOR_CHANGED'
    before = b''.join(x for x in lines if x not in mac+integers)
    assert before.count(anchor) == 1
    result = before.replace(anchor, anchor+mac[0]+integers[0], 1)
    assert b''.join(x for x in result.splitlines(True) if x not in mac+integers) == before
    assert sorted(lines) == sorted(result.splitlines(True)), 'NON_RELOCATION_CHANGE'
    assert result.index(mac[0]) < result.index(b' always @*begin')
    assert result.index(integers[0]) < result.index(b' always @*begin')
    return result


def make_retry(parent):
    parent = parent.resolve()
    raw = (parent/'batch_manifest.json').read_bytes()
    assert sha(raw) == PARENT_HASH, 'WRONG_PARENT_BATCH'
    spec = json.loads(raw)
    assert not spec['development_dirty'] and not spec['hold_optimization']
    receipt = json.loads((parent/'INSTALL_RECEIPT.json').read_bytes())
    assert receipt['batch_manifest_sha256'] == PARENT_HASH, 'PARENT_RECEIPT_MISMATCH'
    planned = {}
    for name, expected in spec['batch_tools'].items():
        assert name == 'batch_run.py', 'UNEXPECTED_BATCH_TOOL'
        data = (parent/name).read_bytes()
        assert sha(data) == expected, 'PARENT_TOOL_CHANGED'
        planned[name] = data
    for name in VERSIONS:
        raw_manifest = (parent/name/'manifest.json').read_bytes()
        assert sha(raw_manifest) == spec['projects'][name]['manifest_sha256'], 'PARENT_MANIFEST_CHANGED'
        manifest = json.loads(raw_manifest)
        for file, row in manifest['files'].items():
            path = PurePosixPath(file)
            assert not path.is_absolute() and '..' not in path.parts and '\\' not in file
            data = (parent/name/file).read_bytes()
            assert sha(data) == row['sha256'] and len(data) == row['bytes'], 'PARENT_SOURCE_CHANGED '+name+'/'+file
            planned[name+'/'+file] = data
        original = planned[name+'/'+RTL]
        fixed = fix_declarations(original)
        planned[name+'/'+RTL] = fixed
        patch = dict(id=FIX_ID, file=RTL, before_sha256=sha(original), after_sha256=sha(fixed),
                     method='relocate two entire declaration lines before first procedural use',
                     original_RTL_revision=manifest['RTL_revision'],
                     original_manifest_sha256=sha(raw_manifest),
                     actual_DC_validation_pending=True)
        manifest['compatibility_patch'] = patch
        manifest['files'][RTL] = dict(bytes=len(fixed), sha256=sha(fixed))
        updated = encoded(manifest)
        planned[name+'/manifest.json'] = updated
        spec['projects'][name]['manifest_sha256'] = sha(updated)
        spec['projects'][name]['compatibility_patch'] = patch
    spec['projects'] = {name:spec['projects'][name] for name in VERSIONS}
    spec['requested_jobs'] = 3
    spec['scope'] = 'three isolated accelerator partition retries; baseline8 remains in parent batch'
    spec['compatibility_patch'] = FIX_ID
    spec['parent_batch_manifest_sha256'] = PARENT_HASH
    planned['batch_manifest.json'] = encoded(spec)
    planned['INSTALL_RECEIPT.json'] = encoded(dict(batch_manifest_sha256=sha(planned['batch_manifest.json']),
        producer_revision=spec['producer_revision'], compatibility_patch=FIX_ID,
        parent_batch_manifest_sha256=PARENT_HASH))
    # This script is a provenance artifact, never inserted into project manifests.
    tool = Path(__file__).read_bytes()
    planned['declaration_retry.py'] = tool
    target = parent.parent/'kwt_parallel_max_20261112_decl_v1'
    assert not target.exists(), 'RETRY_TARGET_EXISTS_PRESERVE '+str(target)
    assert target.parent == parent.parent and target != parent
    # Read/validate all sources before creating anything. No build, state, lock,
    # source mutation, process signal, or baseline8 file is copied or written.
    target.mkdir()
    for name, data in planned.items():
        path = target/name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
    print('DECL_RETRY_CREATED '+str(target))
    print('DECL_RETRY projects=3 declaration_relocation_only baseline8_untouched hold_fix_OFF')
    for name in VERSIONS:
        patch = spec['projects'][name]['compatibility_patch']
        print('DECL_RETRY_HASH '+name+' '+patch['after_sha256'])
    return target


if __name__ == '__main__':
    make_retry(Path.cwd())
