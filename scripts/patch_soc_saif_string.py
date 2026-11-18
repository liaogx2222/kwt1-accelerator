"""Python 3.6; pause only the waiting queue, patch SAIF I/O, resume it."""
import hashlib
import json
import os
from pathlib import Path
import signal
import time


def sha(data):return hashlib.sha256(data).hexdigest()


def updated_tb(data):
    before=b'   $toggle_report({outdir,"/task.saif"},1.0e-9,"tb_soc_metrics.dut");'
    after=b'''   saif_filename={outdir,"/task.saif"};
   $toggle_report(saif_filename,1.0e-9,"tb_soc_metrics.dut");
   saif_fd=$fopen(saif_filename,"r");
   if(saif_fd==0)$fatal(1,"SOC_SAIF_NOT_CREATED");
   if($fgetc(saif_fd)==-1)$fatal(1,"SOC_SAIF_EMPTY");
   $fclose(saif_fd);'''
    decl=b' reg activity_started=0,activity_closed=0;realtime activity_begin,activity_end;'
    assert data.count(before)==1 and data.count(decl)==1,'UNEXPECTED_SAIF_TEMPLATE'
    return data.replace(before,after).replace(decl,decl+b'\n string saif_filename;integer saif_fd;')


def install(root):
    root=root.resolve()
    expected=json.loads((Path(__file__).with_name('soc_saif_patch_spec.json')).read_text())
    original=(root/'manifest.json').read_bytes()
    assert sha(original)==expected['manifest_sha256'],'WRONG_SOC_QUEUE_RELEASE'
    tb=root/'flow/tb_soc_metrics.sv';old=tb.read_bytes()
    assert sha(old)==expected['tb_sha256'],'WRONG_SOC_TESTBENCH'
    new=updated_tb(old)
    manifest=json.loads(original)
    for n,h in manifest['files'].items():assert sha((root/n).read_bytes())==h,'SOURCE_DRIFT '+n
    manifest['files']['flow/tb_soc_metrics.sv']=sha(new)
    manifest['SAIF_capture_patch']=dict(version='string_argument_v1',original_manifest_sha256=sha(original),
        original_tb_sha256=sha(old),new_tb_sha256=sha(new),functional_RTL_unchanged=True,
        evidence='2026-11-12 native VCS Q-2020.03-SP2-6 probe: literal.saif and string.saif 507 bytes; packed/concat rejected')
    replacement=(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode()
    backup=root/'review_tools/saif_string_patch_v1'
    assert not backup.exists(),'PRESERVE_PREVIOUS_PATCH'
    pid=int((root/'build/launch.lock').read_text())
    proc=Path('/proc')/str(pid)
    assert (proc/'cwd').resolve()==root,'QUEUE_PID_CWD_MISMATCH'
    args=(proc/'cmdline').read_bytes().split(b'\0')
    assert b'flow/run.py' in args or str(root/'flow/run.py').encode() in args,'QUEUE_PID_COMMAND_MISMATCH'
    def stage():return json.loads((root/'build/progress.json').read_text())['stage']
    assert stage()=='waiting_for_running_input16_DC','QUEUE_ALREADY_ADVANCED_PRESERVE'
    stopped=False;changed=False;success=False
    try:
        os.kill(pid,signal.SIGSTOP);stopped=True
        for unused in range(100):
            status=(proc/'status').read_text()
            if any(line.startswith('State:') and ('T (' in line or 't (' in line) for line in status.splitlines()):break
            time.sleep(.02)
        else:raise AssertionError('QUEUE_NOT_STOPPED')
        assert stage()=='waiting_for_running_input16_DC','QUEUE_ADVANCED_BEFORE_PAUSE'
        assert not (root/'build/dc').exists() and not (root/'build/gate').exists(),'SOC_CAD_ALREADY_STARTED'
        assert (root/'manifest.json').read_bytes()==original and tb.read_bytes()==old,'SOURCE_CHANGED_BEFORE_PATCH'
        backup.mkdir(parents=True)
        (backup/'manifest.before.json').write_bytes(original);(backup/'tb.before.sv').write_bytes(old)
        changed=True
        temporary=tb.with_suffix('.saif_patch.tmp');temporary.write_bytes(new);os.replace(str(temporary),str(tb))
        temporary=root/'manifest.saif_patch.tmp';temporary.write_bytes(replacement);os.replace(str(temporary),str(root/'manifest.json'))
        for n,h in manifest['files'].items():assert sha((root/n).read_bytes())==h,'PATCH_CHECK_FAILED '+n
        receipt=dict(queue_pid=pid,old_manifest_sha256=sha(original),new_manifest_sha256=sha(replacement),
            changed_files=['flow/tb_soc_metrics.sv','manifest.json'],numerical_RTL_unchanged=True,
            original_DC_untouched=True,queue_resumed=True,UTC=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
        (backup/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');success=True
    finally:
        if changed and not success:
            tb.write_bytes(old);(root/'manifest.json').write_bytes(original)
        if stopped:os.kill(pid,signal.SIGCONT)
    print('SOC_SAIF_STRING_PATCH_VERIFIED '+json.dumps(receipt,sort_keys=True))
    print('SOC_QUEUE_CONTINUES_WAITING_NO_RESTART')


if __name__=='__main__':
    install(Path('/path/to/project/kwt_soc_input16_metrics_595724b_tt_20261112'))
