"""Python 3.6: isolate changed HDL wrapper names after failed r1 linking."""
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


def patched_sources(root):
    patched={}
    for name,old in [('e203_subsys_main.v','e203_subsys_main'),('e203_subsys_top.v','e203_subsys_top')]:
        path='cpu/e203/subsys/'+name;text=(root/path).read_text()
        text=once(text,'module '+old+'(','module sysbus_'+old+'(')
        if name=='e203_subsys_top.v':
            text=once(text,'  e203_subsys_main  u_e203_subsys_main(',
                           '  sysbus_e203_subsys_main  u_e203_subsys_main(')
        patched[path]=text.encode()
    for path in ['soc/local_kwt_soc_joint.sv','soc/kwt_soc_joint.sv']:
        text=(root/path).read_text()
        patched[path]=once(text,' e203_subsys_top u_e203_subsys_top(',
                               ' sysbus_e203_subsys_top u_e203_subsys_top(').encode()
    path='flow/dc.tcl';text=(root/path).read_text()
    guard=''' # Namespace retry: new HDL wrappers cannot alias cached originals.
 foreach wrapper {sysbus_e203_subsys_main sysbus_e203_subsys_top} {
  elaborate $wrapper -lib WORK
  current_design $wrapper
  foreach port {load_cmd_valid load_cmd_ready load_cmd_addr load_cmd_wdata load_rsp_valid load_rsp_ready load_rsp_rdata load_rsp_error} {
   if {[sizeof_collection [get_ports -quiet $port]] != 1} {error "new System Bus wrapper port missing $wrapper/$port"}
  }
  puts "SYSBUS_NEW_WRAPPER_VERIFIED $wrapper"
 }
'''
    text=once(text,' elaborate $TOP -lib WORK\n',guard+' elaborate $TOP -lib WORK\n')
    check=''' set new_top [get_cells u_e203_subsys_top]
 if {[get_attribute $new_top ref_name] ne "sysbus_e203_subsys_top"} {error "stale cached subsystem top bound"}
 set new_main [get_cells u_e203_subsys_top/u_e203_subsys_main]
 if {[get_attribute $new_main ref_name] ne "sysbus_e203_subsys_main"} {error "stale cached subsystem main bound"}
'''
    text=once(text,' set core [get_cells u_e203_subsys_top/u_e203_subsys_main/u_e203_cpu_top]\n',
                   check+' set core [get_cells u_e203_subsys_top/u_e203_subsys_main/u_e203_cpu_top]\n')
    patched[path]=text.encode()
    for path in ['flow/soc_sources.txt','flow/local_sources.txt']:
        lines=(root/path).read_text().splitlines()
        assert sum(Path(n).name=='e203_soc_top.v' for n in lines)==1,'UNEXPECTED_UNUSED_CHIP_TOP'
        patched[path]=''.join(n+'\n' for n in lines if Path(n).name!='e203_soc_top.v').encode()
    return patched


def install(root):
    root=root.resolve();target=root.parent/'kwt_sysbus_v1_20261113_r2'
    assert root.name=='kwt_sysbus_v1_20261113_r1','RUN_IN_FAILED_R1'
    assert not target.exists(),'PRESERVE_EXISTING_R2'
    status=json.loads((root/'build/progress.json').read_text())
    assert status['stage']=='failed_preserve_evidence','R1_NOT_FAILED'
    assert not (root/'build/dc/receipt.json').exists() and not (root/'build/gate').exists(),'PRESERVE_LATER_EVIDENCE'
    text=(root/'build/dc.console.log').read_text(errors='replace')
    assert re.search(r'^SOC_FATAL new core instance missing\s*$',text,re.M),'UNEXPECTED_R1_FAILURE'
    assert 'load_cmd_valid' in text and 'cpu_cache_e203_subsys_top' in text,'WRONG_NAMESPACE_FAILURE'
    pid=json.loads((root/'build/launch.json').read_text())['pid'];proc=Path('/proc')/str(pid)
    if proc.exists():
        try:assert not ((proc/'cwd').resolve()==root and b'flow/run.py' in (proc/'cmdline').read_bytes()),'R1_STILL_RUNNING'
        except OSError:pass
    m=json.loads((root/'manifest.json').read_text())
    assert m['integration_revision']=='SYSBUS_V1','WRONG_INTEGRATION'
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
    m['integration_revision']='SYSBUS_V1_NAMESPACE_R2'
    m['namespace_retry_parent_manifest_sha256']=sha(root/'manifest.json')
    m['namespace_retry_scope']='HDL wrapper names and elaboration guards only; ports, instance names and logic unchanged'
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
    print('SYSBUS_R2_STARTED pid='+str(p.pid)+' directory='+str(target))


if __name__=='__main__':install(Path.cwd())
