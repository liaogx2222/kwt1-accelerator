"""Python 3.6; read-only source probe, explicit late DDC reference binding."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def sha(data):return hashlib.sha256(data).hexdigest()


def transformed(data):
    text=data.decode()
    common='[file join [file dirname [info script]] common.tcl]'
    assert text.count(common)==1
    text=text.replace(common,'[file join [pwd] flow common.tcl]').replace('set OUT $PROJECT/build/dc\n','set OUT $PROJECT/build/link_probe_v2\n')
    # This arbiter is instantiated by the SoC top, outside the cached CPU.
    text=text.replace('{kwt_nice_block.sv kwt_cpu_nice_arbiter.sv sirv_mrom_top.v}',
                      '{kwt_nice_block.sv sirv_mrom_top.v}')
    first=text.index(' # Reuse the already accepted accelerator DDC,')
    end=text.index(' set fd [open $PROJECT/flow/includes.txt r]',first)
    text=text[:first]+text[end:]
    for line in [
        '  read_ddc $PROJECT/build/cpu_precompile_v1/cpu_mapped.ddc\n',
        '  if {[sizeof_collection [get_designs -quiet e203_subsys_top]] != 1} {error "CPU cache top missing"}\n',
        '  set_dont_touch [get_designs e203_subsys_top] true\n']:
        assert text.count(line)==1,'CPU_CACHE_TEMPLATE_CHANGED';text=text.replace(line,'')
    anchor=' current_design $TOP\n if {![link]} {error "SoC link failed"}'
    late=''' # Load and uniquely name mapped blocks after top-level elaboration.
 read_ddc $PROJECT/frozen_accel/mapped.ddc
 puts "SOC_PROBE_ACCEL_DESIGNS [get_object_name [get_designs -quiet *kwt1*]]"
 if {[sizeof_collection [get_designs -quiet kwt1_mmio]] != 1} {error "late accelerator DDC top missing"}
 rename_design kwt1_mmio kwt1_mmio_frozen_ref
 set_dont_touch [get_designs kwt1_mmio_frozen_ref] true
 if {$use_cpu_cache} {
  read_ddc $PROJECT/build/cpu_precompile_v1/cpu_mapped.ddc
  if {[sizeof_collection [get_designs -quiet e203_subsys_top]] != 1} {error "late CPU DDC top missing"}
  rename_design e203_subsys_top e203_subsys_top_frozen_ref
  set_dont_touch [get_designs e203_subsys_top_frozen_ref] true
 }
 set_app_var target_library $maximum
 set_app_var link_library [concat * $maximum]
 current_design $TOP
 change_link [get_cells u_kwt1_mmio] kwt1_mmio_frozen_ref
 if {[get_attribute [get_cells u_kwt1_mmio] ref_name] ne "kwt1_mmio_frozen_ref"} {error "explicit accelerator binding failed"}
 if {$use_cpu_cache} {
  change_link [get_cells u_e203_subsys_top] e203_subsys_top_frozen_ref
  if {[get_attribute [get_cells u_e203_subsys_top] ref_name] ne "e203_subsys_top_frozen_ref"} {error "explicit CPU binding failed"}
 }
 if {![link]} {error "SoC late link failed"}'''
    assert text.count(anchor)==1;text=text.replace(anchor,late)
    end=text.index(' read_soc_constraints\n')+len(' read_soc_constraints\n')
    text=text[:end]+''' puts "SOC_PROBE_ACCEL_BOUND [get_attribute [get_cells u_kwt1_mmio] ref_name]"
 puts "SOC_PROBE_CPU_CACHE $use_cpu_cache"
 if {![write -format ddc -hierarchy -output $OUT/linked_soc.ddc]} {error "linked checkpoint export failed"}
 puts SOC_LINK_PROBE_PASS
} failure]} {puts stderr "SOC_FATAL $failure";puts stderr $::errorInfo;exit 1}
exit
'''
    assert 'compile_ultra' not in text and 'SOC_LINK_PROBE_PASS' in text
    return text.encode()


def install(root,capsule):
    root=root.resolve()
    for key in ['KWT_PDK_ROOT','KWT_SRAM_DB_DIR']:assert os.environ.get(key) and Path(os.environ[key]).is_dir(),'SET_ENV_FIRST '+key
    spec=json.loads((capsule/'spec.json').read_text())
    old=(root/'flow/dc.tcl').read_bytes();assert sha(old)==spec['expected_main_DC_sha256'],'UNEXPECTED_MAIN_DC_SOURCE'
    manifest=(root/'manifest.json').read_bytes();m=json.loads(manifest)
    for n,h in m['files'].items():assert sha((root/n).read_bytes())==h,'SOC_SOURCE_CHANGED '+n
    assert m['RTL_revision']=='595724b88858b142a407f6a5c4761945252d523b','WRONG_INPUT16'
    frozen=json.loads((root/'frozen_accel/input.json').read_text())
    assert sha((root/'frozen_accel/mapped.ddc').read_bytes())==frozen['ddc_sha256'],'FROZEN_DDC_CHANGED'
    work=root/'review_tools/link_probe_v2';assert not work.exists() and not (root/'build/link_probe_v2').exists(),'PRESERVE_LINK_PROBE'
    probe=transformed(old);work.mkdir(parents=True);(work/'link.tcl').write_bytes(probe)
    (work/'inputs.json').write_text(json.dumps(dict(manifest_sha256=sha(manifest),main_DC_sha256=sha(old),probe_sha256=sha(probe),frozen_DDC_sha256=frozen['ddc_sha256'],no_synthesis=True),indent=2)+'\n')
    log=root/'build/link_probe_v2.console.log'
    with log.open('x') as output:
        p=subprocess.Popen(['/eda/synopsys/dc/dc_2022.03-SP5-5/bin/dc_shell','-f',str(work/'link.tcl'),'-output_log_file','build/link_probe_v2.dc.log'],
            cwd=str(root),env=dict(os.environ),stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    print('SOC_LINK_PROBE_STARTED pid='+str(p.pid))


if __name__=='__main__':install(Path('/path/to/project/kwt_soc_input16_metrics_595724b_tt_20261112'),Path(__file__).resolve().parent)
