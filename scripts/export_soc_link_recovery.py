"""Package clock-clean checkpoint recovery without repeating block synthesis."""
import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import zlib
ROOT=Path(__file__).resolve().parents[1]


def build():
    sdc=(ROOT/'flow/soc_metrics/constraints.sdc').read_text()
    sdc=sdc.replace('set_clock_uncertainty -setup 0.300 [all_clocks]\nset_clock_uncertainty -hold 0.150 [all_clocks]',
        'foreach_in_collection soc_clock [all_clocks] {\n set_clock_uncertainty -setup 0.300 $soc_clock\n set_clock_uncertainty -hold 0.150 $soc_clock\n}')
    assert 'foreach_in_collection soc_clock' in sdc
    clock_apply=''' set inherited [all_clocks]
 puts "SOC_INHERITED_CLOCK_COUNT [sizeof_collection $inherited]"
 # An empty collection is not passed as a positional clock_list argument.
 if {[sizeof_collection $inherited] > 0} {remove_clock -all}
 redirect -file $OUT/constraints_apply.rpt {source $PROJECT/review_tools/soc_recovery_v1/constraints_clean.sdc}
 if {[sizeof_collection [all_clocks]] != 3} {error "expected exactly three declared clocks"}
 foreach {clock period} {hfclk 6.666667 lfclk 30517.578125 jtagclk 100.000} {
  set c [get_clocks -quiet $clock]
  if {[sizeof_collection $c] != 1} {error "ambiguous clock $clock"}
  set actual [get_attribute $c period]
  if {[expr {abs($actual-$period)}] > [expr {max(0.0001,abs($period)*0.000001)}]} {error "clock period changed $clock"}
  puts "SOC_CLOCK_DECLARED $clock period=$actual"
 }
'''
    def prefix(out,checkpoint):
        return '''if {[catch {
 source [file join [pwd] flow common.tcl]
 puts [host_python $PROJECT/flow/project.py check]
 set OUT $PROJECT/build/'''+out+'''
 if {[file exists $OUT]} {error "preserve recovery output"}
 file mkdir $OUT/reports
 define_design_lib WORK -path $OUT/WORK
 file mkdir $OUT/alib
 set_app_var alib_library_analysis_path $OUT/alib
 set_host_options -max_cores 4
 set maximum [libs tt]
 set_app_var target_library $maximum
 set_app_var link_library [concat * $maximum]
 read_ddc $PROJECT/build/'''+checkpoint+'''
 if {[sizeof_collection [get_designs -quiet $TOP]] != 1} {error "recovery top missing after read_ddc"}
 set_app_var target_library $maximum
 set_app_var link_library [concat * $maximum]
 current_design $TOP
 if {![link]} {error "recovery checkpoint link failed"}
 check_macros
 foreach {instance reference} {u_kwt1_mmio kwt1_mmio_frozen_ref u_e203_subsys_top e203_subsys_top_frozen_ref} {
  set cell [get_cells $instance]
  if {[sizeof_collection $cell] != 1} {error "recovery instance missing $instance"}
  if {[get_attribute $cell ref_name] ne $reference} {error "unexpected frozen block $instance"}
  set_dont_touch $cell true
  set_boundary_optimization $cell false
 }
'''+clock_apply
    end='''} failure]} {puts stderr "SOC_FATAL $failure";puts stderr $::errorInfo;exit 1}
exit
'''
    pre=prefix('link_clock_clean_v1','link_probe_v2/linked_soc.ddc')+''' if {![write -format ddc -hierarchy -output $OUT/clock_clean_soc.ddc]} {error "clock-clean checkpoint failed"}
 puts SOC_CLOCK_PREFLIGHT_DONE
'''+end
    base=(ROOT/'flow/soc_metrics/dc.tcl').read_text()
    start=base.index(' redirect -file $OUT/reports/check_design_before.rpt')
    tail=base[start:]
    mapping=prefix('dc','link_clock_clean_v1/clock_clean_soc.ddc')+tail
    assert mapping.count('compile_ultra')==1 and 'analyze -format' not in mapping and 'elaborate $TOP' not in mapping
    return {'recover.py':(ROOT/'scripts/recover_soc_from_link.py').read_text().encode(),
        'clock_preflight.tcl':pre.encode(),'map.tcl':mapping.encode(),'constraints_clean.sdc':sdc.encode()}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    assets=build()
    for name,data in assets.items():
        if name.endswith('.py'):ast.parse(data,feature_version=(3,6))
        (out/name).write_bytes(data)
    spec=dict(assets={n:hashlib.sha256(d).hexdigest() for n,d in assets.items()})
    assets['spec.json']=(json.dumps(spec,indent=2)+'\n').encode();(out/'spec.json').write_bytes(assets['spec.json'])
    raw=json.dumps({n:d.decode() for n,d in assets.items()},sort_keys=True).encode();enc=base64.b64encode(zlib.compress(raw,9)).decode()
    loader='''import base64,zlib,hashlib,json,subprocess,sys
from pathlib import Path
b=zlib.decompress(base64.b64decode("""
%s
"""))
assert hashlib.sha256(b).hexdigest()=="%s","RECOVERY_TRANSFER_CHANGED"
root=Path("/home/2026contest/server6/s6_43usr/Desktop/project/kwt_soc_input16_metrics_595724b_tt_20261112")
work=root/"review_tools/soc_recovery_loader_v1"
assert not work.exists(),"PRESERVE_EXISTING_RECOVERY_LOADER"
work.mkdir(parents=True)
for name,source in json.loads(b.decode()).items():
    assert name in ["recover.py","clock_preflight.tcl","map.tcl","constraints_clean.sdc","spec.json"]
    with (work/name).open("xb") as f:f.write(source.encode())
subprocess.check_call([sys.executable,str(work/"recover.py")])
'''%('\n'.join(enc[i:i+800] for i in range(0,len(enc),800)),hashlib.sha256(raw).hexdigest())
    ast.parse(loader,feature_version=(3,6));assert max(map(len,loader.splitlines()))<=800
    (out/'PASTE_INSTALL.py').write_text(loader,encoding='ascii')
    (out/'release.json').write_text(json.dumps(dict(payload_sha256=hashlib.sha256(raw).hexdigest(),max_clipboard_line_bytes=800,source_blocks_recompiled=False,
        actual_server_recovery_started=False,actual_new_PPA=False),indent=2)+'\n')
    print('SOC_RECOVERY_PACKAGE_READY',len(loader))


if __name__=='__main__':main()
