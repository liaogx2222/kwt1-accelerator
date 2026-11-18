"""Mock fail-stop control only for the new full-SoC DC/PT entry points."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import shutil
import tkinter
ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',required=True,type=Path);ap.add_argument('--output',required=True,type=Path)
    a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    project=out/'project';shutil.copytree(a.project,project)
    pdk=out/'fake_pdk';ram=out/'fake_ram';ram.mkdir()
    for standard,macro in [('ss_v0p99_125c','ss_0p99v_0p99v_125c'),('ff_v1p21_-40c','ff_1p21v_1p21v_m40c'),('tt_v1p1_25c','tt_1p10v_1p10v_25c')]:
        for vt in ['HVT','LVT','RVT']:
            p=pdk/('SCC40NLL_VHSC40_'+vt+'_V0.1')/('SCC40NLL_VHSC40_'+vt+'_V0p1')/'liberty/1.1v'/('scc40nll_vhsc40_'+vt.lower()+'_'+standard+'_basic.db')
            p.parent.mkdir(parents=True,exist_ok=True);p.write_text('MOCK LIBRARY NOT PPA')
        (ram/('RAMSP4096X16_'+macro+'.db')).write_text('MOCK LIBRARY NOT PPA')
    result={}
    for mode,scenarios in [('dc',['normal','ddc','analyze','link','macro','compile','write']),('pt',['normal','link','macro','saif','power']),('pt_preflight',['normal','power'])]:
        flow='pt' if mode=='pt_preflight' else mode
        for failure in scenarios:
            build=project/'build'
            if build.exists():shutil.rmtree(build)
            t=tkinter.Tcl();t.setvar('failure',failure);t.setvar('flow',flow)
            t.setvar('env(KWT_PDK_ROOT)',str(pdk));t.setvar('env(KWT_SRAM_DB_DIR)',str(ram))
            if mode=='pt_preflight':t.setvar('env(SOC_PT_PREFLIGHT)','1')
            t.eval('set search_path {};set stages {};set loaded 0')
            t.eval(r'''
proc exit {{code 0}} {return -code error "MOCK_EXIT:$code"}
proc exec {args} {return MOCK_HOST_CHECK}
proc set_app_var {args} {return 1}
proc set_host_options {args} {return 1}
proc define_design_lib {args} {return 1}
proc set_min_library {args} {return 1}
proc all_clocks {args} {return {hfclk lfclk jtagclk}}
proc remove_clock {args} {return 1}
proc read_ddc {args} {lappend ::stages read_ddc;set ::loaded [expr {$::failure ne "ddc"}];return $::loaded}
proc analyze {args} {lappend ::stages analyze;return [expr {$::failure ne "analyze"}]}
proc elaborate {args} {lappend ::stages elaborate;return 1}
proc current_design {args} {return kwt_soc_joint}
proc get_designs {args} {return [expr {$::loaded ? "kwt_soc_joint" : ""}]}
proc read_verilog {args} {set ::loaded 1;return 1}
proc remove_design {args} {set ::loaded 0}
proc link {args} {return [expr {$::failure ne "link"}]}
proc link_design {args} {return [expr {$::failure ne "link"}]}
proc get_cells {args} {
 set q [join $args]
 if {[string match *RAMSP4096X16* $q]} {set r {};for {set i 0} {$i<[expr {$::failure eq "macro" ? 99 : 100}]} {incr i} {lappend r ram$i};return $r}
 if {[string match *is_hierarchical* $q]} {return {u_kwt1_mmio/fake u_e203_subsys_top/fake u_shmem/fake glue}}
 if {[string match *GTECH* $q] || [string match *SELECT_OP* $q]} {return {}}
 return u_kwt1_mmio
}
proc sizeof_collection {v} {return [llength $v]}
proc foreach_in_collection {name values body} {uplevel 1 [list foreach $name $values $body]}
proc get_object_name {v} {return $v}
proc get_lib_cells {args} {return mocklib/cell}
proc get_attribute {cell attr} {if {$attr eq "ref_name"} {return MOCK_CELL};return 1.0}
proc set_dont_touch {args} {return 1}
proc compile_ultra {args} {lappend ::stages compile;return [expr {$::failure ne "compile"}]}
proc check_design {args} {return 1}
proc report_area {args} {return MOCK_AREA}
proc report_qor {args} {return MOCK_QOR}
proc report_constraint {args} {return MOCK_CONSTRAINT}
proc change_names {args} {return 1}
proc write {args} {
 lappend ::stages write;if {$::failure eq "write"} {return 0}
 set p [lindex $args [expr {[lsearch $args -output]+1}]];set f [open $p w];puts $f MOCK;close $f;return 1
}
proc write_sdc {args} {return 1}
rename source mock_original_source
proc source {p} {if {[string match *constraints.sdc $p]} {lappend ::stages constraints;return 1};uplevel 1 [list mock_original_source $p]}
proc redirect {args} {
 set p [lindex $args 0];if {$p eq "-file"} {set p [lindex $args 1]}
 uplevel 1 [lindex $args end];set f [open $p w];puts $f MOCK_REPORT_NOT_PPA;close $f
}
proc read_sdc {args} {return 1}
proc update_timing {args} {return 1}
proc report_analysis_coverage {args} {return MOCK_COVERAGE}
proc check_timing {args} {return MOCK_TIMING}
proc report_disable_timing {args} {return MOCK_DISABLED}
proc report_timing {args} {return MOCK_PATH}
proc read_saif {args} {lappend ::stages saif;if {$::failure eq "saif"} {error MOCK_SAIF_FAILED};return 1}
proc report_switching_activity {args} {return MOCK_ACTIVITY}
proc check_power {args} {return MOCK_POWER_CHECK}
proc update_power {args} {lappend ::stages power;if {$::failure eq "power"} {error MOCK_POWER_FAILED};return 1}
proc report_power {args} {return MOCK_POWER_NOT_ACTUAL}
proc report_units {args} {return MOCK_UNITS}
proc report_design {args} {return MOCK_DESIGN}
''')
            text=(project/('flow/'+flow+'.tcl')).read_text()
            text=text.replace('[file join [file dirname [info script]] common.tcl]',str(project/'flow/common.tcl').replace('\\','/'))
            try:t.eval(text)
            except tkinter.TclError as e:assert 'MOCK_EXIT' in str(e),str(e)
            steps=list(t.splitlist(t.getvar('stages')))
            completed=(project/('build/'+mode+'/complete')).exists() if flow=='pt' else (project/'build/dc/mapped.v').exists()
            if mode=='pt_preflight':assert 'saif' not in steps,'preflight must not claim task activity'
            if failure=='normal':assert completed,(flow,steps)
            else:assert not completed,(flow,failure,steps)
            result[mode+'/'+failure]=dict(completion=completed,steps=steps)
    report=dict(passed=True,actual_EDA=False,cases=result,scope='mock Tcl command control/failure traps; not real tool compatibility or PPA')
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print('SOC_FLOW_MOCK_PASSED',len(result))


if __name__=='__main__':main()
