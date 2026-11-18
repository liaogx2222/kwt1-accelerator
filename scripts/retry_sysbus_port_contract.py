"""Python 3.6: check scalar and vector DC ports after failed r2 gate."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def once(text,old,new):
    assert text.count(old)==1,'NAMESPACE_TEMPLATE_CHANGED '+old
    return text.replace(old,new)


CONTRACT='# Synopsys collections can represent a bus as one aggregate or as bit ports.\n# The HDL\'s fixed bus declarations are source-hash checked before this gate.\nproc sysbus_require_port {port width} {\n set pins [get_ports -quiet ${port}*]\n set count [sizeof_collection $pins]\n set names [get_object_name $pins]\n if {$count == 1 && [lindex $names 0] eq $port} {\n  puts "SYSBUS_PORT_VERIFIED $port width=$width representation=aggregate"\n  return\n }\n if {$count != $width} {error "System Bus port width mismatch $port expected=$width count=$count names=$names"}\n if {$width == 1} {error "System Bus scalar name mismatch $port names=$names"}\n for {set bit 0} {$bit < $width} {incr bit} {\n  set expected [format {%s[%d]} $port $bit]\n  if {[lsearch -exact $names $expected] < 0} {error "System Bus bus bit missing $expected names=$names"}\n }\n puts "SYSBUS_PORT_VERIFIED $port width=$width representation=bits"\n}\n'


def patched_sources(root):
    text=(root/"flow/dc.tcl").read_text()
    text=once(text,'  foreach port {load_cmd_valid load_cmd_ready load_cmd_addr load_cmd_wdata load_rsp_valid load_rsp_ready load_rsp_rdata load_rsp_error} {\n   if {[sizeof_collection [get_ports -quiet $port]] != 1} {error "new System Bus wrapper port missing $wrapper/$port"}\n  }\n','  foreach {port width} {load_cmd_valid 1 load_cmd_ready 1 load_cmd_addr 32 load_cmd_wdata 32 load_rsp_valid 1 load_rsp_ready 1 load_rsp_rdata 32 load_rsp_error 1} {\n   sysbus_require_port $port $width\n  }\n')
    text=once(text,' foreach wrapper {sysbus_e203_subsys_main sysbus_e203_subsys_top} {',CONTRACT+"\n"+' foreach wrapper {sysbus_e203_subsys_main sysbus_e203_subsys_top} {')
    return {"flow/dc.tcl":text.encode()}


def install(root):
    root=root.resolve();target=root.parent/'kwt_sysbus_v1_20261113_r3'
    assert root.name=='kwt_sysbus_v1_20261113_r2','RUN_IN_FAILED_R2'
    assert not target.exists(),'PRESERVE_EXISTING_R3'
    status=json.loads((root/'build/progress.json').read_text())
    assert status['stage']=='failed_preserve_evidence','R1_NOT_FAILED'
    assert not (root/'build/dc/receipt.json').exists() and not (root/'build/gate').exists(),'PRESERVE_LATER_EVIDENCE'
    text=(root/'build/dc.console.log').read_text(errors='replace')
    assert re.search(r'^SOC_FATAL new System Bus wrapper port missing sysbus_e203_subsys_main/load_cmd_addr\s*$',text,re.M),'UNEXPECTED_R1_FAILURE'
    assert 'load_cmd_addr' in text,'WRONG_PORT_CONTRACT_FAILURE'
    pid=json.loads((root/'build/launch.json').read_text())['pid'];proc=Path('/proc')/str(pid)
    if proc.exists():
        try:assert not ((proc/'cwd').resolve()==root and b'flow/run.py' in (proc/'cmdline').read_bytes()),'R1_STILL_RUNNING'
        except OSError:pass
    m=json.loads((root/'manifest.json').read_text())
    assert m['integration_revision']=='SYSBUS_V1_NAMESPACE_R2','WRONG_INTEGRATION'
    for name,digest in list(m['files'].items())+list(m['cache_files'].items()):
        p=Path(name);assert not p.is_absolute() and '..' not in p.parts,'UNSAFE_SOURCE_PATH'
        assert sha(root/name)==digest,'R1_INPUT_CHANGED '+name
    updates=patched_sources(root)
    target.mkdir()
    for name in list(m['files'])+list(m['cache_files']):
        destination=target/name;destination.parent.mkdir(parents=True,exist_ok=True)
        if name in updates:destination.write_bytes(updates[name])
        else:shutil.copyfile(str(root/name),str(destination))
    for name in updates:m['files'][name]=sha(target/name)
    m['integration_revision']='SYSBUS_V1_PORT_CONTRACT_R3'
    m['namespace_retry_parent_manifest_sha256']=sha(root/'manifest.json')
    m['namespace_retry_scope']='DC bus/scalar collection checks only; all HDL and hardware unchanged'
    (target/'manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
    env=dict(os.environ)
    for name in ['LD_LIBRARY_PATH','LD_PRELOAD','PYTHONHOME','PYTHONPATH','SOC_PT_PREFLIGHT','SOC_POWER_CASE']:env.pop(name,None)
    env.setdefault('KWT_PDK_ROOT',str(root.parent/'pdk_extract/SMIC40/S40/smic'))
    env.setdefault('KWT_SRAM_DB_DIR',str(root.parent/'lib_smic40'))
    for name in ['KWT_PDK_ROOT','KWT_SRAM_DB_DIR']:assert Path(env[name]).is_dir(),'MISSING_LIBRARY_DIR '+name
    lc=shutil.which('lc_shell')
    if lc and lc.endswith('/bin/lc_shell'):env['SYNOPSYS_LC_ROOT']=str(Path(lc).parent.parent)
    if not os.access(str(Path(env.get('SYNOPSYS_LC_ROOT',''))/'bin/lc_shell'),os.X_OK):
        found=sorted(Path('/eda/synopsys').glob('lc/*/bin/lc_shell'))
        assert len(found)==1,'LC_ROOT_AMBIGUOUS_OR_MISSING'
        env['SYNOPSYS_LC_ROOT']=str(found[0].parent.parent)
    subprocess.check_call(['/usr/bin/python3',str(target/'flow/project.py'),'check'],cwd=str(target),env=env)
    (target/'build').mkdir()
    with (target/'build/queue.console.log').open('x') as output:
        p=subprocess.Popen(['/usr/bin/python3','-u','flow/run.py'],cwd=str(target),env=env,
            stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    (target/'build/launch.json').write_text(json.dumps(dict(pid=p.pid,namespace_retry=True),indent=2)+'\n')
    print('SYSBUS_R3_STARTED pid='+str(p.pid)+' directory='+str(target))


if __name__=='__main__':install(Path.cwd())
