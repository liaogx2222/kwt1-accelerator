"""Mock only the new cold-power orchestration and fail-stop behavior."""
import argparse
import ast
import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import start_soc_early_cold_power as target
ROOT=Path(__file__).resolve().parents[1]
ORIGINAL_PARSE=ast.parse


def parse_python36(source,filename='<unknown>',mode='exec'):
    # Runtime API shim intentionally rejects newer optional keyword arguments.
    return ORIGINAL_PARSE(source,filename,mode)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);results={}
    for case in ['cold_first','recovery_done','pt_exit_error','pt_log_error','saif_changed','main_failed']:
        root=out/case;work=root/'build/early_cold_power_v1';work.mkdir(parents=True)
        (root/'flow').mkdir();(root/'review_tools').mkdir();(root/'build/dc').mkdir()
        for n in ['pt.tcl','collect.py']:(root/'flow'/n).write_bytes((ROOT/'flow/soc_metrics'/n).read_bytes())
        original={n:(root/'flow'/n).read_bytes() for n in ['pt.tcl','collect.py']}
        (root/'manifest.json').write_text('{}');(root/'build/dc/mapped.v').write_text('MOCK_NETLIST_NOT_PPA')
        cold=root/'build/gate/cold';cold.mkdir(parents=True);(cold/'task.saif').write_text('MOCK_SAIF_NOT_PPA')
        if case!='main_failed':(cold/'result.json').write_text('{}')
        if case=='recovery_done':
            p=root/'build/gate/recovery';p.mkdir();(p/'result.json').write_text('{}')
        (root/'build/progress.json').write_text(json.dumps(dict(stage='failed_preserve_evidence' if case=='main_failed' else 'gate_cold_and_recovery_running_in_parallel')))
        events=[]
        def activity():events.append('verify_activity')
        def collect():events.append('collect');(root/'build/metrics_early_cold_v1.json').write_text('{"MOCK_NOT_PPA":true}')
        def load(path,name):return SimpleNamespace(activity=activity) if path.name=='project.py' else SimpleNamespace(collect=collect)
        def call(command,**kwargs):
            events.append('PT')
            assert str(work/'pt.tcl') in command and kwargs['cwd']==str(root)
            report=root/'build/pt_early_cold_v1';report.mkdir();(report/'complete').write_text('MOCK')
            kwargs['stdout'].write('Error: injected\n' if case=='pt_log_error' else 'SOC_FULL_PT_DONE\n')
            if case=='saif_changed':(cold/'task.saif').write_text('CHANGED_MOCK')
            return 1 if case=='pt_exit_error' else 0
        with patch.object(target,'load',load),patch.object(target.ast,'parse',parse_python36),patch.object(target.shutil,'which',return_value='/mock/bin/lc_shell'),patch.object(target.os,'access',return_value=True),patch.object(target.subprocess,'call',call),patch.dict(target.os.environ,dict(KWT_PDK_ROOT='/mock/pdk',KWT_SRAM_DB_DIR='/mock/ram')),contextlib.redirect_stdout(io.StringIO()):
            try:target.worker(root);passed=True
            except AssertionError:passed=False
        assert passed==(case in ['cold_first','recovery_done']),case
        assert all((root/'flow'/n).read_bytes()==data for n,data in original.items())
        assert not (root/'build/pt').exists(),'primary PT output touched'
        if case=='cold_first':assert events==['verify_activity','PT','verify_activity','collect'],events
        elif case=='recovery_done':assert events==['verify_activity'],events
        else:assert 'collect' not in events
        results[case]=dict(passed=True,events=events,worker_success=passed)
    ast.parse((ROOT/'scripts/start_soc_early_cold_power.py').read_text(),feature_version=(3,6))
    report=dict(passed=True,cases=results,actual_EDA=False,actual_power=False,scope='independent cold-power sequencing, primary output isolation, failure gates and SAIF mutation detection')
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print('EARLY_POWER_MOCK_PASS',len(results))


if __name__=='__main__':main()
