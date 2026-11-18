if {[catch {
 set ROOT [pwd]
 source $ROOT/flow/common.tcl
 set TOP e203_subsys_top
 set OUT $ROOT/build/cpu_precompile_v1
 if {[file exists $OUT]} {error "preserve CPU precompile output"}
 file mkdir $OUT/reports
 set SCRIPT $ROOT/review_tools/cpu_precompile_v1/cpu_precompile.py
 puts [host_python $SCRIPT check]
 define_design_lib WORK -path $OUT/WORK
 set_app_var alib_library_analysis_path $OUT/alib
 file mkdir $OUT/alib
 set_host_options -max_cores 4
 set maximum [libs tt]
 set_app_var target_library $maximum
 set_app_var link_library [concat * $maximum]
 set fd [open $ROOT/flow/includes.txt r]
 foreach d [split [read $fd] \n] {if {[string trim $d] ne ""} {lappend search_path $ROOT/[string trim $d]}}
 close $fd
 set fd [open $ROOT/review_tools/cpu_precompile_v1/cpu_sources.txt r]
 set files {}
 foreach n [split [read $fd] \n] {if {[string trim $n] ne ""} {lappend files $ROOT/[string trim $n]}}
 close $fd
 if {![analyze -format sverilog -define {FPGA_SOURCE SYNTHESIS DISABLE_SV_ASSERTION} -lib WORK $files]} {error "CPU analysis failed"}
 elaborate $TOP -lib WORK
 current_design $TOP
 if {![link]} {error "CPU link failed"}
 set macros [get_cells -hierarchical -quiet -filter {ref_name =~ RAMSP4096X16*}]
 if {[sizeof_collection $macros] != 16} {error "CPU ITCM+DTCM macro count must be 16"}
 set_dont_touch $macros true
 create_clock -name hfclk -period 6.666667 [get_ports hfextclk]
 create_clock -name lfclk -period 30517.578125 [get_ports lfextclk]
 create_clock -name jtagclk -period 100.000 [get_ports io_pads_jtag_TCK_i_ival]
 set_clock_uncertainty -setup 0.300 [all_clocks]
 set_clock_uncertainty -hold 0.150 [all_clocks]
 set data_in [remove_from_collection [all_inputs] [get_ports {hfextclk lfextclk io_pads_jtag_TCK_i_ival}]]
 set_input_delay -clock hfclk -max 1.500 $data_in
 set_input_delay -clock hfclk -min 0.000 $data_in
 set_input_transition 0.150 $data_in
 set_output_delay -clock hfclk -max 1.500 [all_outputs]
 set_output_delay -clock hfclk -min 0.000 [all_outputs]
 set_load 0.020 [all_outputs]
 set before_ports [lsort [get_object_name [get_ports *]]]
 puts "SOC_CPU_PRECOMPILE TT 1.1V 25C 150MHz boundary_optimization=OFF hold_fix=OFF"
 if {![compile_ultra -no_autoungroup -no_boundary_optimization]} {error "CPU compile failed"}
 if {$before_ports ne [lsort [get_object_name [get_ports *]]]} {error "CPU public ports changed"}
 foreach pattern {GTECH* SELECT_OP*} {
  if {[sizeof_collection [get_cells -hierarchical -quiet -filter "ref_name =~ $pattern"]] != 0} {error "CPU unmapped $pattern"}
 }
 set macros [get_cells -hierarchical -quiet -filter {ref_name =~ RAMSP4096X16*}]
 if {[sizeof_collection $macros] != 16} {error "CPU mapped macros changed"}
 redirect -file $OUT/reports/area.rpt {report_area -hierarchy}
 redirect -file $OUT/reports/check_design.rpt {check_design}
 redirect -file $OUT/reports/qor.rpt {report_qor}
 redirect -file $OUT/reports/operating_conditions.rpt {report_design}
 redirect -file $OUT/reports/constraints.rpt {report_constraint -all_violators -verbose}
 change_names -rules verilog -hierarchy
 set fd [open $OUT/reports/macros.txt w]
 foreach_in_collection macro $macros {puts $fd [get_object_name $macro]}
 close $fd
 if {![write -format ddc -hierarchy -output $OUT/cpu_mapped.ddc]} {error "CPU DDC export failed"}
 if {![write -format verilog -hierarchy -output $OUT/cpu_mapped.v]} {error "CPU netlist export failed"}
 puts [host_python $SCRIPT attest]
 puts SOC_CPU_PRECOMPILE_DONE
} failure]} {puts stderr "SOC_CPU_FATAL $failure";puts stderr $::errorInfo;exit 1}
exit
