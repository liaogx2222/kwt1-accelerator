"""Build immutable System Bus candidate and short VNC delta installers."""
import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import textwrap
import zlib
import prepare_sysbus_candidate as candidate
import prepare_input16_soc_metrics as base
ROOT=Path(__file__).resolve().parents[1]


def source_files(all_cases=False):
    f=candidate.build()
    dc=(ROOT/'flow/sysbus_v1/dc.tcl').read_text()
    dc=dc.replace(' SYSBUS_PORT_CONTRACT\n',(ROOT/'flow/sysbus_v1/check_wrapper_ports.tcl').read_text()+'\n')
    old=(ROOT/'flow/soc_metrics/dc.tcl').read_text()
    start=old.index(' redirect -file $OUT/reports/area.rpt')
    end=old.index('\n} failure]',start)
    accounting=old[start:end]
    # Count custom ROM and new System Bus arbiter regardless of CPU hierarchy.
    accounting=accounting.replace('![string match */u_e203_nice_core/* $name]',
       '![string match */u_e203_nice_core/* $name] && ![string match */system_bus_masters/* $name] && ![string match */u_sirv_mrom_top/* $name]')
    assert dc.count(' SYSBUS_ACCOUNTING_AND_EXPORT\n')==1
    f['flow/dc.tcl']=dc.replace(' SYSBUS_ACCOUNTING_AND_EXPORT\n',accounting+'\n').encode()
    s=f['flow/constraints.sdc'].decode()
    old='set_clock_uncertainty -setup 0.300 [all_clocks]\nset_clock_uncertainty -hold 0.150 [all_clocks]'
    new='foreach_in_collection c [all_clocks] {\n set_clock_uncertainty -setup 0.300 $c\n set_clock_uncertainty -hold 0.150 $c\n}\nset_clock_transition 0.150 [all_clocks]'
    assert old in s;f['flow/constraints.sdc']=s.replace(old,new).encode()
    # A per-case report uses exactly the same code, library and constraints.
    s=f['flow/pt.tcl'].decode()
    s=s.replace(' set OUT $PROJECT/build/pt\n',
      ' set case 0\n if {[info exists ::env(SOC_POWER_CASE)]} {set case $::env(SOC_POWER_CASE)}\n'
      ' if {![string is integer -strict $case] || $case < 0 || $case > 11} {error "invalid power case"}\n'
      ' set OUT $PROJECT/build/pt_case_[format %02d $case]\n'
      ' set gate_name cold\n if {$case != 0} {set gate_name case_[format %02d $case]}\n')
    s=s.replace('$PROJECT/build/gate/cold/task.saif','$PROJECT/build/gate/$gate_name/task.saif')
    old='   redirect $OUT/activity_tt.rpt {report_switching_activity;report_switching_activity -list_not_annotated}\n   redirect $OUT/power_checks_tt.rpt {check_power -verbose}\n   update_power\n'
    new='   update_power\n   redirect $OUT/activity_tt.rpt {report_switching_activity;report_switching_activity -list_not_annotated}\n   redirect $OUT/power_checks_tt.rpt {check_power -verbose}\n'
    assert old in s;f['flow/pt.tcl']=s.replace(old,new).encode()
    s=f['flow/project.py'].decode()
    s=s.replace('import json\n','import json\nimport os\n')
    s=s.replace("    print('SOC_FULL_SOURCE_VERIFIED '+m['RTL_revision'])",
      "    for n,h in m.get('cache_files',{}).items():assert sha(ROOT/n)==h,'MAPPED_CACHE_CHANGED '+n\n"
      "    print('SOC_FULL_SOURCE_VERIFIED '+m['RTL_revision'])")
    s=s.replace("run=ROOT/'build/gate/cold'", "case=int(os.environ.get('SOC_POWER_CASE','0'));assert 0<=case<12\n    run=ROOT/'build/gate'/('cold' if case==0 else 'case_%02d'%case)")
    f['flow/project.py']=s.encode()
    parser=(ROOT/'scripts/review_soc_power_report.py').read_text().split('\ndef prepare(root):')[0]
    f['flow/power_parser.py']=parser.encode()
    s=f['flow/collect.py'].decode();start=s.index('def power(');end=s.index('def collect():',start)
    s=s[:start]+'from power_parser import power,totals\n\n\n'+s[end:]
    s=s.replace('import json\n','import json\nimport os\n')
    s=s.replace("    log=(ROOT/'build/gate/cold/run.log')", "    case=int(os.environ.get('SOC_POWER_CASE','0'));assert 0<=case<12\n    gate_name='cold' if case==0 else 'case_%02d'%case\n    log=(ROOT/('build/gate/'+gate_name+'/run.log'))")
    s=s.replace("ROOT/'build/pt/power_soc_tt.rpt'", "ROOT/('build/pt_case_%02d/power_soc_tt.rpt'%case)")
    s=s.replace("ROOT/'build/gate/cold/task.saif'", "ROOT/('build/gate/'+gate_name+'/task.saif')")
    s=s.replace('    dynamic=power(report,','    totals(report)\n    dynamic=power(report,')
    s=s.replace('tasks=1,case=0,cycles=cycles,','tasks=1,case=case,cycles=cycles,')
    s=s.replace("path=ROOT/'build/metrics_reference.json'", "path=ROOT/('build/metrics_case_%02d.json'%case)")
    s=s.replace('coverage_review_required=True,',
      "conservative_non_shared_macro_area_upper_bound_mm2=whole_area-ledger['shared_macros'],\n"
      '        reference_ideal_clock_slew_ns=.150,coverage_review_required=True,')
    f['flow/collect.py']=s.encode()
    f['flow/run.py']=(ROOT/'scripts/run_sysbus_pipeline.py').read_bytes()
    # Heartbeat is observational only; all task checks and timing stay intact.
    tb=f['flow/tb_soc_metrics.sv'].decode();index=tb.rindex('endmodule')
    tb=tb[:index]+''' always @(negedge hfextclk)if(erst_n&&ticks%10000==0)begin
  $display("SYSBUS_PROGRESS recovery=%0d recovered=%0d case=%0d ticks=%0d packets=%0d ack=%0d params=%0d input=%0d output=%0d done=%0d",mode,recovered,case_id,ticks,packets,ack,params,inputs,outputs,done);
  $fflush();
 end
'''+tb[index:]
    f['flow/tb_soc_metrics.sv']=tb.encode()
    # Module declarations in the numeric core are bit-identical to 595724b.
    original_files=base.build()
    assert all(d==original_files[n] for n,d in f.items() if n.startswith('rtl/'))
    if not all_cases:
        for i in range(1,12):
            for kind in ['input','expected']:f.pop('fixtures/%s_%03d.hex'%(kind,i))
    m=json.loads(f['manifest.json']);m['work_in_progress']=False
    m['performance_cases']=list(range(12)) if all_cases else [0]
    m['files']={n:hashlib.sha256(d).hexdigest() for n,d in f.items() if n!='manifest.json'}
    f['manifest.json']=(json.dumps(m,sort_keys=True,indent=2)+'\n').encode()
    for n,d in f.items():
        if n.endswith('.py'):ast.parse(d,feature_version=(3,6))
    return f


INSTALL=r'''import hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
parent=Path('/home/2026contest/server6/s6_43usr/Desktop/project/kwt_soc_input16_metrics_595724b_tt_20261112')
target=parent.parent/'kwt_sysbus_v1_20261113_r1'
assert not target.exists(),'PRESERVE_EXISTING_SYSBUS_CANDIDATE'
manifest=json.loads((parent/'manifest.json').read_text())
assert manifest['RTL_revision']=='595724b88858b142a407f6a5c4761945252d523b','WRONG_PARENT'
# Validate parent using its own current provenance before borrowing any cache.
clean=dict(os.environ)
for name in ['LD_LIBRARY_PATH','LD_PRELOAD','PYTHONHOME','PYTHONPATH']:clean.pop(name,None)
subprocess.check_call(['/usr/bin/python3',str(parent/'flow/project.py'),'check-netlist'],cwd=str(parent),env=clean)
for n,h in payload['borrow'].items():assert sha(parent/n)==h,'PARENT_FILE_CHANGED '+n
cache={'cache/cpu_mapped.ddc':parent/'build/cpu_precompile_v1/cpu_mapped.ddc',
       'cache/accelerator_mapped.ddc':parent/'frozen_accel/mapped.ddc',
       'frozen_accel/input.json':parent/'frozen_accel/input.json'}
cpu=json.loads((parent/'build/cpu_precompile_v1/receipt.json').read_text())
assert sha(cache['cache/cpu_mapped.ddc'])==cpu['DDC_sha256'],'CPU_CACHE_CHANGED'
acc=json.loads(cache['frozen_accel/input.json'].read_text())
assert sha(cache['cache/accelerator_mapped.ddc'])==acc['ddc_sha256'],'ACCEL_CACHE_CHANGED'
target.mkdir()
for n,d in payload['files'].items():
 p=target/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(base64.b64decode(d))
for n in payload['borrow']:
 p=target/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(str(parent/n),str(p))
for n,p in cache.items():
 dest=target/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(str(p),str(dest))
m=json.loads((target/'manifest.json').read_text());m['cache_files']={n:sha(target/n) for n in cache}
m['parent_manifest_sha256']=sha(parent/'manifest.json')
(target/'manifest.json').write_text(json.dumps(m,sort_keys=True,indent=2)+'\n')
env=dict(clean)
env.setdefault('KWT_PDK_ROOT',str(parent.parent/'pdk_extract/SMIC40/S40/smic'))
env.setdefault('KWT_SRAM_DB_DIR',str(parent.parent/'lib_smic40'))
assert Path(env['KWT_PDK_ROOT']).is_dir() and Path(env['KWT_SRAM_DB_DIR']).is_dir(),'LIBRARY_DIR_MISSING'
lc=shutil.which('lc_shell')
if lc and lc.endswith('/bin/lc_shell'):env['SYNOPSYS_LC_ROOT']=str(Path(lc).parent.parent)
if not os.access(str(Path(env.get('SYNOPSYS_LC_ROOT',''))/'bin/lc_shell'),os.X_OK):
 matches=sorted(Path('/eda/synopsys').glob('lc/*/bin/lc_shell'))
 assert len(matches)==1,'LC_ROOT_AMBIGUOUS_OR_MISSING '+str(matches)
 env['SYNOPSYS_LC_ROOT']=str(matches[0].parent.parent)
subprocess.check_call(['/usr/bin/python3',str(target/'flow/project.py'),'check'],cwd=str(target),env=env)
(target/'build').mkdir()
with (target/'build/queue.console.log').open('x') as log:
 p=subprocess.Popen(['/usr/bin/python3','-u','flow/run.py'],cwd=str(target),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
(target/'build/launch.json').write_text(json.dumps({'pid':p.pid,'source_checked':True},indent=2)+'\n')
print('SYSBUS_PIPELINE_STARTED pid='+str(p.pid)+' directory='+str(target))
'''


def export(out,all_cases=False):
    assert not out.exists(),'PRESERVE_RELEASE'
    f=source_files(all_cases);old=base.build();borrow={};files={}
    for n,d in f.items():
        if n in old and d==old[n] and n!='manifest.json':borrow[n]=hashlib.sha256(d).hexdigest()
        else:files[n]=base64.b64encode(d).decode()
    payload=dict(files=files,borrow=borrow)
    data=zlib.compress(json.dumps(payload,sort_keys=True).encode(),9)
    encoded=base64.b64encode(data).decode();out.mkdir(parents=True)
    # Each command is short enough for a VNC terminal canonical input line.
    size=20000;parts=[encoded[i:i+size] for i in range(0,len(encoded),size)]
    for i,part in enumerate(parts):
        code="from pathlib import Path\nPath('sysbus.part%02d').write_text(\n"%i
        code+=''.join(repr(v)+'\n' for v in textwrap.wrap(part,120))+')\nprint("SYSBUS_PART_OK %d")\n'%i
        (out/('PASTE_PART_%02d.py'%i)).write_text(code)
    loader="import base64,zlib,json,hashlib\nfrom pathlib import Path\n"
    loader+="raw=base64.b64decode(''.join(Path('sysbus.part%%02d'%%i).read_text() for i in range(%d)))\n"%len(parts)
    loader+="assert hashlib.sha256(raw).hexdigest()==%r,'TRANSFER_CHANGED'\n"%hashlib.sha256(data).hexdigest()
    loader+="payload=json.loads(zlib.decompress(raw).decode())\n"+INSTALL
    ast.parse(loader,feature_version=(3,6))
    (out/'PASTE_START.py').write_text(loader)
    for n,d in f.items():
        p=out/'project'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(d)
    result=dict(compressed_bytes=len(data),parts=len(parts),borrowed_files=len(borrow),overlaid_files=len(files),
        parent_unchanged=True,arithmetic_unchanged=True,actual_server_run=False,
        cache_reused='accelerator and CPU core+TCM+NICE, new wrappers and original System Bus outside core remapped')
    (out/'release.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--all-cases',action='store_true');a=p.parse_args();export(a.output,a.all_cases)
