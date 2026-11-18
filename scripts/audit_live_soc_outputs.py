"""Python 3.6 live audit: read logs; only temporary 4KiB write/fsync probes."""
from datetime import datetime,timedelta
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ERROR=re.compile(r'^\s*(?:Error(?::|-\[)|SOC_FATAL\b|Fatal(?::|-\[)|%Fatal|%Error|AssertionError:|Traceback \(most recent call last\):)|SAIF_REPORT_ARG_CHECK|No space left on device|Disk quota exceeded|File size limit exceeded')
LOGS=['build/link_clock_clean_v1.console.log','build/dc.console.log','build/pt_preflight.console.log',
      'build/gate/model/compile.log','build/gate/cold/run.log','build/gate/recovery/run.log',
      'review_tools/soc_recovery_v2/recovery.console.log','build/pt.console.log']


def scan_logs(root):
    count=0
    for name in LOGS:
        p=root/name
        if not p.is_file():continue
        hits=[]
        with p.open(errors='replace') as stream:
            for i,line in enumerate(stream,1):
                if ERROR.search(line):hits.append((i,line.rstrip()))
        count+=len(hits)
        print('LOG_CHECK '+name+' errors='+str(len(hits)))
        for i,line in hits[:6]:print('  line '+str(i)+' '+line[:300])
    print('ACTIVE_LOG_ERROR_COUNT '+str(count))
    return count


def write_probes(root):
    for name in ['build','build/gate/cold','build/gate/recovery']:
        p=root/name
        if not p.is_dir():print('WRITE_PROBE_NOT_CREATED_YET '+name);continue
        try:
            with tempfile.TemporaryFile(prefix='.soc_save_probe_',dir=str(p)) as stream:
                assert stream.write(b'0'*4096)==4096
                stream.flush();os.fsync(stream.fileno())
            print('WRITE_FSYNC_OK '+name)
        except OSError as error:print('WRITE_FSYNC_FAILED '+name+' '+str(error))


def audit(root):
    root=root.resolve()
    print('AUDIT_CST '+(datetime.utcnow()+timedelta(hours=8)).isoformat())
    assert root.name=='kwt_soc_input16_metrics_595724b_tt_20261112','RUN_IN_CURRENT_SOC_PROJECT'
    scan_logs(root)
    tb=(root/'flow/tb_soc_metrics.sv').read_text()
    print('SAIF_STRING_AND_FILE_GUARDS '+str(all(x in tb for x in ['$toggle_report(saif_filename,','SOC_SAIF_NOT_CREATED','SOC_SAIF_EMPTY'])))
    usage=shutil.disk_usage(str(root));print('FILESYSTEM_FREE_GiB %.2f'%(usage.free/float(1024**3)))
    if hasattr(os,'statvfs'):
        s=os.statvfs(str(root));print('FREE_INODES '+(str(s.f_favail) if s.f_files else 'not reported by filesystem'))
    write_probes(root)
    for mode in ['cold','recovery']:
        p=root/('build/gate/'+mode+'/run.log')
        if p.is_file():
            lines=p.read_text(errors='replace').splitlines()
            latest=next((line for line in reversed(lines) if line.startswith(('SOC_PROGRESS','PASS SOC_INPUT16_GATE','SOC_GATE_METRICS'))),'no progress marker')
            print('LATEST '+mode+' '+latest)
        saif=root/('build/gate/'+mode+'/task.saif')
        print('SAIF_FILE '+mode+' '+(str(saif.stat().st_size)+' bytes' if saif.exists() else 'not created yet; generated at successful task end'))
    for name in ['build/pt','build/metrics_reference.json']:
        print('FUTURE_OUTPUT '+name+' exists='+str((root/name).exists()))
    report=root/'build/pt_preflight/power_soc_tt.rpt'
    if report.is_file():
        try:
            spec=importlib.util.spec_from_file_location('soc_audit_collector',str(root/'flow/collect.py'))
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            text=report.read_text(errors='replace')
            module.power(text,'Total Dynamic Power','Dynamic');module.power(text,'Cell Leakage Power','Leakage')
            print('PREFLIGHT_POWER_FORMAT_PARSE_OK not_task_power')
        except Exception as error:print('PREFLIGHT_POWER_FORMAT_PARSE_FAILED '+str(error))
    if Path('/proc').is_dir():
        listing=subprocess.check_output(['ps','-u',str(os.getuid()),'-o','pid=,comm=']).decode(errors='replace')
        for line in listing.splitlines():
            fields=line.split()
            if len(fields)<2 or not fields[1].startswith('simv'):continue
            p=Path('/proc')/fields[0]
            try:
                args=(p/'cmdline').read_bytes().decode(errors='replace').split('\0')
                if str(root/'build/gate/model/simv') not in args:continue
                print('SIMV_LIMITS pid='+fields[0]+' '+next((v for v in args if v.startswith('+RECOVERY=')),'mode=?'))
                for v in (p/'limits').read_text().splitlines():
                    if v.startswith(('Max cpu time','Max file size','Max open files','Max address space')):print('  '+v)
            except OSError as error:print('PROCESS_ENDED_OR_UNREADABLE '+str(error))
    quota=shutil.which('quota')
    if quota:
        try:
            p=subprocess.run([quota,'-s'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=8)
            print('QUOTA_STATUS rc='+str(p.returncode)+' '+p.stdout.decode(errors='replace')[:2000])
        except Exception as error:print('QUOTA_STATUS_UNAVAILABLE '+str(error))
    else:print('QUOTA_TOOL_NOT_AVAILABLE filesystem_free_space_does_not_prove_personal_quota')
    print('AUDIT_COMPLETE no_existing_result_or_running_source_modified')


if __name__=='__main__':audit(Path.cwd())
