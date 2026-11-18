"""Python 3.6; cold-result TT power watcher, independent of recovery completion."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

SERVER_ROOT='/home/2026contest/server6/s6_43usr/Desktop/project/kwt_soc_input16_metrics_595724b_tt_20261112'
PT='/eda/synopsys/prime/prime_2022.03-SP5-1/bin/pt_shell'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def sidecars(root):
    source=(root/'flow/pt.tcl').read_text()
    anchor='[file join [file dirname [info script]] common.tcl]'
    assert source.count(anchor)==1 and source.count('set OUT $PROJECT/build/pt\n')==1,'PT_TEMPLATE_CHANGED'
    pt=source.replace(anchor,'[file join [pwd] flow common.tcl]').replace('set OUT $PROJECT/build/pt\n','set OUT $PROJECT/build/pt_early_cold_v1\n')
    assert 'foreach corner {tt}' in pt and 'read_saif $PROJECT/build/gate/cold/task.saif' in pt
    source=(root/'flow/collect.py').read_text()
    assert source.count('build/pt/power_soc_tt.rpt')==1 and source.count('build/metrics_reference.json')==1,'COLLECT_TEMPLATE_CHANGED'
    collect=source.replace('build/pt/power_soc_tt.rpt','build/pt_early_cold_v1/power_soc_tt.rpt').replace('build/metrics_reference.json','build/metrics_early_cold_v1.json')
    collect=collect.replace("        coverage_review_required=True,SRAM_library_power_review_required=True,", "        evidence_stage='cold_passed_recovery_not_required_for_this_power_estimate',\n        coverage_review_required=True,SRAM_library_power_review_required=True,")
    # The executing server Python 3.6 is itself the syntax compatibility check.
    ast.parse(collect)
    return pt,collect


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,str(path));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def state(work,stage,**fields):
    value=dict(stage=stage,UTC=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),**fields)
    temp=work/'progress.tmp';temp.write_text(json.dumps(value,indent=2)+'\n');os.replace(str(temp),str(work/'progress.json'))
    print(stage,flush=True)


def worker(root):
    work=root/'build/early_cold_power_v1';assert work.is_dir()
    try:
        pt_text,collect_text=sidecars(root)
        (work/'pt.tcl').write_text(pt_text)
        # A same-root review_tools path retains the collector's ROOT derivation.
        collector=root/'review_tools/collect_early_cold_v1.py'
        assert not collector.exists(),'PRESERVE_EARLY_COLLECTOR'
        collector.write_text(collect_text)
        env=dict(os.environ);env.pop('SOC_PT_PREFLIGHT',None);env.pop('KWT_GATE_SAIF',None)
        lc=shutil.which('lc_shell')
        if lc and lc.endswith('/bin/lc_shell'):env['SYNOPSYS_LC_ROOT']=str(Path(lc).parent.parent)
        assert os.access(os.path.join(env.get('SYNOPSYS_LC_ROOT',''),'bin/lc_shell'),os.X_OK),'EARLY_LC_ROOT_MISSING'
        for key in ['KWT_PDK_ROOT','KWT_SRAM_DB_DIR']:assert env.get(key),'EARLY_MISSING_ENV '+key
        assert os.access(PT,os.X_OK),'EARLY_PT_EXECUTABLE_MISSING'
        project=load(root/'flow/project.py','early_soc_project')
        state(work,'waiting_for_verified_cold_gate')
        while not (root/'build/gate/cold/result.json').is_file():
            status=json.loads((root/'build/progress.json').read_text())
            assert status['stage']!='failed_preserve_evidence','MAIN_QUEUE_FAILED '+str(status)
            time.sleep(15)
        project.activity()
        # If recovery also finished, let the primary queue produce its normal
        # report instead of starting a simultaneous duplicate PT invocation.
        if (root/'build/gate/recovery/result.json').is_file():
            state(work,'cold_and_recovery_already_done_primary_queue_owns_power')
            return
        assert not (root/'build/pt_early_cold_v1').exists(),'PRESERVE_EARLY_PT_REPORTS'
        inputs=dict(manifest_sha256=sha(root/'manifest.json'),netlist_sha256=sha(root/'build/dc/mapped.v'),
            saif_sha256=sha(root/'build/gate/cold/task.saif'),source_PT_sha256=sha(root/'flow/pt.tcl'),
            source_collector_sha256=sha(root/'flow/collect.py'),PT_sidecar_sha256=sha(work/'pt.tcl'))
        (work/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
        state(work,'running_TT_power_while_recovery_continues')
        with (work/'pt.console.log').open('x') as log:
            rc=subprocess.call([PT,'-f',str(work/'pt.tcl')],cwd=str(root),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        text=(work/'pt.console.log').read_text(errors='replace')
        assert rc==0 and (root/'build/pt_early_cold_v1/complete').is_file(),'EARLY_PT_FAILED'
        assert not re.search(r'^(?:Error:|SOC_FATAL)',text,re.M),'EARLY_PT_ERROR_GATE'
        project.activity()
        assert inputs['saif_sha256']==sha(root/'build/gate/cold/task.saif'),'EARLY_ACTIVITY_CHANGED'
        assert inputs['manifest_sha256']==sha(root/'manifest.json'),'EARLY_SOURCE_CHANGED'
        load(collector,'early_soc_collector').collect()
        state(work,'cold_metrics_ready_recovery_and_coverage_review_remain',metrics=str(root/'build/metrics_early_cold_v1.json'))
    except Exception as e:
        state(work,'failed_preserve_early_evidence',error=str(e));raise


def start(root):
    root=root.resolve()
    for key in ['KWT_PDK_ROOT','KWT_SRAM_DB_DIR']:
        assert os.environ.get(key) and Path(os.environ[key]).is_dir(),'SET_ENV_BEFORE_START '+key
    manifest=json.loads((root/'manifest.json').read_text())
    assert manifest['RTL_revision']=='595724b88858b142a407f6a5c4761945252d523b','WRONG_INPUT16_RTL'
    tb=(root/'flow/tb_soc_metrics.sv').read_text()
    assert '$toggle_report(saif_filename,' in tb and 'SOC_SAIF_NOT_CREATED' in tb,'INSTALL_SAIF_STRING_PATCH_FIRST'
    project=load(root/'flow/project.py','early_soc_project');project.check()
    sidecars(root)
    assert (root/'build/launch.lock').is_file(),'MAIN_QUEUE_NOT_STARTED'
    work=root/'build/early_cold_power_v1';assert not work.exists(),'EARLY_WORKER_ALREADY_EXISTS'
    work.mkdir()
    with (work/'watcher.console.log').open('x') as log:
        p=subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--worker',str(root)],cwd=str(root),
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    (work/'launch.json').write_text(json.dumps(dict(pid=p.pid,scope='same full SoC cold task TT estimate; does not wait for recovery',
        script_sha256=sha(Path(__file__)),numerical_RTL_changed=False,main_queue_restarted=False),indent=2)+'\n')
    print('SOC_EARLY_COLD_POWER_WATCHER_STARTED pid='+str(p.pid))
    print('SOC_EARLY_POWER_PROGRESS '+str(work/'progress.json'))


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--worker':worker(Path(sys.argv[2]))
    else:start(Path(SERVER_ROOT))
