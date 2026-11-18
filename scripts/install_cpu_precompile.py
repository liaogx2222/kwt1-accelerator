"""Python 3.6 CPU mapping in parallel; guard optional cache reuse in waiting queue."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT=Path('/path/to/project/kwt_soc_input16_metrics_595724b_tt_20261112')
DC='/eda/synopsys/dc/dc_2022.03-SP5-5/bin/dc_shell'


def sha(data):return hashlib.sha256(data).hexdigest()


def cache_hook(data):
    before=b' if {![analyze -format sverilog -define {FPGA_SOURCE SYNTHESIS DISABLE_SV_ASSERTION} -lib WORK $files]} {error "SoC analysis failed"}'
    assert data.count(before)==1,'CPU_REUSE_ANCHOR_CHANGED'
    code=b''' # Reuse the independent CPU mapping only when its final receipt is ready.
 # Otherwise retain the original whole-platform flow, with no extra wait.
 set use_cpu_cache 0
 if {[file isfile $PROJECT/build/cpu_precompile_v1/receipt.json]} {
  puts [host_python $PROJECT/review_tools/cpu_precompile_v1/cpu_precompile.py ready]
  read_ddc $PROJECT/build/cpu_precompile_v1/cpu_mapped.ddc
  set_app_var target_library $maximum
  set_app_var link_library [concat * $maximum]
  if {[sizeof_collection [get_designs -quiet e203_subsys_top]] != 1} {error "CPU cache top missing"}
  set_dont_touch [get_designs e203_subsys_top] true
  set kept {}
  foreach f $files {
   if {[string match $PROJECT/cpu/* $f]} {continue}
   if {[lsearch -exact {kwt_nice_block.sv sirv_mrom_top.v} [file tail $f]] >= 0} {continue}
   lappend kept $f
  }
  set files $kept
  set use_cpu_cache 1
  puts SOC_CPU_PRECOMPILE_REUSED
 } else {puts SOC_CPU_PRECOMPILE_NOT_READY_ORIGINAL_FLOW}
'''
    data=data.replace(before,code+before)
    anchor=b' set frozen [get_cells u_kwt1_mmio]'
    assert data.count(anchor)==1
    return data.replace(anchor,b''' if {$use_cpu_cache} {
  set cpu [get_cells u_e203_subsys_top]
  if {[sizeof_collection $cpu] != 1} {error "cached CPU instance missing"}
  set_dont_touch $cpu true
  set_boundary_optimization $cpu false
 }
'''+anchor)


def hook_waiting_queue(root,work,expected):
    progress=root/'build/progress.json'
    def stage():return json.loads(progress.read_text())['stage']
    if stage()!='waiting_for_running_input16_DC':
        print('CPU_CACHE_HOOK_SKIPPED_MAIN_ALREADY_ADVANCED');return False
    pid=int((root/'build/launch.lock').read_text());proc=Path('/proc')/str(pid)
    assert (proc/'cwd').resolve()==root.resolve(),'MAIN_QUEUE_PID_CWD_MISMATCH'
    args=(proc/'cmdline').read_bytes().split(b'\0')
    assert b'flow/run.py' in args or str(root/'flow/run.py').encode() in args,'MAIN_QUEUE_PID_COMMAND_MISMATCH'
    original=(root/'manifest.json').read_bytes();m=json.loads(original)
    dc=root/'flow/dc.tcl';old=dc.read_bytes()
    assert sha(old)==expected,'UNEXPECTED_MAIN_DC_TEMPLATE'
    updated=cache_hook(old);m['files']['flow/dc.tcl']=sha(updated)
    m['CPU_precompile_reuse']=dict(policy='only final verified ready receipt; otherwise original flow without waiting',CPU_RTL_unchanged=True,original_DC_sha256=sha(old))
    new_manifest=(json.dumps(m,indent=2,sort_keys=True)+'\n').encode()
    stopped=False;changed=False;success=False
    try:
        os.kill(pid,signal.SIGSTOP);stopped=True
        for unused in range(100):
            status=(proc/'status').read_text()
            if any(line.startswith('State:') and 'T (' in line for line in status.splitlines()):break
            time.sleep(.02)
        else:raise AssertionError('MAIN_QUEUE_NOT_STOPPED')
        if stage()!='waiting_for_running_input16_DC' or (root/'build/dc').exists():
            print('CPU_CACHE_HOOK_SKIPPED_STAGE_CHANGED');return False
        assert dc.read_bytes()==old and (root/'manifest.json').read_bytes()==original,'MAIN_SOURCE_RACE'
        (work/'main_dc.before.tcl').write_bytes(old);(work/'main_manifest.before.json').write_bytes(original)
        changed=True
        tmp=dc.with_suffix('.cpu_cache.tmp');tmp.write_bytes(updated);os.replace(str(tmp),str(dc))
        tmp=root/'manifest.cpu_cache.tmp';tmp.write_bytes(new_manifest);os.replace(str(tmp),str(root/'manifest.json'))
        for n,h in m['files'].items():assert sha((root/n).read_bytes())==h,'UPDATED_SOURCE_CHECK_FAILED '+n
        success=True
        (work/'main_hook_receipt.json').write_text(json.dumps(dict(queue_pid=pid,old_manifest_sha256=sha(original),new_manifest_sha256=sha(new_manifest),numeric_RTL_changed=False),indent=2)+'\n')
    finally:
        if changed and not success:dc.write_bytes(old);(root/'manifest.json').write_bytes(original)
        if stopped:os.kill(pid,signal.SIGCONT)
    print('CPU_CACHE_HOOK_INSTALLED_MAIN_QUEUE_RESUMED');return True


def install(root,capsule):
    root=root.resolve()
    for key in ['KWT_PDK_ROOT','KWT_SRAM_DB_DIR']:
        assert os.environ.get(key) and Path(os.environ[key]).is_dir(),'SET_ENV_FIRST '+key
    assert os.access(DC,os.X_OK),'DC_NOT_EXECUTABLE'
    meta=json.loads((capsule/'spec.json').read_text())
    for name,h in meta['assets'].items():assert sha((capsule/name).read_bytes())==h,'CPU_INSTALL_ASSET_CHANGED'
    m=json.loads((root/'manifest.json').read_text())
    assert m['RTL_revision']=='595724b88858b142a407f6a5c4761945252d523b','WRONG_INPUT16_PROJECT'
    for n,h in m['files'].items():assert sha((root/n).read_bytes())==h,'SOC_SOURCE_CHANGED '+n
    work=root/'review_tools/cpu_precompile_v1'
    assert not work.exists() and not (root/'build/cpu_precompile_v1').exists(),'CPU_PRECOMPILE_ALREADY_EXISTS'
    sources={n:h for n,h in m['files'].items() if n.startswith('cpu/') or n in ['soc/kwt_nice_block.sv','soc/kwt_cpu_nice_arbiter.sv','soc/sirv_mrom_top.v','flow/includes.txt']}
    assert sources==meta['expected_CPU_sources'],'CPU_SOURCES_DIFFER_FROM_FROZEN_INPUT16'
    assert len([n for n in sources if n.startswith('cpu/')])>100,'CPU_SOURCE_INVENTORY_TOO_SMALL'
    pdk=Path(os.environ['KWT_PDK_ROOT']);ram=Path(os.environ['KWT_SRAM_DB_DIR'])
    libraries=[pdk/('SCC40NLL_VHSC40_'+vt+'_V0.1')/('SCC40NLL_VHSC40_'+vt+'_V0p1')/'liberty/1.1v'/('scc40nll_vhsc40_'+vt.lower()+'_tt_v1p1_25c_basic.db') for vt in ['HVT','LVT','RVT']]
    libraries.append(ram/'RAMSP4096X16_tt_1p10v_1p10v_25c.db')
    library_hashes={str(p.resolve()):sha(p.read_bytes()) for p in libraries}
    work.mkdir(parents=True)
    for name in ['cpu_precompile.py','cpu_precompile.tcl']:(work/name).write_bytes((capsule/name).read_bytes())
    (work/'cpu_sources.txt').write_text('\n'.join(n for n in sources if n!='flow/includes.txt')+'\n')
    contract=dict(RTL_revision=m['RTL_revision'],sources=sources,TT_libraries=library_hashes,
        Tcl_sha256=sha((work/'cpu_precompile.tcl').read_bytes()),source_SoC_manifest_sha256=sha((root/'manifest.json').read_bytes()),
        macros=16,boundary_optimization=False,scope='CPU+NICE+TCM mapped block; complete SoC metrics require integrated reports')
    (work/'source_contract.json').write_text(json.dumps(contract,indent=2)+'\n')
    hook=hook_waiting_queue(root,work,meta['original_main_DC_sha256'])
    log=root/'build/cpu_precompile_v1.console.log'
    with log.open('x') as output:
        process=subprocess.Popen([DC,'-f',str(work/'cpu_precompile.tcl'),'-output_log_file','build/cpu_precompile_v1.dc.log'],cwd=str(root),
            env=dict(os.environ),stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    (work/'launch.json').write_text(json.dumps(dict(pid=process.pid,main_cache_hook=hook,source_contract_sha256=sha((work/'source_contract.json').read_bytes()),
        UTC=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())),indent=2)+'\n')
    print('CPU_PRECOMPILE_STARTED pid='+str(process.pid)+' main_cache_hook='+str(hook))


if __name__=='__main__':install(ROOT,Path(__file__).resolve().parent)
