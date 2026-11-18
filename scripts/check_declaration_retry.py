"""Check the deployment repair, source isolation and native RTL parsing, not DC."""
import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from retry_parallel_declarations import make_retry, fix_declarations, VERSIONS, RTL

ROOT = Path(__file__).resolve().parents[1]


def hashes(path):
    return {p.relative_to(path).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args(); out = a.output.resolve()
    assert not out.exists(); out.mkdir(parents=True)
    parent = out/'old_batch'
    shutil.copytree(ROOT/'deliverables/parallel_max_20261112_v2/batch', parent)
    (parent/'baseline8/build').mkdir()
    (parent/'baseline8/build/LIVE').write_text('DO NOT TOUCH')
    (parent/'states.json').write_text('{"running":"baseline8"}')
    (parent/'launch.lock').write_text('60226')
    for name in VERSIONS:
        (parent/name/'build').mkdir()
        (parent/name/'build/dc.console.log').write_text('REAL-ERROR PLACEHOLDER, RETAIN')
    before = hashes(parent)
    with contextlib.redirect_stdout(io.StringIO()): target = make_retry(parent)
    assert hashes(parent) == before, 'PARENT_CHANGED'
    assert not (target/'baseline8').exists()
    assert not (target/'launch.lock').exists() and not (target/'states.json').exists()
    for name in VERSIONS:
        project = target/name
        assert not (project/'build').exists()
        original = (parent/name/RTL).read_bytes()
        fixed = (project/RTL).read_bytes()
        assert fixed == fix_declarations(original)
        m = json.loads((project/'manifest.json').read_text())
        assert m['compatibility_patch']['before_sha256'] == hashlib.sha256(original).hexdigest()
        assert m['compatibility_patch']['after_sha256'] == hashlib.sha256(fixed).hexdigest()
        for path in m['files']:
            if path != RTL: assert (project/path).read_bytes() == (parent/name/path).read_bytes()
        result = subprocess.run([sys.executable,str(project/'flow/project.py'),'check'],capture_output=True,text=True)
        assert result.returncode == 0, result.stdout+result.stderr
    result = subprocess.run([sys.executable,str(target/'batch_run.py'),'check'],capture_output=True,text=True)
    assert result.returncode == 0, result.stdout+result.stderr
    result = subprocess.run([sys.executable,str(target/'batch_run.py'),'run','--jobs','3','--dry-run'],capture_output=True,text=True)
    assert result.returncode == 0 and len(json.loads(result.stdout)['plan']['projects']) == 3
    try: make_retry(parent)
    except AssertionError as e: assert 'RETRY_TARGET_EXISTS' in str(e)
    else: raise AssertionError('existing target accepted')
    source = parent/'overlap'/RTL
    saved = source.read_bytes()
    source.write_bytes(saved+b'// drift\n')
    try: make_retry(parent)
    except AssertionError as e: assert 'PARENT_SOURCE_CHANGED' in str(e)
    else: raise AssertionError('source drift accepted')
    source.write_bytes(saved)
    assert hashes(parent) == before
    ast.parse((ROOT/'scripts/retry_parallel_declarations.py').read_text(),feature_version=(3,6))
    # Parse the actual production source sets, before and after relocation.
    vr = ROOT/'tools/rtl_v1_python/verilator/bin/verilator_bin.exe'
    env = dict(os.environ, VERILATOR_ROOT=str(vr.parent.parent))
    lint = []
    for name in VERSIONS:
        for mode in ['original','fixed']:
            project = (parent if mode == 'original' else target)/name
            sources = [str(project/p) for p in (project/'flow/rtl_sources.txt').read_text().splitlines()]
            command = [str(vr),'--lint-only','--Wno-fatal','-DBLACKBOX','--bbox-unsup',
                '-I'+str(project/'rtl/v2/generated'),'--top-module','kwt1_mmio','-GBLOCK_STREAM=1',*sources]
            # A macro blackbox declaration is needed for production lint.
            stub = out/'macro_stub.sv'
            if not stub.exists():
                stub.write_text('module RAMSP4096X16(output [15:0] Q,input CLK,CEN,GWEN,input [15:0] WEN,input [11:0] A,input [15:0] D,input [2:0] EMA,input [1:0] EMAW,input RET1N); endmodule\n')
            command.append(str(stub))
            result = subprocess.run(command,capture_output=True,text=True,env=env)
            (out/(name+'_'+mode+'_lint.log')).write_text(result.stdout+result.stderr)
            assert result.returncode == 0, name+' '+mode+' lint failed, see log'
            lint.append(name+'/'+mode)
    summary = dict(passed=True,Python36_syntax=True,old_batch_and_baseline_preserved=True,
        exact_two_declaration_lines_relocated=True,other_all_project_files_byte_identical=True,
        three_project_manifest_and_batch_check=True,source_drift_and_existing_target_refused=True,
        no_old_build_or_lock_copied=True,three_project_dry_run=True,
        native_Verilator_production_lint=lint,actual_DC_PT_execution=False,
        numerical_regression_rerun=False,scope='source relocation, parsing and isolated deployment')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__': main()
