"""Python 3.6: start power only on the original, hash-paired gate SAIF/netlist."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

root=Path.cwd().resolve()
assert hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()=='2c9225dfaaf97ad6c9be370463a27d6e902dc57e79ba5ba7897db4ba72178987', 'WRONG_PROJECT_USE_ORIGINAL_2b2dc17'
saif=root/'build/gate/c0_resume_20261112/kwt1_gate_c0.saif'
assert saif.is_file() and saif.stat().st_size>0, 'GATE_SAIF_NOT_READY_PRESERVE_RUNNING_SIMULATION'
gate_log=(saif.parent/'run.log').read_text(errors='replace')
assert 'KWT_OUTPUT mismatches=0 of 1584' in gate_log and 'PASS KWT_GATE_TASK case=0 ' in gate_log, 'GATE_FULL_OUTPUT_PASS_MISSING'
assert not re.search(r'FAIL|BUS_ERR|TIMEOUT|X_ENTER|HW_ERROR',gate_log), 'GATE_ERRORS_PRESERVE_LOG'
subprocess.check_call([sys.executable,str(root/'flow/project.py'),'check-saif',str(saif)])
subprocess.check_call([sys.executable,str(root/'flow/project.py'),'preflight'])
env=dict(os.environ)
lc=shutil.which('lc_shell')
if lc and lc.endswith('/bin/lc_shell'):
    env['SYNOPSYS_LC_ROOT']=str(Path(lc).parent.parent)
assert os.access(os.path.join(env.get('SYNOPSYS_LC_ROOT',''),'bin/lc_shell'),os.X_OK), 'LC_PATH_MISSING_BIND_ACTUAL_LC_ROOT'
pt='/eda/synopsys/prime/prime_2022.03-SP5-1/bin/pt_shell'
assert os.access(pt,os.X_OK), 'PT_EXECUTABLE_MISSING'
run='pt_power_c0_20261112'
assert not (root/'build'/run).exists(), 'PRESERVE_EXISTING_POWER_REPORTS'
# Select TT in a new sidecar; preserve every registered project file.
original=(root/'flow/pt.tcl').read_text()
anchor='[file join [file dirname [info script]] project.tcl]'
assert original.count(anchor)==1 and original.count('foreach corner {ss ff tt}')==1, 'UNEXPECTED_PT_TEMPLATE'
power_tcl=original.replace(anchor,'[file join [pwd] flow project.tcl]').replace('foreach corner {ss ff tt}','foreach corner {tt}')
sidecar=root/'review_tools/pt_power_only_tt.tcl'
sidecar.parent.mkdir(exist_ok=True)
if sidecar.exists():
    assert sidecar.read_text()==power_tcl, 'PRESERVE_CHANGED_POWER_SIDECAR'
else:
    with sidecar.open('x') as f:f.write(power_tcl)

env.update(KWT_GATE_SAIF=str(saif),KWT_PT_RUN=run)
log=root/'build/pt_power_c0_20261112.console.log'
with log.open('x') as stream:
    job=subprocess.Popen([pt,'-f',str(sidecar)],cwd=str(root),env=env,
        stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
receipt=dict(pid=job.pid,source_manifest_sha256=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),
    netlist_sha256=hashlib.sha256((root/'build/dc/mapped.v').read_bytes()).hexdigest(),
    declared_operating_corner='TT',PT_sidecar_sha256=hashlib.sha256(sidecar.read_bytes()).hexdigest(),
    SAIF=str(saif),report=str(root/'build'/run/'power_accelerator_tt.rpt'),
    scope='accelerator only, gate bench window, not full SoC and not the input16 candidate',
    whole_SoC_power_mW=None,whole_SoC_energy_uJ=None)
with (root/'build/pt_power_c0_20261112.launch.json').open('x') as stream:
    json.dump(receipt,stream,indent=2)
print('ACCEL_POWER_STARTED pid=%d log=%s'%(job.pid,log))
print('ACCEL_POWER_SCOPE accelerator_only_not_complete_SoC')
