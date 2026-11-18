if {[catch {
set kwt_fd [open [file join [file dirname [info script]] project.tcl] r]
set kwt_config [read $kwt_fd]
close $kwt_fd
eval $kwt_config
puts [kwt_host_python $PROJECT/flow/project.py check-dc]
puts [kwt_host_python $PROJECT/flow/project.py preflight]
set NETLIST $PROJECT/build/dc/mapped.v
require_file $NETLIST
set OUT $PROJECT/build/pt
if {[info exists ::env(KWT_PT_RUN)]} {
    if {![regexp {^pt_[A-Za-z0-9_]+$} $::env(KWT_PT_RUN)]} { error "invalid KWT_PT_RUN" }
    set OUT $PROJECT/build/$::env(KWT_PT_RUN)
}
if {[file exists $OUT]} { error "PT result directory already exists; preserve this run" }
file mkdir $OUT
set_app_var power_enable_analysis true
foreach corner {ss ff tt} {
    if {[sizeof_collection [get_designs -quiet *]] > 0} { remove_design -all }
    set link_path [concat "*" [corner_libs $corner]]
    read_verilog $NETLIST
    current_design $TOP
    if {![link_design]} { error "PT link failed at $corner" }
    set kwt_macros [get_cells -hierarchical -filter "ref_name =~ RAMSP4096X16*" -quiet]
    set n [sizeof_collection $kwt_macros]
    puts "KWT_PT_MACROS $corner $n"
    if {$n != 20} { error "PT macro count changed" }
    set kwt_macro_ref [get_lib_cells -of_objects [index_collection $kwt_macros 0]]
    if {[sizeof_collection $kwt_macro_ref] != 1} { error "ambiguous bound macro library at $corner" }
    set kwt_macro_ref_name [get_object_name $kwt_macro_ref]
    if {[sizeof_collection [get_lib_pins -quiet $kwt_macro_ref_name/RET1N]] != 1} {
        error "PT SRAM RET1N library binding missing at $corner"
    }
    puts "KWT_PT_SRAM_REFERENCE $corner $kwt_macro_ref_name RET1N"
    read_sdc $SDC
    update_timing -full
    redirect $OUT/timing_$corner.rpt {
        report_timing -significant_digits 6 -delay_type max -max_paths 20 -nworst 5 -path_type full_clock_expanded
        report_timing -significant_digits 6 -delay_type min -max_paths 20 -nworst 5
        report_qor
    }
    redirect $OUT/check_timing_$corner.rpt { check_timing -verbose; report_disable_timing }
    redirect $OUT/coverage_$corner.rpt { report_analysis_coverage }
    redirect $OUT/coverage_untested_$corner.rpt { report_analysis_coverage -status_details untested }
    redirect $OUT/constraints_$corner.rpt { report_constraint -all_violators -verbose }
    redirect $OUT/area_$corner.rpt { report_qor }
    if {$corner eq "tt" && [info exists ::env(KWT_GATE_SAIF)]} {
        require_file $::env(KWT_GATE_SAIF)
        puts [kwt_host_python $PROJECT/flow/project.py check-saif $::env(KWT_GATE_SAIF)]
        read_saif $::env(KWT_GATE_SAIF) -strip_path tb_gate_tasks/dut
        redirect $OUT/activity_tt.rpt { report_switching_activity -list_not_annotated }
        update_power
        redirect $OUT/power_accelerator_tt.rpt { report_power -verbose }
    }
}
set fd [open $OUT/complete w]; puts $fd "KWT_CLEAN_PT_DONE"; close $fd
puts "KWT_CLEAN_PT_DONE"
} kwt_failure]} {
    puts stderr "KWT_FATAL $kwt_failure"
    puts stderr $::errorInfo
    exit 1
}
exit
