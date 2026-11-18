"""Tcl control-flow fault injection only; no Synopsys execution or PPA."""
import argparse
import json
from pathlib import Path
import tkinter
import sys
import shutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument('--max-only', action='store_true', help='two-stage batch with hold optimization disabled')
    a = ap.parse_args()
    project, out = a.project.resolve(), a.output.resolve()
    if out.exists():
        raise ValueError("choose a fresh output directory")
    out.mkdir(parents=True)
    source_project = project
    project = out/'project'
    shutil.copytree(source_project, project)
    # The helper only verifies presence; these are explicitly synthetic files.
    pdk, ram = out/"synthetic_pdk", out/"synthetic_ram"
    for std, macro in [("ss_v0p99_125c", "ss_0p99v_0p99v_125c"),
                       ("ff_v1p21_-40c", "ff_1p21v_1p21v_m40c"),
                       ("tt_v1p1_25c", "tt_1p10v_1p10v_25c")]:
        for vt in ["HVT", "LVT", "RVT"]:
            p = pdk/("SCC40NLL_VHSC40_%s_V0.1" % vt)/("SCC40NLL_VHSC40_%s_V0p1" % vt)/"liberty/1.1v"/("scc40nll_vhsc40_%s_%s_basic.db" % (vt.lower(),std))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("SYNTHETIC CONTROL-FLOW TEST ONLY")
        ram.mkdir(exist_ok=True)
        (ram/("RAMSP4096X16_%s.db" % macro)).write_text("SYNTHETIC CONTROL-FLOW TEST ONLY")
    cases = {}
    scenarios = ["missing_env", "min_library", "analyze", "link", "ret1n", "reset_cone",
                 "fanout_return0", "transition_return0", "mapped_rename", "missing_anchor", "mapped_anchor_lost", "final_anchor_lost", "small_mapped_cone", "checkpoint", "compile", "compile_reset", "compile_hold", "generic", "normal"]
    if a.max_only:
        scenarios.remove('compile_hold')
    for scenario in scenarios:
        t = tkinter.Tcl()
        t.call("set", "::env(KWT_HOST_PYTHON)", sys.executable)
        t.eval("set stages {}; set search_path {}; set compile_count 0; set failure " + scenario)
        t.setvar('last_compile', 2 if a.max_only else 3)
        t.eval(r'''
proc exit {{code 0}} {return -code error "TEST_EXIT:$code"}
proc exec {args} {return "MOCK_EXTERNAL_CHECK"}
proc define_design_lib {args} {lappend ::stages work}
proc set_app_var {k v} {uplevel #0 [list set $k $v]}
proc set_host_options {args} {lappend ::stages host_options}
proc get_app_var {k} {uplevel #0 [list set $k]}
proc set_min_library {args} {if {$::failure eq "min_library"} {return 0}; lappend ::stages min_library;return 1}
proc analyze {args} {lappend ::stages analyze; return [expr {$::failure ne "analyze"}]}
proc elaborate {args} {
 lappend ::stages elaborate
 set ::mock_current kwt1_mmio
 if {[string match *-parameters* $args]} {set ::mock_current kwt1_mmio_BLOCK_STREAM1}
}
proc current_design {args} {
 if {[llength $args]} {set ::mock_current [lindex $args 0]}
 return $::mock_current
}
proc get_object_name {x} {return $x}
proc rename_design {old new} {
 if {$old ne $::mock_current || $new ne "kwt1_mmio"} {error BAD_RENAME}
 set ::mock_current $new
 lappend ::stages rename_parameterized_top
 return 1
}
proc get_designs {args} {return 1}
proc link {} {lappend ::stages link; return [expr {$::failure ne "link"}]}
proc get_lib_cells {args} {return 1}
proc get_lib_pins {args} {return [expr {$::failure ne "ret1n"}]}
proc get_clocks {args} {return 1}
proc set_fix_hold {args} {lappend ::stages fix_hold;return 1}
proc get_nets {args} {return [expr {$::failure ne "reset_cone" && !($::failure eq "mapped_rename" && $::compile_count > 0)}]}
proc get_pins {args} {return 1}
proc get_ports {args} {
 if {$::failure eq "missing_anchor" || ($::failure eq "mapped_anchor_lost" && $::compile_count >= 1) || ($::failure eq "final_anchor_lost" && $::compile_count >= $::last_compile)} {return 1}
 return 2
}
proc all_fanout {args} {
 if {[string match *-endpoints_only* $args] && $::failure eq "small_mapped_cone"} {return 10}
 return 5000
}
proc filter_collection {objects query} {if {$query ne {object_class != design}} {error BAD_DESIGN_FILTER};return 0}
proc add_to_collection {a b} {return [expr {$a+$b}]}
proc set_max_fanout {value args} {if {$value != 32} {error BAD_FANOUT}; lappend ::stages reset_fanout;return [expr {$::failure ne "fanout_return0"}]}
proc set_max_transition {value args} {if {$value != 0.400} {error BAD_TRANSITION}; lappend ::stages reset_transition;return [expr {$::failure ne "transition_return0"}]}
proc get_cells {args} {
    if {[string match *GTECH* $args]} {return [expr {$::failure eq "generic"}]}
    if {[string match *SELECT_OP* $args]} {return 0}
    return 20
}
proc sizeof_collection {n} {return $n}
proc set_dont_touch {args} {return 1}
proc read_sdc {args} {return 1}
proc redirect {args} {}
proc compile_ultra {args} {
  lappend ::stages compile
  incr ::compile_count
  if {$::failure eq "compile" && $::compile_count == 1} {return 0}
  if {$::failure eq "compile_reset" && $::compile_count == 2} {return 0}
  if {$::failure eq "compile_hold" && $::compile_count == 3} {return 0}
  return 1
}
proc change_names {args} {lappend ::stages export}
proc write {args} {
 if {[string match *initial_mapped.ddc* $args]} {
  lappend ::stages checkpoint
  return [expr {$::failure ne "checkpoint"}]
 }
 lappend ::stages write;return 1
}
proc write_sdc {args} {lappend ::stages sdc;return 1}
''')
        if scenario == "missing_env":
            t.eval("unset -nocomplain ::env(KWT_PDK_ROOT)")
        else:
            t.call("set", "::env(KWT_PDK_ROOT)", pdk.as_posix())
            t.call("set", "::env(KWT_SRAM_DB_DIR)", ram.as_posix())
        try:
            t.call("source", (project/"flow/dc.tcl").as_posix())
            raise AssertionError("flow failed to exit")
        except tkinter.TclError as error:
            assert ("TEST_EXIT:0" if scenario in ["normal", "mapped_rename"] else "TEST_EXIT:1") in str(error), str(error)
        stages = str(t.eval("join $stages ,")).split(",")
        assert ("export" in stages) == (scenario in ["normal", "mapped_rename"]), (scenario, stages)
        if scenario == "missing_env":
            assert "work" not in stages and "analyze" not in stages
        if scenario in ["analyze", "link"]:
            assert "compile" not in stages
        expected_compile = {"compile": 1, "compile_reset": 2, "compile_hold": 3, "generic": 3, "normal": 3, "mapped_rename": 3, "checkpoint": 1, "mapped_anchor_lost": 1, "final_anchor_lost": 3}.get(scenario, 0)
        if a.max_only and expected_compile == 3:
            expected_compile = 2
        assert stages.count("compile") == expected_compile, (scenario, stages)
        if a.max_only:
            assert 'fix_hold' not in stages
            if 'elaborate' in stages:
                parameterized = 'BLOCK_STREAM=1' in (project/'flow/project.tcl').read_text()
                assert ('rename_parameterized_top' in stages) == parameterized
        if scenario in ["normal", "mapped_rename", "mapped_anchor_lost", "final_anchor_lost"]:
            assert stages.count("checkpoint") == 1
        cases[scenario] = stages
    (project/'build/dc/mapped.v').write_text('MOCK PT INPUT, NOT EDA NETLIST')
    pt_cases = {}
    for scenario in ['pt_normal', 'pt_ret1n', 'pt_link']:
        t = tkinter.Tcl()
        for k, v in [('KWT_HOST_PYTHON', sys.executable), ('KWT_PDK_ROOT', str(pdk)),
                     ('KWT_SRAM_DB_DIR', str(ram)), ('KWT_PT_RUN', scenario)]:
            t.call('set', '::env('+k+')', v)
        t.eval('unset -nocomplain ::env(KWT_GATE_SAIF)')
        t.eval('set loaded 0; set updates 0; set mode '+scenario)
        t.eval(r'''
proc exit {{code 0}} {error TEST_EXIT:$code}
proc exec {args} {return MOCK_EXTERNAL_CHECK}
proc set_app_var {args} {}
proc get_designs {args} {return $::loaded}
proc sizeof_collection {n} {return $n}
proc remove_design {args} {if {!$::loaded} {error EMPTY_REMOVE}; set ::loaded 0}
proc read_verilog {args} {set ::loaded 1}
proc current_design {args} {}
proc link_design {} {return [expr {$::mode ne "pt_link"}]}
proc get_cells {args} {return 20}
proc index_collection {args} {return 1}
proc get_lib_cells {args} {return 1}
proc get_object_name {args} {return mock_$::corner/RAMSP4096X16}
proc get_lib_pins {args} {
  if {![string match *mock_*/RAMSP4096X16/RET1N* $args]} {error WRONG_BOUND_MACRO_REFERENCE}
  return [expr {!($::mode eq "pt_ret1n" && $::corner eq "ff")}]
}
proc read_sdc {args} {}
proc update_timing {args} {incr ::updates}
proc redirect {file body} {set f [open $file w];puts $f MOCK_REPORT;close $f;uplevel 1 $body}
proc report_timing {args} {}
proc report_qor {args} {}
proc check_timing {args} {}
proc report_disable_timing {args} {}
proc report_analysis_coverage {args} {}
proc report_constraint {args} {}
''')
        try:
            t.call('source', (project/'flow/pt.tcl').as_posix())
        except tkinter.TclError as e:
            assert ('TEST_EXIT:0' if scenario == 'pt_normal' else 'TEST_EXIT:1') in str(e), str(e)
        else:
            raise AssertionError('mock PT did not exit')
        updates = int(t.getvar('updates'))
        assert updates == {'pt_normal': 3, 'pt_ret1n': 1, 'pt_link': 0}[scenario]
        assert (project/'build'/scenario/'complete').exists() == (scenario == 'pt_normal')
        pt_cases[scenario] = dict(updates=updates, completion=scenario == 'pt_normal')
    report = dict(passed=True, max_only=a.max_only, fault_cases=cases, PT_bound_macro_tests=pt_cases, EDA_execution=False,
                  scope="standard Tcl with mocked tool commands; actual DC retry required")
    (out/"summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
