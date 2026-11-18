if {[catch {
 source [file join [file dirname [info script]] common.tcl]
 puts [host_python $PROJECT/flow/project.py check]
 set OUT $PROJECT/build/dc
 if {[file exists $OUT]} {error "preserve existing DC outputs"}
 file mkdir $OUT/reports
 define_design_lib WORK -path $OUT/WORK
 file mkdir $OUT/alib
 set_app_var alib_library_analysis_path $OUT/alib
 set_host_options -max_cores 4
 # The supplied competition Q&A permits a declared reasonable operating PVT.
 # Keep one TT operating/optimization condition throughout the platform run.
 set maximum [libs tt]
 set_app_var target_library $maximum
 set_app_var link_library [concat * $maximum]
 puts "SOC_DECLARED_PVT TT 1.1V 25C target=150MHz platform_optimization=TT frozen_accelerator_optimization=SS"
 # Reuse the already accepted accelerator DDC, freeze its mapped implementation.
 # This avoids another multi-hour accelerator optimization just to add the CPU.
 read_ddc $PROJECT/frozen_accel/mapped.ddc
 if {[sizeof_collection [get_designs -quiet kwt1_mmio]] != 1} {error "accelerator DDC top missing"}
 set_app_var target_library $maximum
 set_app_var link_library [concat * $maximum]
 current_design kwt1_mmio
 if {![set_dont_touch [get_designs kwt1_mmio] true]} {error "accelerator protection failed"}
 set fd [open $PROJECT/flow/includes.txt r]
 foreach directory [split [read $fd] \n] {if {[string trim $directory] ne ""} {lappend search_path $PROJECT/[string trim $directory]}}
 close $fd
 set files {}
 set fd [open $PROJECT/flow/soc_sources.txt r]
 foreach line [split [read $fd] \n] {if {[string trim $line] ne ""} {lappend files $PROJECT/[string trim $line]}}
 close $fd
 if {![analyze -format sverilog -define {FPGA_SOURCE SYNTHESIS DISABLE_SV_ASSERTION} -lib WORK $files]} {error "SoC analysis failed"}
 elaborate $TOP -lib WORK
 current_design $TOP
 if {![link]} {error "SoC link failed"}
 set macros [check_macros]
 if {![set_dont_touch $macros]} {error "macro protection failed"}
 set frozen [get_cells u_kwt1_mmio]
 if {[sizeof_collection $frozen] != 1} {error "accelerator hierarchy missing"}
 if {![set_dont_touch $frozen true]} {error "instance protection failed"}
 remove_clock [all_clocks]
 read_soc_constraints
 redirect -file $OUT/reports/check_design_before.rpt {check_design}
 puts "SOC_SYNTH_STAGE PLATFORM_ONLY_FROZEN_ACCEL hold_fix=OFF"
 if {![compile_ultra -no_autoungroup]} {error "SoC compile failed"}
 check_macros
 foreach pattern {GTECH* SELECT_OP*} {
  if {[sizeof_collection [get_cells -hierarchical -quiet -filter "ref_name =~ $pattern"]] != 0} {error "unmapped $pattern"}
 }
 # Preserve the expensive optimized state before any accounting/report code.
 if {![write -format ddc -hierarchy -output $OUT/post_compile.ddc]} {error "post-compile checkpoint failed"}
 puts "SOC_POST_COMPILE_CHECKPOINT $OUT/post_compile.ddc"
 redirect -file $OUT/reports/area.rpt {report_area -hierarchy}
 # Every leaf counted exactly once, including all 100 macros. Classify the
 # fixed platform separately; all added NICE/arbiter/bridge/glue remains counted.
 set sums [dict create accelerator 0.0 CPU_TCM 0.0 shared_macros 0.0 added_shared_controller 0.0 added_interface_glue 0.0]
 set areas [dict create]
 set virtual_types [dict create]
 set virtual_counts [dict create {**logic_0**} 0 {**logic_1**} 0]
 foreach_in_collection cell [get_cells -hierarchical -filter {is_hierarchical == false}] {
  set name [get_object_name $cell];set ref [get_attribute $cell ref_name]
  if {![dict exists $areas $ref]} {
   set lib [get_lib_cells -of_objects $cell]
   set count [sizeof_collection $lib]
   if {$count == 0 && [lsearch -exact {{**logic_0**} {**logic_1**}} $ref] >= 0} {
    dict set areas $ref 0.0
    dict set virtual_types $ref 1
   } elseif {$count == 1} {
    dict set areas $ref [get_attribute $lib area]
   } else {error "unbound leaf $name $ref"}
  }
  if {[dict exists $virtual_types $ref]} {dict incr virtual_counts $ref;continue}
  set category added_interface_glue
  if {[string match u_kwt1_mmio/* $name]} {set category accelerator
  } elseif {[string match u_e203_subsys_top/* $name] && ![string match */u_e203_nice_core/* $name]} {set category CPU_TCM
  } elseif {[string match u_shmem/* $name]} {
   if {[string match RAMSP4096X16* $ref]} {set category shared_macros} else {set category added_shared_controller}
  }
  dict set sums $category [expr {[dict get $sums $category]+[dict get $areas $ref]}]
 }
 set fd [open $OUT/reports/area_ledger.tsv w]
 dict for {category area} $sums {puts $fd "$category\t$area"}
 close $fd
 set fd [open $OUT/reports/virtual_constants.tsv w]
 dict for {reference count} $virtual_counts {puts $fd "$reference\t$count\t0.0"}
 close $fd
 puts "SOC_VIRTUAL_CONSTANTS_ZERO_AREA $virtual_counts"
 redirect -file $OUT/reports/qor.rpt {report_qor}
 redirect -file $OUT/reports/check_design.rpt {check_design}
 redirect -file $OUT/reports/constraints.rpt {report_constraint -all_violators -verbose}
 change_names -rules verilog -hierarchy
 set fd [open $OUT/reports/macro_instances.txt w]
 foreach_in_collection macro [check_macros] {puts $fd [get_object_name $macro]}
 close $fd
 if {![write -format ddc -hierarchy -output $OUT/mapped.ddc]} {error "DDC write failed"}
 if {![write -format verilog -hierarchy -output $OUT/mapped.v]} {error "netlist write failed"}
 if {![write_sdc -nosplit $OUT/mapped.sdc]} {error "SDC write failed"}
 puts [host_python $PROJECT/flow/project.py attest]
 puts "SOC_FULL_DC_DONE"
} failure]} {puts stderr "SOC_FATAL $failure";puts stderr $::errorInfo;exit 1}
exit
