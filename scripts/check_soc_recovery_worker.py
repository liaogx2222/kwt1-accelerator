"""Recovery orchestration/failure checks with fake tools, no actual PPA."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch
import recover_soc_from_link as target


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);results={}
    for case in ['normal','reuse_clock','clock_error_in_log','clock_error_in_report','map_error','area_mismatch','PT_preflight_error','cold_error']:
        root=out/case;work=root/'review_tools/soc_recovery_v1';work.mkdir(parents=True)
        (root/'build/link_probe_v2').mkdir(parents=True);(root/'build/link_probe_v2/linked_soc.ddc').write_text('MOCK_LINKED')
        (root/'build/cpu_precompile_v1').mkdir();(root/'build/cpu_precompile_v1/receipt.json').write_text('MOCK_RECEIPT')
        (root/'manifest.json').write_text(json.dumps(dict(recovery_flow=dict(linked_checkpoint_sha256=target.sha(root/'build/link_probe_v2/linked_soc.ddc'),CPU_receipt_sha256=target.sha(root/'build/cpu_precompile_v1/receipt.json'),clock_preflight_reused=case=='reuse_clock'))))
        if case=='reuse_clock':
            folder=root/'build/link_clock_clean_v1';folder.mkdir();(folder/'clock_clean_soc.ddc').write_text('MOCK_CLEAN')
            (root/'build/link_clock_clean_v1.console.log').write_text('SOC_CLOCK_PREFLIGHT_DONE')
            (work/'clock_checkpoint.json').write_text(json.dumps(dict(sha256=target.sha(folder/'clock_clean_soc.ddc'))))
        events=[];power_started=threading.Event()
        def state(stage,**kwargs):events.append('state:'+stage)
        def execute(command,log,env=None,cwd=None):
            name=log.name;log.parent.mkdir(parents=True,exist_ok=True)
            if name=='link_clock_clean_v1.console.log':
                events.append('clock');p=root/'build/link_clock_clean_v1';p.mkdir();(p/'clock_clean_soc.ddc').write_text('MOCK_CLOCK_CLEAN')
                (p/'constraints_apply.rpt').write_text('Error: injected\n' if case=='clock_error_in_report' else 'MOCK_OK')
                text=('Error: injected\n' if case=='clock_error_in_log' else '')+'SOC_CLOCK_PREFLIGHT_DONE\n'
            elif name=='dc.console.log':
                events.append('map');text=('Error: injected\n' if case=='map_error' else '')+'SOC_FULL_DC_DONE\n'
                (root/'build/dc/reports').mkdir(parents=True);(root/'build/dc/mapped.v').write_text('MOCK_MAPPED')
                (root/'build/dc/reports/area.rpt').write_text('Total cell area: 1000.0' if case=='area_mismatch' else 'Total cell area: 128.0')
                (root/'build/dc/reports/area_ledger.tsv').write_text('accelerator\t128.0\n')
            elif name=='pt_preflight.console.log':
                events.append('preflight');text=('Error: injected\n' if case=='PT_preflight_error' else '')+'SOC_FULL_PT_DONE\n'
                p=root/'build/pt_preflight';p.mkdir();(p/'complete').write_text('MOCK_COMPLETE')
            elif name=='compile.log':events.append('compile_gate');text='MOCK_COMPILED'
            elif name=='pt.console.log':
                events.append('power');text='SOC_FULL_PT_DONE\n';p=root/'build/pt';p.mkdir();(p/'complete').write_text('MOCK_COMPLETE');power_started.set()
            else:raise AssertionError('unexpected tool '+str(log))
            log.write_text(text)
        def gate(mode,env):
            events.append('gate:'+mode)
            if mode=='cold':
                if case=='cold_error':raise AssertionError('injected cold failure')
                return
            if case=='cold_error':return
            assert power_started.wait(3),'power waited for recovery'
            events.append('recovery_done')
        pipeline=SimpleNamespace(DC='MOCK_DC',PT='MOCK_PT',VCS='MOCK_VCS',state=state,execute=execute,gate=gate)
        project=SimpleNamespace(netlist=lambda:events.append('verify_netlist'),activity=lambda:events.append('verify_activity'))
        collect=SimpleNamespace(collect=lambda:events.append('collect'))
        with patch.dict(sys.modules,{'run':pipeline,'project':project,'collect':collect}),patch.object(target.shutil,'which',return_value='/mock/bin/lc_shell'),patch.object(target.os,'access',return_value=True),patch.dict(target.os.environ,{'KWT_PDK_ROOT':'/mock/pdk','KWT_SRAM_DB_DIR':'/mock/ram'}),contextlib.redirect_stdout(io.StringIO()):
            try:target.worker(root,work);success=True
            except AssertionError:success=False
        assert success==(case in ['normal','reuse_clock']),(case,events)
        if success:
            assert events.index('power')<events.index('recovery_done') and 'collect' in events
            assert events[-1]=='state:reports_ready_for_review'
        else:
            assert 'collect' not in events
            assert events[-1]=='state:failed_preserve_evidence'
            if case.startswith('clock_'):assert 'map' not in events
            if case=='map_error':assert 'compile_gate' not in events
            if case=='area_mismatch':assert 'preflight' not in events
            if case=='PT_preflight_error':assert 'compile_gate' not in events
        results[case]=dict(passed=True,worker_success=success,events=events)
    (out/'summary.json').write_text(json.dumps(dict(passed=True,actual_EDA=False,actual_power=False,cases=results),indent=2)+'\n')
    print('RECOVERY_WORKER_CONTROL_PASS',len(results))


if __name__=='__main__':main()
