"""Python 3.6: preserve failed stage, reuse two DDCs, map glue, gate, power."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT=Path('/path/to/project/kwt_soc_input16_metrics_595724b_tt_20261112')


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def live_original_queue(root):
    lock=root/'build/launch.lock'
    if not lock.is_file():return False
    pid=int(lock.read_text());proc=Path('/proc')/str(pid)
    try:
        return (proc/'cwd').resolve()==root.resolve() and b'flow/run.py' in (proc/'cmdline').read_bytes().split(b'\0')
    except (OSError,RuntimeError):return False


def archive_failed(root,work):
    assert not live_original_queue(root),'MAIN_QUEUE_STILL_RUNNING'
    status=json.loads((root/'build/progress.json').read_text())
    assert status['stage']=='failed_preserve_evidence','MAIN_NOT_AT_EXPECTED_FAILED_STAGE'
    assert not (root/'build/dc/receipt.json').exists(),'PRESERVE_COMPLETED_SOC_NETLIST'
    assert not (root/'build/gate').exists() and not (root/'build/pt').exists(),'LATER_SOC_STAGE_ALREADY_EXISTS'
    saved=work/'failed_before_recovery';saved.mkdir()
    assert root.resolve() in saved.resolve().parents,'RECOVERY_ARCHIVE_ESCAPES_PROJECT'
    for name in ['dc','dc.console.log','dc.log','launch.lock','progress.json']:
        path=root/'build'/name
        if not path.exists():continue
        assert path.resolve().parent==(root/'build').resolve(),'ARCHIVE_SOURCE_ESCAPES_BUILD'
        target=saved/name
        assert target.resolve().parent==saved.resolve(),'ARCHIVE_TARGET_ESCAPES_RECOVERY'
        path.rename(target)


def checked_execute(pipeline,command,log,env,marker):
    pipeline.execute(command,log,env)
    text=log.read_text(errors='replace')
    assert marker in text and not re.search(r'^\s*(?:Error:|SOC_FATAL)',text,re.M),'RECOVERY_TOOL_ERROR '+str(log)


def check_reports(folder):
    for p in folder.rglob('*.rpt'):
        assert not re.search(r'^\s*Error:',p.read_text(errors='replace'),re.M),'RECOVERY_REPORT_ERROR '+str(p)


def check_area_ledger(root):
    reports=root/'build/dc/reports'
    rows=[line.split() for line in (reports/'area_ledger.tsv').read_text().splitlines()]
    total=sum(float(value) for name,value in rows)
    text=(reports/'area.rpt').read_text()
    reported=float(re.search(r'Total cell area:\s+([0-9.eE+-]+)',text).group(1))
    # Match the existing collector's 1e-5 mm2 report-rounding tolerance.
    assert abs(total-reported)<=10.0,'AREA_LEDGER_NOT_EQUAL_FULL_DESIGN'
    print('SOC_AREA_LEDGER_RECONCILED library_units='+str(reported),flush=True)


def worker(root,work):
    sys.path.insert(0,str(root/'flow'))
    import run as pipeline
    import project
    try:
        env=dict(os.environ);lc=shutil.which('lc_shell')
        if lc and lc.endswith('/bin/lc_shell'):env['SYNOPSYS_LC_ROOT']=str(Path(lc).parent.parent)
        assert os.access(os.path.join(env.get('SYNOPSYS_LC_ROOT',''),'bin/lc_shell'),os.X_OK),'LC_ROOT_MISSING'
        env.pop('SOC_PT_PREFLIGHT',None);env.pop('KWT_GATE_SAIF',None)
        source=json.loads((root/'manifest.json').read_text())['recovery_flow']
        assert sha(root/'build/link_probe_v2/linked_soc.ddc')==source['linked_checkpoint_sha256'],'LINKED_CHECKPOINT_CHANGED'
        assert sha(root/'build/cpu_precompile_v1/receipt.json')==source['CPU_receipt_sha256'],'CPU_RECEIPT_CHANGED'
        checkpoint=root/'build/link_clock_clean_v1/clock_clean_soc.ddc'
        if env.get('SOC_REUSE_CLOCK_CHECKPOINT')=='1' or source.get('clock_preflight_reused',False):
            pipeline.state('reusing_verified_clock_checkpoint')
            saved=json.loads((root/'review_tools/soc_recovery_v1/clock_checkpoint.json').read_text())
            assert sha(checkpoint)==saved['sha256'],'VERIFIED_CLOCK_CHECKPOINT_CHANGED'
            text=(root/'build/link_clock_clean_v1.console.log').read_text(errors='replace')
            assert 'SOC_CLOCK_PREFLIGHT_DONE' in text and not re.search(r'^\s*(?:Error:|SOC_FATAL)',text,re.M),'OLD_CLOCK_PREFLIGHT_NOT_CLEAN'
            check_reports(root/'build/link_clock_clean_v1')
        else:
            pipeline.state('checking_linked_checkpoint_clocks')
            checked_execute(pipeline,[pipeline.DC,'-f',str(work/'clock_preflight.tcl'),'-output_log_file','build/link_clock_clean_v1.dc.log'],root/'build/link_clock_clean_v1.console.log',env,'SOC_CLOCK_PREFLIGHT_DONE')
            check_reports(root/'build/link_clock_clean_v1')
            assert sha(root/'build/link_probe_v2/linked_soc.ddc')==source['linked_checkpoint_sha256'],'LINKED_CHECKPOINT_CHANGED_DURING_PREFLIGHT'
        assert checkpoint.is_file(),'CLEAN_CLOCK_CHECKPOINT_MISSING'
        (work/'clock_checkpoint.json').write_text(json.dumps(dict(sha256=sha(checkpoint),linked_input_sha256=sha(root/'build/link_probe_v2/linked_soc.ddc')),indent=2)+'\n')
        pipeline.state('mapping_glue_with_frozen_accelerator_and_CPU')
        checked_execute(pipeline,[pipeline.DC,'-f',str(work/'map.tcl'),'-output_log_file','build/dc.log'],root/'build/dc.console.log',env,'SOC_FULL_DC_DONE')
        check_reports(root/'build/dc')
        check_area_ledger(root)
        project.netlist();pipeline.state('TT_link_timing_power_capability_preflight')
        checked_execute(pipeline,[pipeline.PT,'-f','flow/pt.tcl'],root/'build/pt_preflight.console.log',dict(env,SOC_PT_PREFLIGHT='1'),'SOC_FULL_PT_DONE')
        check_reports(root/'build/pt_preflight')
        assert (root/'build/pt_preflight/complete').is_file(),'PT_PREFLIGHT_NOT_COMPLETE'
        pipeline.state('compiling_full_SoC_gate_model')
        model=root/'build/gate/model';model.mkdir(parents=True)
        cells=[str(Path(env['KWT_PDK_ROOT'])/('SCC40NLL_VHSC40_'+vt+'_V0.1')/('SCC40NLL_VHSC40_'+vt+'_V0p1')/'verilog'/('scc40nll_vhsc40_'+vt.lower()+'.v')) for vt in ['HVT','LVT','RVT']]
        pipeline.execute([pipeline.VCS,'-full64','-sverilog','-lca','-timescale=1ns/1ps','+define+SOC_SAIF','-top','tb_soc_metrics',*cells,
            str(root/'flow/sram_contract_ret1n.v'),str(root/'build/dc/mapped.v'),str(root/'flow/tb_soc_metrics.sv'),'-o',str(model/'simv')],model/'compile.log',env,model)
        pipeline.state('gate_cold_and_recovery_running_in_parallel')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            cold=pool.submit(pipeline.gate,'cold',env);recovery=pool.submit(pipeline.gate,'recovery',env)
            try:cold.result()
            except Exception as e:
                pipeline.state('failed_preserve_evidence',error='cold gate failed; recovery may still be running: '+str(e));raise
            project.activity()
            pipeline.state('cold_passed_TT_power_recovery_may_be_running')
            checked_execute(pipeline,[pipeline.PT,'-f','flow/pt.tcl'],root/'build/pt.console.log',env,'SOC_FULL_PT_DONE')
            check_reports(root/'build/pt')
            assert (root/'build/pt/complete').is_file(),'PT_NOT_COMPLETE'
            import collect
            collect.collect()
            recovery.result()
        pipeline.state('reports_ready_for_review',timing_signoff=False,power_coverage_review_required=True)
    except Exception as error:
        pipeline.state('failed_preserve_evidence',error=str(error));raise


def install(root,capsule):
    root=root.resolve()
    for key in ['KWT_PDK_ROOT','KWT_SRAM_DB_DIR']:assert os.environ.get(key) and Path(os.environ[key]).is_dir(),'SET_ENV_FIRST '+key
    env=dict(os.environ);lc=shutil.which('lc_shell')
    if lc and lc.endswith('/bin/lc_shell'):env['SYNOPSYS_LC_ROOT']=str(Path(lc).parent.parent)
    assert os.access(os.path.join(env.get('SYNOPSYS_LC_ROOT',''),'bin/lc_shell'),os.X_OK),'LC_ROOT_MISSING_BEFORE_RECOVERY'
    work=root/'review_tools/soc_recovery_v1';assert not work.exists(),'PRESERVE_EXISTING_RECOVERY'
    spec=json.loads((capsule/'spec.json').read_text())
    for name,h in spec['assets'].items():assert sha(capsule/name)==h,'RECOVERY_ASSET_CHANGED'
    original=(root/'manifest.json').read_bytes();m=json.loads(original)
    assert m['RTL_revision']=='595724b88858b142a407f6a5c4761945252d523b','WRONG_INPUT16'
    for n,h in m['files'].items():assert sha(root/n)==h,'SOURCE_CHANGED '+n
    assert '$toggle_report(saif_filename,' in (root/'flow/tb_soc_metrics.sv').read_text(),'SAIF_FIX_REQUIRED'
    probe=root/'build/link_probe_v2.console.log';text=probe.read_text(errors='replace')
    assert 'SOC_LINK_PROBE_PASS' in text and 'SOC_MACRO_COUNT 100' in text and 'SOC_PROBE_CPU_CACHE 1' in text,'LINKED_CPU_ACCEL_CHECKPOINT_NOT_CONFIRMED'
    errors=re.findall(r'^\s*Error:.*$',text,re.M)
    assert all('clock_list' in e and 'CMD-036' in e for e in errors),'UNEXPECTED_LINK_PROBE_ERROR'
    assert 'SOC_FATAL ' not in '\n'.join(line for line in text.splitlines() if line.startswith('SOC_FATAL')),'LINK_PROBE_FATAL'
    sys.path.insert(0,str(root/'review_tools/cpu_precompile_v1'))
    import cpu_precompile
    cpu_precompile.ready(root)
    frozen=json.loads((root/'frozen_accel/input.json').read_text())
    assert sha(root/'frozen_accel/mapped.ddc')==frozen['ddc_sha256'],'ACCEL_DDC_CHANGED'
    work.mkdir(parents=True)
    for name in spec['assets']:(work/name).write_bytes((capsule/name).read_bytes())
    (work/'manifest.before.json').write_bytes(original)
    m['recovery_flow']=dict(version='linked_DDC_clock_clean_v1',linked_checkpoint_sha256=sha(root/'build/link_probe_v2/linked_soc.ddc'),
        CPU_receipt_sha256=sha(root/'build/cpu_precompile_v1/receipt.json'),original_manifest_sha256=hashlib.sha256(original).hexdigest(),
        original_link_probe_clock_error_preserved=True,numerical_RTL_unchanged=True)
    for name in spec['assets']:m['files']['review_tools/soc_recovery_v1/'+name]=sha(work/name)
    archive_failed(root,work)
    try:
        tmp=root/'manifest.recovery.tmp';tmp.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n');os.replace(str(tmp),str(root/'manifest.json'))
        (root/'build/progress.json').write_text(json.dumps(dict(stage='soc_recovery_starting',UTC=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())),indent=2)+'\n')
        with (work/'recovery.console.log').open('x') as log:
            p=subprocess.Popen([sys.executable,'-u',str(work/'recover.py'),'--worker',str(root),str(work)],cwd=str(root),
                env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        (root/'build/launch.lock').write_text(str(p.pid))
        (work/'launch.json').write_text(json.dumps(dict(pid=p.pid,main_CPU_and_accelerator_recompiled=False),indent=2)+'\n')
        print('SOC_RECOVERY_STARTED pid='+str(p.pid))
    except Exception:
        # Source rollback; failed-stage archive remains readable for diagnosis.
        (root/'manifest.json').write_bytes(original);raise


if __name__=='__main__':
    if len(sys.argv)==4 and sys.argv[1]=='--worker':worker(Path(sys.argv[2]),Path(sys.argv[3]))
    else:install(ROOT,Path(__file__).resolve().parent)
