"""Source-only installation and rejection tests; never launches CAD."""
import argparse
import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from install_soc_metrics import install
from apply_soc_tb_declfix import updated_manifest
ROOT=Path(__file__).resolve().parents[1]


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def snapshot(root):return {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--bundle',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();bundle=a.bundle.resolve();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    base=out/'kwt_ret1n_reset_2b2dc17_20261111';soc=out/'kwt_soc_joint_0e308fd_20261111'
    shutil.copytree(ROOT/'deliverables/reset_anchor_20261111/project',base)
    shutil.copytree(ROOT/'deliverables/soc_joint_resetguard_20261111/project',soc)
    patchdir=ROOT/'deliverables/soc_tb_declfix_20261111/tb_declfix'
    patch=json.loads((patchdir/'patch.json').read_bytes());tb=(patchdir/'tb_soc_joint.sv').read_bytes()
    (soc/'manifest.json').write_bytes(updated_manifest((soc/'manifest.json').read_bytes(),tb,patch['revision']))
    (soc/'soc/tb_soc_joint.sv').write_bytes(tb)
    for p in [base,soc]:(p/'build').mkdir();(p/'build/KEEP_LIVE').write_text('do not copy or touch')
    before={str(p):snapshot(p) for p in [base,soc]}
    capsule=bundle/'capsule/soc_metrics'
    with contextlib.redirect_stdout(io.StringIO()):target=install(base,capsule)
    assert all(snapshot(p)==before[str(p)] for p in [base,soc])
    assert not (target/'build').exists()
    result=subprocess.run([sys.executable,str(target/'flow/project.py'),'check'],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    manifest=json.loads((target/'manifest.json').read_bytes())
    assert not manifest['work_in_progress'] and manifest['declared_operating_PVT']['corner']=='TT'
    assert 'foreach corner {tt}' in (target/'flow/pt.tcl').read_text() and '[libs ss]' not in (target/'flow/dc.tcl').read_text()
    for n,h in manifest['files'].items():assert sha(target/n)==h
    try:install(base,capsule)
    except AssertionError as e:assert 'TARGET_EXISTS' in str(e)
    else:raise AssertionError('existing target accepted')
    corrupt=out/'corrupt_capsule';shutil.copytree(capsule,corrupt)
    next((corrupt/'assets').iterdir()).write_bytes(b'corrupt')
    try:install(base,corrupt)
    except AssertionError as e:assert 'ASSET_CHANGED' in str(e)
    else:raise AssertionError('bad asset accepted')
    source=soc/'cpu/e203/core/e203_cpu.v';data=source.read_bytes();source.write_bytes(data+b'\n// drift\n')
    try:install(base,capsule)
    except AssertionError as e:assert 'SOURCE_CHANGED' in str(e)
    else:raise AssertionError('source drift accepted')
    finally:source.write_bytes(data)
    assert all(snapshot(p)==before[str(p)] for p in [base,soc])
    loader=(bundle/'PASTE_INSTALL.py').read_text()
    assert ''.join(p.read_text() for p in sorted(bundle.glob('PASTE_PART_*.txt')))==loader
    ast.parse(loader,feature_version=(3,6))
    report=dict(passed=True,source_roots_preserved=True,patched_soc_manifest_accepted=True,no_old_build_copied=True,
        existing_target_refused=True,bad_asset_and_source_drift_refused=True,TT_only=True,all_hex_deltas_reconstructed=True,
        Python36_loader=True,clipboard_reassembly=True,actual_server_run=False,actual_CAD=False)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
