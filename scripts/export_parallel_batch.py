"""Export four max-delay-focused partition experiments, never editing source worktrees."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import zlib
from export_clean_project import archive
from retry_parallel_declarations import fix_declarations, FIX_ID

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'deliverables/reset_anchor_20261111/project'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(revision, dirty=False):
    old = json.loads((BASE/'manifest.json').read_text())
    original = {n: (BASE/n).read_bytes() for n in old['files']}
    assert all(sha(original[n]) == row['sha256'] for n, row in old['files'].items())
    batch = {'batch_run.py': (ROOT/'flow/parallel/batch_run.py').read_bytes().replace(b'\r\n', b'\n')}
    projects = {}
    specs = [('baseline8', None, '2b2dc171a1601d955609bc65db1ca4b00ff0c7a1', 12017466),
             ('overlap', 'arch60', 'a691cc7f82c5610975ec74c6d63f41e9106080a9', 2470147),
             ('refine', 'arch60-refine', '01f5ca27be00a224499179917ff9dfada517af98', 2470147),
             ('writeback', 'arch60-writeback', '693ffde4dfd6f6eaaea7ee73d5bd0fb10ddcde78', 2391817)]
    for label, source_name, rtl_revision, reference_cycles in specs:
        files = dict(original)
        compatibility_patch = None
        if source_name:
            source = ROOT.parent/source_name
            for name in list(files):
                if name.startswith(('rtl/v2/', 'rtl/micro/', 'rtl/integration/')):
                    del files[name]
            paths = ['rtl/integration/smic40/kwt_tech_sram_4096x16.sv', 'rtl/micro/mul_pipe.sv', 'rtl/micro/rne_pipe.sv']
            paths += ['rtl/v2/'+n for n in ['kwt_sram_sp.sv','kwt_mac_array.sv','kwt_iterative.sv','kwt_math.sv','kwt_packet_loader.sv','kwt_layer_banked.sv','kwt1_accel.sv','kwt1_mmio.sv','generated/kwt_profile.svh']]
            for name in paths:
                files[name] = subprocess.check_output(['git','show',rtl_revision+':'+name], cwd=source)
            name = 'rtl/v2/kwt_layer_banked.sv'
            before = files[name]
            files[name] = fix_declarations(before)
            compatibility_patch = dict(id=FIX_ID, file=name, before_sha256=sha(before),
                                       after_sha256=sha(files[name]), original_RTL_revision=rtl_revision,
                                       method='relocate two entire declaration lines before first procedural use',
                                       actual_DC_validation_pending=True)
            rtl_list = [name for name in paths if not name.endswith('.svh')]
        else:
            rtl_list = original['flow/rtl_sources.txt'].decode().splitlines()
        files['flow/rtl_sources.txt'] = ('\n'.join(rtl_list)+'\n').encode()
        config = original['flow/project.tcl'].decode()
        config += '\nset KWT_ELAB_PARAMETERS {%s}\n' % ('BLOCK_STREAM=1' if source_name else '')
        files['flow/project.tcl'] = config.encode()
        dc = original['flow/dc.tcl'].decode()
        dc = dc.replace('define_design_lib WORK -path $OUT/WORK', '''define_design_lib WORK -path $OUT/WORK
file mkdir $OUT/alib_cache
set_app_var alib_library_analysis_path $OUT/alib_cache
set KWT_CORES 4
if {[info exists ::env(KWT_JOB_CORES)]} { set KWT_CORES $::env(KWT_JOB_CORES) }
if {![string is integer -strict $KWT_CORES] || $KWT_CORES < 1 || $KWT_CORES > 8} { error "invalid KWT_JOB_CORES" }
set_host_options -max_cores $KWT_CORES
puts "KWT_BATCH_RESOURCE cores=$KWT_CORES hold_optimization=OFF"
redirect -file $OUT/reports/host_options.rpt { report_host_options }''')
        dc = dc.replace('elaborate $TOP -lib WORK', '''if {[llength $KWT_ELAB_PARAMETERS]} {
    elaborate $TOP -lib WORK -parameters $KWT_ELAB_PARAMETERS
} else { elaborate $TOP -lib WORK }
# A parameterized template can be named kwt1_mmio_BLOCK_STREAM1.
# Normalize only the in-memory design name before the common link/export path.
set KWT_ACTUAL_TOP [get_object_name [current_design]]
if {$KWT_ACTUAL_TOP eq ""} { error "elaboration did not select a top" }
puts "KWT_ELABORATED_TOP $KWT_ACTUAL_TOP parameters=$KWT_ELAB_PARAMETERS"
if {$KWT_ACTUAL_TOP ne $TOP} {
    if {![rename_design $KWT_ACTUAL_TOP $TOP]} { error "parameterized top rename failed" }
}''')
        dc = dc.replace('if {![set_fix_hold [get_clocks accel_clk]]} { error "set_fix_hold failed" }\n', '')
        dc = dc.replace('puts "KWT_SYNTH_STAGE HOLD_AFTER_RESET_TREE"\nif {![compile_ultra -incremental -no_autoungroup]} { error "incremental hold/timing compile failed" }\n', '')
        assert 'set_fix_hold' not in dc and 'HOLD_AFTER_RESET_TREE' not in dc
        assert dc.count('if {![compile_ultra ') == 2
        files['flow/dc.tcl'] = dc.encode()
        constraints = original['flow/constraints.sdc']
        files['flow/constraints_base.sdc'] = constraints
        if source_name:
            constraints += b'''
# Production BLOCK_STREAM ports: same I/O budgets, no timing relaxation.
set block_inputs [get_ports {blk_sink_valid blk_sink_data blk_sink_last blk_sink_input blk_output_active blk_source_ready blk_source_ack}]
set block_outputs [get_ports {blk_sink_ready blk_error blk_cancel blk_source_valid blk_source_data blk_source_last}]
set_input_delay -clock $clk_name -max $io_delay $block_inputs
set_input_delay -clock $clk_name -min 0.000 $block_inputs
set_input_transition 0.150 $block_inputs
set_output_delay -clock $clk_name -max $io_delay $block_outputs
set_output_delay -clock $clk_name -min 0.000 $block_outputs
set_load 0.020 $block_outputs
'''
        files['flow/constraints.sdc'] = constraints
        # Do not ship an unvalidated old PIO TB as a BLOCK_STREAM mapped test.
        files['flow/run_gate.sh'] = b'#!/bin/bash\necho "BATCH_SYNTHESIS_ONLY: use a source-specific validated gate adapter"\nexit 2\n'
        manifest = dict(schema=2, git_revision=revision, RTL_revision=rtl_revision,
                        development_dirty=dirty, top='kwt1_mmio', numerical_contract='INTEGER_NUMERICS_V1',
                        private_macros=20, private_sram_bytes=163840, macro_retention_pin='RET1N',
                        scope='accelerator partition only; CPU/NICE/shared SRAM/ROM/TCM not mapped',
                        BLOCK_STREAM=1 if source_name else None, hold_optimization=False,
                        hold_analysis='reported, deferred by user, not signed off',
                        functional_reference_full_SoC_cycles=reference_cycles,
                        functional_reference_not_measured_by_this_batch=True,
                        original_constraints_sha256=sha(original['flow/constraints.sdc']),
                        files={n: dict(bytes=len(data), sha256=sha(data)) for n,data in sorted(files.items())})
        if compatibility_patch:
            manifest['compatibility_patch'] = compatibility_patch
        raw = (json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode()
        for name,data in files.items():
            batch[label+'/'+name] = data
        batch[label+'/manifest.json'] = raw
        projects[label] = dict(manifest_sha256=sha(raw), RTL_revision=rtl_revision,
                               BLOCK_STREAM=manifest['BLOCK_STREAM'], hold_optimization=False,
                               scope=manifest['scope'], reference_cycles=reference_cycles)
    spec = dict(schema=1, producer_revision=revision, development_dirty=dirty, scope='four isolated accelerator partition DC/PT experiments',
                batch_tools={'batch_run.py':sha(batch['batch_run.py'])}, projects=projects,
                requested_jobs=4, cores_per_job=4, hold_optimization=False,
                no_shared_work_or_alib_cache=True, default_clock_period_ns=6.666667,
                complete_SoC_PPA=False, power_mW=None, energy_uJ=None)
    batch['batch_manifest.json'] = (json.dumps(spec,indent=2,sort_keys=True)+'\n').encode()
    batch['INSTALL_RECEIPT.json'] = (json.dumps(dict(batch_manifest_sha256=sha(batch['batch_manifest.json']),
                                                   producer_revision=revision),indent=2)+'\n').encode()
    return batch, original


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--allow-dirty',action='store_true')
    a=ap.parse_args(); out=a.output.resolve()
    if out.exists(): raise ValueError('fresh output required')
    tracked=['flow/parallel','scripts/export_parallel_batch.py','scripts/install_parallel_batch.py',
             'scripts/retry_parallel_declarations.py']
    dirty=bool(subprocess.check_output(['git','status','--porcelain','--',*tracked],cwd=ROOT))
    if dirty and not a.allow_dirty: raise ValueError('commit producer scripts before release')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    batch,original=build(revision,dirty)
    pool={sha(data):data for data in original.values()}
    assets={sha(data):data for data in batch.values() if sha(data) not in pool}
    meta=dict(directory='kwt_parallel_max_20261112_'+revision[:7],base_manifest_sha256=sha((BASE/'manifest.json').read_bytes()),
              assets={h:len(data) for h,data in assets.items()},
              files={n:dict(bytes=len(data),sha256=sha(data)) for n,data in sorted(batch.items())})
    capsule={'parallel_fix/install.py':(ROOT/'scripts/install_parallel_batch.py').read_bytes().replace(b'\r\n',b'\n'),
             'parallel_fix/install.json':(json.dumps(meta,indent=2,sort_keys=True)+'\n').encode()}
    capsule.update({'parallel_fix/assets/'+h:data for h,data in assets.items()})
    payload=archive(capsule);encoded=base64.b64encode(zlib.compress(payload,9)).decode();parts=[encoded[i:i+800] for i in range(0,len(encoded),800)]
    commands=['mkdir vnc_parallel_max_20261112']
    for i,part in enumerate(parts):commands.append('python3 -c "open(\'vnc_parallel_max_20261112/part%04d\',\'w\').write(\'%s\')"'%(i,part))
    h=sha(payload)
    commands.append('python3 -c "import base64,zlib,hashlib;b=zlib.decompress(base64.b64decode(\'\'.join(open(\'vnc_parallel_max_20261112/part%%04d\'%%i).read() for i in range(%d))));assert len(b)==%d and hashlib.sha256(b).hexdigest()==\'%s\';open(\'vnc_parallel_max_20261112/fix.tar.gz\',\'xb\').write(b);print(\'PARALLEL_TRANSFER_VERIFIED\')"'%(len(parts),len(payload),h))
    commands+=['tar xzf vnc_parallel_max_20261112/fix.tar.gz -C vnc_parallel_max_20261112','python3 vnc_parallel_max_20261112/parallel_fix/install.py']
    out.mkdir(parents=True)
    for name,data in batch.items():
        p=out/'batch'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    for name,data in capsule.items():
        p=out/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    (out/'fix.tar.gz').write_bytes(payload);(out/'VNC_INSTALL.csh.txt').write_text('\n'.join(commands)+'\n',encoding='ascii')
    report=dict(source_revision=revision,development_dirty=dirty,directory=meta['directory'],bytes=len(payload),sha256=h,parts=len(parts),commands=len(commands),assets=len(assets),projects=4,hold_optimization=False,full_SoC_PPA=False)
    # The whole script can be pasted into a Python stdin reader, avoiding a
    # Python process per base64 line. Parts stay below typical clipboard limits.
    loader = '''import base64,zlib,hashlib,io,tarfile,subprocess,sys
from pathlib import Path,PurePosixPath
assert hashlib.sha256(Path("manifest.json").read_bytes()).hexdigest()=="%s", "WRONG_BASE_PROJECT"
encoded="""
%s
"""
data=zlib.decompress(base64.b64decode(encoded))
assert len(data)==%d and hashlib.sha256(data).hexdigest()=="%s", "TRANSFER_HASH_MISMATCH"
stage=Path("vnc_parallel_stdin_%s")
stage.mkdir()
with tarfile.open(fileobj=io.BytesIO(data),mode="r:gz") as stream:
    for member in stream.getmembers():
        path=PurePosixPath(member.name)
        assert member.isfile() and not path.is_absolute() and ".." not in path.parts
    stream.extractall(str(stage))
print("PARALLEL_TRANSFER_VERIFIED")
subprocess.check_call([sys.executable,str(stage/"parallel_fix/install.py")])
target=Path("..").resolve()/"%s"
subprocess.check_call([sys.executable,str(target/"batch_run.py"),"check"])
print("PARALLEL_READY "+str(target))
''' % (meta['base_manifest_sha256'],'\n'.join(parts),len(payload),h,revision[:7],meta['directory'])
    (out/'STDIN_INSTALL.py').write_text(loader,encoding='ascii')
    sections=[];current=''
    for line in loader.splitlines(True):
        if len(current)+len(line)>28000:
            sections.append(current);current=''
        current+=line
    if current:sections.append(current)
    for i,section in enumerate(sections):
        (out/('STDIN_PART_%02d.txt'%(i+1))).write_text(section,encoding='ascii')
    report['stdin_clipboard_parts']=len(sections)
    (out/'transfer_manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
