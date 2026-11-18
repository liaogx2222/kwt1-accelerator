# Characterize the saved INITIAL mapping only. No compile or timing waiver.
if {[catch {
set kwt_fd [open [file join [file dirname [info script]] .. flow project.tcl] r]
set kwt_config [read $kwt_fd]
close $kwt_fd
eval $kwt_config
puts [kwt_host_python $PROJECT/recovery/verify.py check-input]
puts [kwt_host_python $PROJECT/flow/project.py preflight]
set OUT $PROJECT/build/dc
if {[file exists $OUT]} { error "recovery output exists; preserve it" }
file mkdir $OUT/reports
set maximum_libs [corner_libs ss]
set minimum_libs [corner_libs ff]
set_app_var target_library $maximum_libs
set_app_var link_library [concat "*" $maximum_libs $minimum_libs]
foreach maximum $maximum_libs minimum $minimum_libs {
    if {![set_min_library $maximum -min_version $minimum]} { error "recovery min-library association failed" }
}
read_ddc $PROJECT/build/recovery_input/initial_mapped.ddc
if {[sizeof_collection [get_designs -quiet $TOP]] != 1} { error "checkpoint top missing" }
current_design $TOP
if {![link]} { error "checkpoint link failed" }
set macros [get_cells -hierarchical -filter "ref_name =~ RAMSP4096X16*" -quiet]
if {[sizeof_collection $macros] != 20} { error "checkpoint macro count not 20" }
set views [sizeof_collection [get_lib_cells -quiet */RAMSP4096X16]]
set pins [sizeof_collection [get_lib_pins -quiet */RAMSP4096X16/RET1N]]
if {$views < 1 || $views != $pins} { error "checkpoint RET1N library binding invalid" }
puts "KWT_RECOVERY_MACROS 20 RET1N_views=$pins"
foreach pattern {GTECH* SELECT_OP*} {
    set n [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ $pattern" -quiet]]
    puts "KWT_RECOVERY_UNMAPPED $pattern $n"
    if {$n != 0} { error "checkpoint contains unmapped cells: $pattern" }
}
if {![read_sdc $SDC]} { error "checkpoint original SDC load failed" }
set kwt_fd [open $PROJECT/flow/reset_rules.tcl r]
set kwt_rules [read $kwt_fd]
close $kwt_fd
eval $kwt_rules
kwt_reset_distribution_rules mapped
puts "KWT_RECOVERY_SCOPE INITIAL_MAPPING_ONLY NO_COMPILE HOLD_NOT_SIGNED_OFF"
redirect -file $OUT/reports/area.rpt { report_area -hierarchy }
redirect -file $OUT/reports/check_design_mapped.rpt { check_design }
redirect -file $OUT/reports/operating_conditions.rpt { report_design }
redirect -file $OUT/reports/setup.rpt { report_timing -significant_digits 6 -delay_type max -max_paths 20 -nosplit }
redirect -file $OUT/reports/hold.rpt { report_timing -significant_digits 6 -delay_type min -max_paths 20 -nosplit }
redirect -file $OUT/reports/constraints.rpt { report_constraint -all_violators -verbose }
change_names -rules verilog -hierarchy
if {![write -format ddc -hierarchy -output $OUT/mapped.ddc]} { error "recovery DDC export failed" }
if {![write -format verilog -hierarchy -output $OUT/mapped.v]} { error "recovery Verilog export failed" }
if {![write_sdc -nosplit $OUT/mapped.sdc]} { error "recovery SDC export failed" }
puts [kwt_host_python $PROJECT/flow/project.py attest-dc]
puts [kwt_host_python $PROJECT/recovery/verify.py attest-output]
puts "KWT_INITIAL_CHECKPOINT_EXPORT_DONE"
} kwt_failure]} {
    puts stderr "KWT_RECOVERY_FATAL $kwt_failure"
    puts stderr $::errorInfo
    exit 1
}
exit
