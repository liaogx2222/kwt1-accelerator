"""Validate transport/install/isolation and mock the four-job scheduler, not CAD."""
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
import types
import zlib
from unittest.mock import patch
from install_parallel_batch import install

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--bundle',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();bundle=a.bundle.resolve();out=a.output.resolve()
    if out.exists():raise ValueError('fresh output required')
    out.mkdir(parents=True)
    meta=json.loads((bundle/'transfer_manifest.json').read_text())
    lines=(bundle/'VNC_INSTALL.csh.txt').read_text().splitlines()
    parts=[re.search(r"write\('([^']+)'\)",line).group(1) for line in lines[1:1+meta['parts']]]
    data=zlib.decompress(base64.b64decode(''.join(parts)))
    assert data==(bundle/'fix.tar.gz').read_bytes() and hashlib.sha256(data).hexdigest()==meta['sha256']
    loader=(bundle/'STDIN_INSTALL.py').read_text()
    assert ''.join((bundle/('STDIN_PART_%02d.txt'%(i+1))).read_text() for i in range(meta['stdin_clipboard_parts']))==loader
    assert all((bundle/('STDIN_PART_%02d.txt'%(i+1))).stat().st_size<29000 for i in range(meta['stdin_clipboard_parts']))
    ast.parse(loader,feature_version=(3,6))
    base=out/'old_project';shutil.copytree(ROOT/'deliverables/reset_anchor_20261111/project',base)
    (base/'build').mkdir();(base/'build/ACTIVE_GATE_KEEP').write_text('old live work is not copied')
    before={name:sha(base/name) for name in json.loads((base/'manifest.json').read_text())['files']}
    with contextlib.redirect_stdout(io.StringIO()):target=install(base,bundle/'parallel_fix')
    assert before=={name:sha(base/name) for name in before}
    assert (base/'build/ACTIVE_GATE_KEEP').read_text()=='old live work is not copied'
    spec=json.loads((target/'batch_manifest.json').read_text())
    for name,row in spec['projects'].items():
        p=target/name;assert not (p/'build').exists()
        subprocess.check_call([sys.executable,str(p/'flow/project.py'),'check'])
        dc=(p/'flow/dc.tcl').read_text();assert 'set_fix_hold' not in dc and 'HOLD_AFTER_RESET_TREE' not in dc
        assert dc.count('if {![compile_ultra ')==2 and 'alib_library_analysis_path $OUT/alib_cache' in dc
        assert (p/'flow/constraints.sdc').read_bytes().startswith((base/'flow/constraints.sdc').read_bytes())
        assert (p/'flow/constraints_base.sdc').read_bytes()==(base/'flow/constraints.sdc').read_bytes()
        assert 'set hold_uncert 0.150' in (p/'flow/constraints.sdc').read_text()
        if name!='baseline8':assert 'BLOCK_STREAM=1' in (p/'flow/project.tcl').read_text() and 'set block_inputs' in (p/'flow/constraints.sdc').read_text()
        ast.parse((p/'flow/project.py').read_text(),feature_version=(3,6))
    for script in [target/'batch_run.py',bundle/'parallel_fix/install.py']:ast.parse(script.read_text(),feature_version=(3,6))
    result=subprocess.run([sys.executable,str(target/'batch_run.py'),'check'],capture_output=True,text=True);assert result.returncode==0,result.stdout+result.stderr
    result=subprocess.run([sys.executable,str(target/'batch_run.py'),'run','--jobs','4','--cores-per-job','1','--dry-run'],capture_output=True,text=True);assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(result.stdout)['dry_run'] and not (target/'launch.lock').exists()
    try:install(base,bundle/'parallel_fix')
    except SystemExit as error:assert 'TARGET_EXISTS' in str(error)
    else:raise AssertionError('existing batch overwritten')
    corrupt=out/'bad_capsule';shutil.copytree(bundle/'parallel_fix',corrupt)
    first=next((corrupt/'assets').iterdir());first.write_text('corrupt')
    try:install(base,corrupt)
    except SystemExit as error:assert 'ASSET_HASH_MISMATCH' in str(error)
    else:raise AssertionError('bad asset accepted')
    (base/'rtl/v2/kwt_math.sv').write_text('source drift')
    try:install(base,bundle/'parallel_fix')
    except SystemExit as error:assert 'BASE_SOURCE_MISMATCH' in str(error)
    else:raise AssertionError('base source drift accepted')
    # Explicit synthetic scheduler fixture. No real processes or EDA are launched.
    namespace={'__name__':'parallel_scheduler_mock','__file__':str(target/'batch_run.py')}
    exec(compile((target/'batch_run.py').read_text(),str(target/'batch_run.py'),'exec'),namespace)
    verified=namespace['verify']();verified['development_dirty']=False
    namespace['verify']=lambda:verified
    namespace['resources']=lambda:(64,352*1024**3)
    namespace['stage_check']=lambda *args:None
    live=[0];peak=[0];counter=[10000]
    class MockProcess:
        def __init__(self,command,cwd,env,stdout,stderr):
            self.project=Path(cwd);self.stage='dc' if 'dc_shell' in command[0] else 'pt';self.polls=0;self.done=False
            counter[0]+=1;self.pid=counter[0];live[0]+=1;peak[0]=max(peak[0],live[0])
            assert env['KWT_JOB_CORES']=='4' and 'KWT_GATE_SAIF' not in env
            self.code=1 if self.stage=='dc' and self.project.name=='overlap' else 0
            if self.stage=='dc':
                d=self.project/'build/dc/reports';d.mkdir(parents=True)
                (d/'area.rpt').write_text('Total cell area: 123\nMacro/Black Box area: 20\n')
                (d.parent/'mapped.v').write_text('MOCK NETLIST NOT ACTUAL HARDWARE')
                stdout.write('MOCK ONLY\nKWT_CLEAN_SYNTH_DONE\n');stdout.flush()
            else:
                d=self.project/'build/pt_batch';d.mkdir()
                (d/'complete').write_text('MOCK REPORT COMPLETION')
                for corner in ['ss','ff','tt']:
                    (d/('area_'+corner+'.rpt')).write_text('Timing Path Group accel_clk (max_delay/setup)\nCritical Path Slack: 0\nTotal Negative Slack: 0\nNo. of Violating Paths: 0\nTiming Path Group accel_clk (min_delay/hold)\nCritical Path Slack: -1\nTotal Negative Slack: -1\nNo. of Violating Paths: 1\n')
                    for prefix in ['coverage_','coverage_untested_','check_timing_','constraints_']:(d/(prefix+corner+'.rpt')).write_text('MOCK')
                stdout.write('MOCK ONLY\nKWT_CLEAN_PT_DONE\n');stdout.flush()
        def poll(self):
            self.polls+=1
            if self.polls<2:return None
            if not self.done:live[0]-=1;self.done=True
            return self.code
    namespace['subprocess']=types.SimpleNamespace(Popen=MockProcess,STDOUT=subprocess.STDOUT)
    namespace['time']=types.SimpleNamespace(sleep=lambda n:None,strftime=lambda *a:'MOCK_TIME',gmtime=lambda:None)
    namespace['shutil']=types.SimpleNamespace(which=lambda name:'/mock_lc/bin/lc_shell')
    isfile=namespace['os'].path.isfile;access=namespace['os'].access
    with patch.object(sys,'argv',['batch_run.py','run','--jobs','4','--cores-per-job','4']),patch('os.path.isfile',side_effect=lambda p:True if str(p).startswith('/eda/') else isfile(p)),patch('os.access',side_effect=lambda p,m:True if str(p).replace('\\','/').startswith(('/eda/','/mock_lc/')) else access(p,m)),contextlib.redirect_stdout(io.StringIO()):
        namespace['main']()
    states=json.loads((target/'states.json').read_text())['projects']
    assert peak[0]==4 and live[0]==0
    assert states['overlap']['stage']=='failed_dc'
    assert all(states[name]['stage']=='reports_done' for name in ['baseline8','refine','writeback'])
    assert all(states[name]['timing_signoff'] is False for name in ['baseline8','refine','writeback'])
    summary=dict(passed=True,transport_and_stdin_reconstructed=True,Python36_runtime_syntax=True,four_project_source_checks=True,
                 base_and_live_marker_preserved=True,no_old_build_copied=True,existing_batch_refused=True,bad_asset_rejected=True,
                 source_drift_rejected=True,hold_fix_disabled_hold_constraints_retained=True,production_BLOCK_STREAM1=True,
                 per_project_WORK_and_alib_isolated=True,mock_peak_concurrent_jobs=peak[0],mock_failed_job_did_not_stop_other_three=True,
                 dry_run_did_not_launch=True,actual_server_or_EDA_started=False,scope='transport/source/Tcl separately mocked and scheduler control only')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
