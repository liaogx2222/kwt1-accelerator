"""Check patch provenance, failed-run preservation, idempotence and rejection."""
import argparse
import ast
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zlib
from apply_soc_tb_declfix import apply

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True, type=Path)
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise ValueError('fresh output required')
    out.mkdir(parents=True)
    bundle = ROOT/'deliverables/soc_tb_declfix_20261111'
    capsule = bundle/'tb_declfix'
    meta = json.loads((bundle/'transfer_manifest.json').read_text())
    lines = (bundle/'commands.csh.txt').read_text().splitlines()
    parts = [re.search(r"write\('([^']+)'\)", line).group(1) for line in lines[:meta['parts']]]
    data = zlib.decompress(base64.b64decode(''.join(parts)))
    assert data == (bundle/'tb_declfix.tar.gz').read_bytes()
    assert hashlib.sha256(data).hexdigest() == meta['sha256']
    assert (capsule/'apply.py').read_bytes() == (ROOT/'scripts/apply_soc_tb_declfix.py').read_bytes().replace(b'\r\n', b'\n')
    base = ROOT/'deliverables/soc_joint_resetguard_20261111/project'
    def project(name):
        p = out/name
        shutil.copytree(base, p)
        for folder in ['case0', 'rtl']:
            q = p/'build'/folder
            q.mkdir(parents=True)
            (q/'failed.log').write_text('preserve failed '+folder)
        return p
    valid = project('valid')
    with contextlib.redirect_stdout(io.StringIO()):
        apply(valid, capsule)
        apply(valid, capsule)
    for name in ['case0', 'rtl']:
        assert not (valid/'build'/name).exists()
        assert (valid/'build'/(name+'_before_tb_declfix')/'failed.log').read_text() == 'preserve failed '+name
    assert (valid/'build/tb_declfix_audit/base.manifest.json').read_bytes() == (base/'manifest.json').read_bytes()
    assert (valid/'build/tb_declfix_audit/base.tb_soc_joint.sv').read_bytes() == (base/'soc/tb_soc_joint.sv').read_bytes()
    p = subprocess.run([sys.executable, str(valid/'flow/project.py'), 'check'], capture_output=True, text=True)
    assert p.returncode == 0 and meta['revision'] in p.stdout, p.stdout+p.stderr
    before = json.loads((base/'manifest.json').read_text())
    after = json.loads((valid/'manifest.json').read_text())
    assert all(row == after['files'][n] for n, row in before['files'].items() if n != 'soc/tb_soc_joint.sv')
    def reject(p, marker):
        old = (p/'manifest.json').read_bytes()
        try:
            apply(p, capsule)
        except SystemExit as e:
            assert marker in str(e), str(e)
        else:
            raise AssertionError('unsafe patch accepted')
        assert (p/'manifest.json').read_bytes() == old
        assert (p/'build/case0/failed.log').is_file()
        assert not (p/'build/case0_before_tb_declfix').exists()
    wrong = project('bad_source')
    (wrong/'cpu/e203/core/config.v').write_text('wrong source')
    reject(wrong, 'SOC_TB_PATCH_SOURCE_MISMATCH')
    existing = project('existing_simv')
    (existing/'build/rtl/simv').write_text('preserve executable')
    reject(existing, 'SOC_TB_PATCH_REFUSE_EXISTING_SIMV')
    conflict = project('archive_conflict')
    (conflict/'build/case0_before_tb_declfix').mkdir()
    try:
        apply(conflict, capsule)
    except SystemExit as e:
        assert 'ARCHIVE_EXISTS' in str(e)
    else:
        raise AssertionError('archive collision accepted')
    assert (conflict/'build/case0/failed.log').is_file()
    ast.parse((capsule/'apply.py').read_text(), feature_version=(3, 6))
    report = dict(passed=True, full_197_file_check=True, only_testbench_source_changed=True,
                  failed_runs_preserved=True, idempotent=True, source_mismatch_rejected=True,
                  existing_executable_preserved=True, archive_collision_rejected=True,
                  transport_reconstruction=True, python36=True, actual_server_VCS=False)
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
