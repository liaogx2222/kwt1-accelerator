"""Exercise wait-queue patch, refusal and rollback with simulated /proc/signals."""
import argparse
import ast
import contextlib
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import patch
import patch_soc_saif_string as target
ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
    out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    source=ROOT/'deliverables/input16_soc_metrics_TT_release_20261112_v3/project'
    results={}
    for case in ['normal','wrong_release','source_drift','advanced','race_after_stop','write_failure','wrong_pid']:
        root=out/case;shutil.copytree(source,root);(root/'build').mkdir()
        (root/'build/launch.lock').write_text('12345')
        progress=root/'build/progress.json';progress.write_text(json.dumps(dict(stage='waiting_for_running_input16_DC')))
        if case=='wrong_release':(root/'manifest.json').write_text('{}')
        if case=='source_drift':
            n=next(iter(json.loads((root/'manifest.json').read_bytes())['files']))
            p=root/n;p.write_bytes(p.read_bytes()+b'\n')
        if case=='advanced':progress.write_text(json.dumps(dict(stage='mapping_platform_with_frozen_accelerator')))
        before_manifest=(root/'manifest.json').read_bytes();before_tb=(root/'flow/tb_soc_metrics.sv').read_bytes()
        events=[];replacements=[]
        class ProcFile:
            def __init__(self,name):self.name=name
            def resolve(self):return out if case=='wrong_pid' else root
            def read_bytes(self):return b'python3\x00-u\x00flow/run.py\x00'
            def read_text(self):return 'State:\tT (stopped)\n'
        class Proc:
            def __truediv__(self,name):return ProcFile(name)
        class ProcRoot:
            def __truediv__(self,name):assert name=='12345';return Proc()
        def path(value):return ProcRoot() if value=='/proc' else Path(value)
        def kill(pid,sig):
            assert pid==12345;events.append(sig)
            if case=='race_after_stop' and sig==19:progress.write_text(json.dumps(dict(stage='mapping_platform_with_frozen_accelerator')))
        actual_replace=target.os.replace
        def replace(src,dst):
            replacements.append(str(dst))
            if case=='write_failure' and len(replacements)==2:raise OSError('injected second replace failure')
            return actual_replace(src,dst)
        with patch.object(target,'Path',path),patch.object(target,'signal',SimpleNamespace(SIGSTOP=19,SIGCONT=18)),patch.object(target.os,'kill',kill),patch.object(target.os,'replace',replace),contextlib.redirect_stdout(io.StringIO()):
            try:target.install(root);success=True
            except (AssertionError,OSError):success=False
        assert success==(case=='normal'),case
        if case=='normal':
            manifest=json.loads((root/'manifest.json').read_bytes())
            for n,h in manifest['files'].items():assert target.sha((root/n).read_bytes())==h
            assert events==[19,18]
            assert (root/'flow/run.py').read_bytes()==(source/'flow/run.py').read_bytes()
            assert b'$toggle_report(saif_filename,' in (root/'flow/tb_soc_metrics.sv').read_bytes()
        else:
            assert (root/'manifest.json').read_bytes()==before_manifest and (root/'flow/tb_soc_metrics.sv').read_bytes()==before_tb,case
            assert events==([19,18] if case in ['race_after_stop','write_failure'] else []),(case,events)
        results[case]=dict(passed=True,signals=events,installation_success=success)
    ast.parse((ROOT/'scripts/patch_soc_saif_string.py').read_text(),feature_version=(3,6))
    report=dict(passed=True,actual_Linux_signals=False,actual_VCS=False,cases=results,
        scope='local source binding, simulated PID identity, exact queue pause/resume, race refusal and failure rollback')
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print('SOC_SAIF_PATCH_TESTS_PASS '+str(len(results)))


if __name__=='__main__':main()
