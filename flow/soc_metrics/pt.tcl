if {[catch {
 source [file join [file dirname [info script]] common.tcl]
 puts [host_python $PROJECT/flow/project.py check-netlist]
 set OUT $PROJECT/build/pt
 set preflight [expr {[info exists ::env(SOC_PT_PREFLIGHT)] && $::env(SOC_PT_PREFLIGHT) eq "1"}]
 if {$preflight} {set OUT $PROJECT/build/pt_preflight}
 if {[file exists $OUT]} {error "preserve existing PT outputs"}
 file mkdir $OUT
 set_app_var power_enable_analysis true
 foreach corner {tt} {
  if {[sizeof_collection [get_designs -quiet *]] > 0} {remove_design -all}
  set link_path [concat * [libs $corner]]
  read_verilog $PROJECT/build/dc/mapped.v
  current_design $TOP
  if {![link_design]} {error "SoC PT link failed"}
  check_macros
  # Fresh declared TT constraints: do not import inherited SS optimization
  # operating conditions or private standalone clocks from the source DDC.
  read_soc_constraints
  update_timing -full
  redirect $OUT/qor_$corner.rpt {report_qor}
  redirect $OUT/coverage_$corner.rpt {report_analysis_coverage;report_analysis_coverage -status_details untested}
  redirect $OUT/check_timing_$corner.rpt {check_timing -verbose;report_disable_timing}
  redirect $OUT/constraints_$corner.rpt {report_constraint -all_violators -verbose}
  redirect $OUT/timing_$corner.rpt {
   report_timing -significant_digits 6 -delay_type max -max_paths 20 -path_type full_clock_expanded
   report_timing -significant_digits 6 -delay_type min -max_paths 20 -path_type full_clock_expanded
  }
  if {$corner eq "tt"} {
   if {!$preflight} {
    puts [host_python $PROJECT/flow/project.py check-activity]
    read_saif $PROJECT/build/gate/cold/task.saif -strip_path tb_soc_metrics/dut
   } else {puts "SOC_POWER_PREFLIGHT_ONLY default_activity_not_task_metrics"}
   redirect $OUT/activity_tt.rpt {report_switching_activity;report_switching_activity -list_not_annotated}
   redirect $OUT/power_checks_tt.rpt {check_power -verbose}
   update_power
   redirect $OUT/power_soc_tt.rpt {report_power -verbose;report_power -hierarchy}
   redirect $OUT/power_libraries_tt.rpt {report_units;report_design}
  }
 }
 set fd [open $OUT/complete w];puts $fd SOC_FULL_PT_DONE;close $fd
 puts SOC_FULL_PT_DONE
} failure]} {puts stderr "SOC_FATAL $failure";puts stderr $::errorInfo;exit 1}
exit
