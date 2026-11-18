# One compound Tcl command: DC's -f reader may continue after a top-level
# error. The catch must contain every stage, including project configuration.
if {[catch {
set kwt_fd [open [file join [file dirname [info script]] project.tcl] r]
set kwt_config [read $kwt_fd]
close $kwt_fd
eval $kwt_config
puts [kwt_host_python $PROJECT/flow/project.py check]
puts [kwt_host_python $PROJECT/flow/project.py preflight]
set OUT $PROJECT/build/dc
if {[file exists $OUT/mapped.v]} { error "mapped.v already exists; use a new project directory" }
file mkdir $OUT/reports
define_design_lib WORK -path $OUT/WORK
set kwt_libs [corner_libs ss]
set kwt_min_libs [corner_libs ff]
set_app_var target_library $kwt_libs
set_app_var link_library [concat "*" $kwt_libs $kwt_min_libs]
foreach maximum $kwt_libs minimum $kwt_min_libs {
    if {![set_min_library $maximum -min_version $minimum]} { error "min-library association failed: $maximum" }
    puts "KWT_MIN_LIBRARY $maximum $minimum"
}
set_app_var search_path [concat [list $PROJECT/rtl/v2/generated $PROJECT/rtl/v2] $search_path]
if {[get_app_var target_library] ne $kwt_libs} { error "target_library did not take effect" }
foreach f $kwt_libs { puts "KWT_TARGET_LIBRARY $f" }
if {![analyze -format sverilog -define KWT_TECH_SRAM -lib WORK $rtl_files]} { error "RTL analysis failed" }
elaborate $TOP -lib WORK
current_design $TOP
if {![link]} { error "link failed" }
set kwt_macro_views [sizeof_collection [get_lib_cells -quiet */RAMSP4096X16]]
if {$kwt_macro_views < 1} { error "SRAM Liberty cell is not bound" }
set kwt_ret_views [sizeof_collection [get_lib_pins -quiet */RAMSP4096X16/RET1N]]
if {$kwt_ret_views != $kwt_macro_views} { error "RET1N pin missing from a loaded SRAM library view" }
puts "KWT_SRAM_RET1N_VIEWS $kwt_ret_views"
set macros [get_cells -hierarchical -filter "ref_name =~ RAMSP4096X16*" -quiet]
if {[sizeof_collection $macros] != 20} { error "expected 20 SRAM instances" }
# Protect cells, not the wrapper design: the wrapper's control gates must map.
if {![set_dont_touch $macros]} { error "macro protection failed" }
if {![read_sdc $SDC]} { error "read_sdc failed" }
set kwt_fd [open $PROJECT/flow/reset_rules.tcl r]
set kwt_reset_rules [read $kwt_fd]
close $kwt_fd
eval $kwt_reset_rules
if {![set_fix_hold [get_clocks accel_clk]]} { error "set_fix_hold failed" }
kwt_reset_distribution_rules elaborated
# Exercise post-mapping query syntax before the hour-long initial compile.
kwt_reset_distribution_rules mapped_contract_preflight
redirect -file $OUT/reports/check_design.rpt { check_design -summary }
puts "KWT_SYNTH_STAGE INITIAL"
if {![compile_ultra -no_autoungroup]} { error "compile_ultra failed" }
# Forensic checkpoint only, never accepted as the final mapped.v/netlist receipt.
# It preserves the expensive initial stage if later diagnostics/optimization fail.
if {![write -format ddc -hierarchy -output $OUT/initial_mapped.ddc]} { error "initial DDC checkpoint failed" }
puts "KWT_INITIAL_DDC_CHECKPOINT $OUT/initial_mapped.ddc"
kwt_reset_distribution_rules mapped
redirect -file $OUT/reports/reset_drc_before.rpt { report_constraint -all_violators -verbose }
set kwt_cells_before [sizeof_collection [get_cells -hierarchical -quiet]]
puts "KWT_SYNTH_STAGE RESET_DRC"
if {![compile_ultra -incremental -only_design_rule]} { error "reset distribution compile failed" }
set kwt_cells_after [sizeof_collection [get_cells -hierarchical -quiet]]
puts "KWT_RESET_TREE_CELL_DELTA [expr {$kwt_cells_after-$kwt_cells_before}]"
puts "KWT_SYNTH_STAGE HOLD_AFTER_RESET_TREE"
if {![compile_ultra -incremental -no_autoungroup]} { error "incremental hold/timing compile failed" }
kwt_reset_distribution_rules final
foreach pattern {GTECH* SELECT_OP*} {
    set n [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ $pattern" -quiet]]
    puts "KWT_UNMAPPED $pattern $n"
    if {$n != 0} { error "unmapped cells survived: $pattern" }
}
set n [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ RAMSP4096X16*" -quiet]]
puts "KWT_MAPPED_MACRO_INSTANCES $n"
if {$n != 20} { error "macro count changed" }
redirect -file $OUT/reports/area.rpt { report_area -hierarchy }
redirect -file $OUT/reports/check_design_mapped.rpt { check_design }
redirect -file $OUT/reports/operating_conditions.rpt { report_design }
redirect -file $OUT/reports/setup.rpt { report_timing -significant_digits 6 -delay_type max -max_paths 20 -nosplit }
redirect -file $OUT/reports/hold.rpt { report_timing -significant_digits 6 -delay_type min -max_paths 20 -nosplit }
redirect -file $OUT/reports/constraints.rpt { report_constraint -all_violators -verbose }
change_names -rules verilog -hierarchy
if {![write -format ddc -hierarchy -output $OUT/mapped.ddc]} { error "DDC export failed" }
if {![write -format verilog -hierarchy -output $OUT/mapped.v]} { error "netlist export failed" }
if {![write_sdc -nosplit $OUT/mapped.sdc]} { error "SDC export failed" }
puts [kwt_host_python $PROJECT/flow/project.py attest-dc]
puts "KWT_CLEAN_SYNTH_DONE"
} kwt_failure]} {
    puts stderr "KWT_FATAL $kwt_failure"
    puts stderr $::errorInfo
    exit 1
}
exit
