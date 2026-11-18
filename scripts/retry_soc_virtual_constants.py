"""Python 3.6 retry accounting failure, retain all earlier block/checkpoint evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT=Path('/home/2026contest/server6/s6_43usr/Desktop/project/kwt_soc_input16_metrics_595724b_tt_20261112')


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def progress_tb(data):
    anchor=b' initial begin #2000000000;$fatal(1,"SOC_GATE_WATCHDOG");end'
    assert data.count(anchor)==1 and b'SOC_PROGRESS ' not in data,'UNEXPECTED_PROGRESS_TEMPLATE'
    block=b''' // Read-only testbench heartbeat: no DUT writes and no simulation delays.
 always @(negedge hfextclk)begin
  if(ticks!=0&&(ticks%10000)==0)begin
   $display("SOC_PROGRESS recovery=%0d recovered=%0d ticks=%0d id=%0d compute=%0d packets=%0d ack=%0d params=%0d in=%0d out=%0d done=%0d",mode,recovered,ticks,id_seen,compute_seen,packets,ack,params,inputs,outputs,done);
   $fflush();
  end
 end
'''
    return data.replace(anchor,block+anchor)


def install(root,capsule):
    root=root.resolve()
    for k in ['KWT_PDK_ROOT','KWT_SRAM_DB_DIR']:assert os.environ.get(k) and Path(os.environ[k]).is_dir(),'SET_ENV_FIRST '+k
    env=dict(os.environ);lc=shutil.which('lc_shell')
    if lc and lc.endswith('/bin/lc_shell'):env['SYNOPSYS_LC_ROOT']=str(Path(lc).parent.parent)
    assert os.access(os.path.join(env.get('SYNOPSYS_LC_ROOT',''),'bin/lc_shell'),os.X_OK),'LC_ROOT_MISSING'
    spec=json.loads((capsule/'spec.json').read_text())
    for n,h in spec['assets'].items():assert sha(capsule/n)==h,'RETRY_ASSET_CHANGED'
    original=(root/'manifest.json').read_bytes();m=json.loads(original)
    assert m['RTL_revision']=='595724b88858b142a407f6a5c4761945252d523b','WRONG_INPUT16'
    for n,h in m['files'].items():assert sha(root/n)==h,'SOURCE_CHANGED '+n
    status=json.loads((root/'build/progress.json').read_text())
    assert status['stage']=='failed_preserve_evidence','QUEUE_NOT_FAILED'
    pid=int((root/'build/launch.lock').read_text());proc=Path('/proc')/str(pid)
    if proc.exists():
        try:
            args=(proc/'cmdline').read_bytes()
            assert not ((proc/'cwd').resolve()==root and (b'/recover.py' in args or b'flow/run.py' in args)),'QUEUE_STILL_RUNNING'
        except OSError:pass
    assert not (root/'build/dc/receipt.json').exists() and not (root/'build/gate').exists(),'LATER_NETLIST_OR_GATE_EXISTS'
    log=(root/'build/dc.console.log').read_text(errors='replace')
    fatal=[line for line in log.splitlines() if line.startswith('SOC_FATAL')]
    assert fatal and all('unbound leaf' in line and line.rstrip().endswith(('**logic_0**','**logic_1**')) for line in fatal),'NOT_THE_VIRTUAL_CONSTANT_FAILURE'
    assert 'Optimization Complete' in log and 'SOC_MACRO_COUNT 100' in log,'OPTIMIZATION_NOT_CONFIRMED'
    assert not re.search(r'^\s*Error:',log,re.M),'UNEXPECTED_NATIVE_DC_ERROR'
    checkpoint=root/'build/link_clock_clean_v1/clock_clean_soc.ddc'
    clock_proof=json.loads((root/'review_tools/soc_recovery_v1/clock_checkpoint.json').read_text())
    assert sha(checkpoint)==clock_proof['sha256'],'CLEAN_CLOCK_DDC_CHANGED'
    clock_log=(root/'build/link_clock_clean_v1.console.log').read_text(errors='replace')
    assert 'SOC_CLOCK_PREFLIGHT_DONE' in clock_log and not re.search(r'^\s*(?:Error:|SOC_FATAL)',clock_log,re.M),'CLOCK_PREFLIGHT_NOT_CLEAN'
    tb=root/'flow/tb_soc_metrics.sv';old_tb=tb.read_bytes();assert sha(tb)==spec['expected_TB_sha256'],'UNEXPECTED_TESTBENCH'
    new_tb=progress_tb(old_tb)
    sys_path=root/'review_tools/cpu_precompile_v1'
    import sys
    sys.path.insert(0,str(sys_path));import cpu_precompile
    cpu_precompile.ready(root)
    frozen=json.loads((root/'frozen_accel/input.json').read_text());assert sha(root/'frozen_accel/mapped.ddc')==frozen['ddc_sha256'],'ACCEL_CHANGED'
    work=root/'review_tools/soc_recovery_v2';assert not work.exists(),'PRESERVE_EXISTING_RETRY';work.mkdir()
    (work/'manifest.before.json').write_bytes(original);(work/'tb.before.sv').write_bytes(old_tb)
    for n in spec['assets']:(work/n).write_bytes((capsule/n).read_bytes())
    m['files']['flow/tb_soc_metrics.sv']=hashlib.sha256(new_tb).hexdigest()
    for n in spec['assets']:m['files']['review_tools/soc_recovery_v2/'+n]=sha(work/n)
    m['recovery_flow'].update(version='virtual_constants_retry_v2',previous_manifest_sha256=hashlib.sha256(original).hexdigest(),
        validated_clock_checkpoint_sha256=sha(checkpoint),clock_preflight_reused=True,virtual_constants_zero_area_only_if_unbound=True,
        heartbeat=dict(interval_cycles=10000,read_only=True,no_DUT_or_simulation_delay_changes=True))
    saved=work/'previous_mapping_failure';saved.mkdir()
    assert root in saved.resolve().parents,'ARCHIVE_ESCAPES_PROJECT'
    for n in ['dc','dc.console.log','dc.log','progress.json','launch.lock']:
        p=root/'build'/n
        if p.exists():
            assert p.resolve().parent==(root/'build').resolve(),'ARCHIVE_SOURCE_ESCAPES_BUILD'
            assert (saved/n).resolve().parent==saved.resolve(),'ARCHIVE_TARGET_ESCAPES_RETRY'
            p.rename(saved/n)
    try:
        temp=tb.with_suffix('.retry.tmp');temp.write_bytes(new_tb);os.replace(str(temp),str(tb))
        temp=root/'manifest.retry.tmp';temp.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n');os.replace(str(temp),str(root/'manifest.json'))
        for n,h in m['files'].items():assert sha(root/n)==h,'RETRY_SOURCE_CHECK_FAILED '+n
        env['SOC_REUSE_CLOCK_CHECKPOINT']='1'
        (root/'build/progress.json').write_text(json.dumps(dict(stage='retrying_virtual_constant_accounting',UTC=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())),indent=2)+'\n')
        with (work/'recovery.console.log').open('x') as output:
            p=subprocess.Popen([sys.executable,'-u',str(work/'recover.py'),'--worker',str(root),str(work)],cwd=str(root),env=env,
                stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        (root/'build/launch.lock').write_text(str(p.pid));(work/'launch.json').write_text(json.dumps(dict(pid=p.pid,CPU_and_accelerator_recompiled=False,clock_preflight_reused=True),indent=2)+'\n')
        print('SOC_VIRTUAL_CONSTANT_RETRY_STARTED pid='+str(p.pid))
    except Exception:
        tb.write_bytes(old_tb);(root/'manifest.json').write_bytes(original);raise


if __name__=='__main__':install(ROOT,Path(__file__).resolve().parent)
