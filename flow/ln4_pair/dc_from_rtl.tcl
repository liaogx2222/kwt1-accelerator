# Full-source paired DC body. The evidence-gated launcher must generate inputs.tcl
# in a NEW run and bind every source/library/constraint hash before invoking this.
# inputs.tcl sets TOP, OUT, RTL_FILES, INCLUDE_DIRS, TARGET_LIBS, REFERENCE_SDC.
if {[catch {
 source [file join [file dirname [info script]] inputs.tcl]
 foreach variable {TOP OUT RTL_FILES INCLUDE_DIRS TARGET_LIBS REFERENCE_SDC} {
  if {![info exists $variable]} {error "LN4_DC_MISSING_INPUT $variable"}
 }
 if {[file exists $OUT]} {error "LN4_DC_PRESERVE_EXISTING_OUTPUT $OUT"}
 foreach path [concat $RTL_FILES $TARGET_LIBS [list $REFERENCE_SDC]] {
  if {![file isfile $path]} {error "LN4_DC_INPUT_MISSING $path"}
 }
 if {[llength $RTL_FILES] != 151} {error "LN4_DC_EXPECT_151_SOURCES"}
 if {[llength $TARGET_LIBS] != 4} {error "LN4_DC_EXPECT_3_TT_STD_AND_1_SRAM_LIBRARY"}
 file mkdir $OUT/reports
 file mkdir $OUT/alib
 define_design_lib WORK -path $OUT/WORK
 set_app_var alib_library_analysis_path $OUT/alib
 set_app_var search_path [concat $INCLUDE_DIRS [get_app_var search_path]]
 set_app_var target_library $TARGET_LIBS
 set_app_var link_library [concat * $TARGET_LIBS]
 set_host_options -max_cores 4
 set_svf $OUT/compile.svf
 # KWT_SIM is intentionally absent: verification shadow state is not hardware.
 # Both variants are elaborated from their complete source lists; no old DDC.
 puts "LN4_DC_STAGE ANALYZE_FULL_SOURCE"
 if {![analyze -format sverilog -define {FPGA_SOURCE SYNTHESIS DISABLE_SV_ASSERTION KWT_TECH_SRAM} -lib WORK $RTL_FILES]} {
  error "LN4_DC_ANALYZE_FAILED"
 }
 elaborate $TOP -lib WORK
 current_design $TOP
 if {![link]} {error "LN4_DC_LINK_FAILED"}
 if {[sizeof_collection [get_lib_pins -quiet */RAMSP4096X16/RET1N]] != 1} {
  error "LN4_DC_REAL_RET1N_LIBRARY_VIEW_NOT_ONE"
 }
 set macros [get_cells -hierarchical -quiet -filter {ref_name =~ RAMSP4096X16*}]
 if {[sizeof_collection $macros] != 100} {error "LN4_DC_ELABORATED_MACROS_NOT_100"}
 set_dont_touch $macros true
 # Apply the preserved server constraints verbatim. No clock grouping, reset
 # exception, uncertainty relaxation, or substitute clock period is added here.
 source $REFERENCE_SDC
 if {[sizeof_collection [all_clocks]] != 3} {error "LN4_DC_REFERENCE_CLOCKS_NOT_THREE"}
 redirect -file $OUT/reports/precompile_check_design.rpt {check_design}
 if {![write -format ddc -hierarchy -output $OUT/linked_before_compile.ddc]} {
  error "LN4_DC_LINKED_CHECKPOINT_FAILED"
 }
 puts "LN4_DC_STAGE COMPILE_FULL_SOURCE"
 if {![compile_ultra -no_autoungroup]} {error "LN4_DC_COMPILE_FAILED"}
 if {![write -format ddc -hierarchy -output $OUT/post_compile.ddc]} {
  error "LN4_DC_POST_COMPILE_CHECKPOINT_FAILED"
 }
 set macros [get_cells -hierarchical -quiet -filter {ref_name =~ RAMSP4096X16*}]
 if {[sizeof_collection $macros] != 100} {error "LN4_DC_MAPPED_MACROS_NOT_100"}
 foreach pattern {GTECH* SELECT_OP*} {
  if {[sizeof_collection [get_cells -hierarchical -quiet -filter "ref_name =~ $pattern"]] != 0} {
   error "LN4_DC_UNMAPPED_CELLS $pattern"
  }
 }
 redirect -file $OUT/reports/area.rpt {report_area -hierarchy}
 redirect -file $OUT/reports/qor.rpt {report_qor}
 redirect -file $OUT/reports/check_design.rpt {check_design}
 redirect -file $OUT/reports/setup.rpt {report_timing -significant_digits 6 -delay_type max -max_paths 50 -nosplit}
 redirect -file $OUT/reports/hold.rpt {report_timing -significant_digits 6 -delay_type min -max_paths 50 -nosplit}
 redirect -file $OUT/reports/constraints.rpt {report_constraint -all_violators -verbose}
 redirect -file $OUT/reports/design.rpt {report_design}
 # Attribute every mapped physical leaf once using the bound library area.
 # Virtual logic constants have no library cell and are explicitly zero area.
 set sums [dict create private_SRAM 0.0 shared_SRAM 0.0 ITCM 0.0 DTCM 0.0 accelerator_logic 0.0 CPU_and_platform_logic 0.0 shared_controller 0.0 interface_glue 0.0]
 set fd [open $OUT/reports/leaf_area.tsv w]
 set mf [open $OUT/reports/macro_inventory.tsv w]
 foreach_in_collection cell [get_cells -hierarchical -filter {is_hierarchical == false}] {
  set name [get_object_name $cell]
  set ref [get_attribute $cell ref_name]
  set lib [get_lib_cells -of_objects $cell]
  set count [sizeof_collection $lib]
  if {$count == 0 && [lsearch -exact {{**logic_0**} {**logic_1**}} $ref] >= 0} {
   puts $fd "$name\t$ref\tvirtual_constant\t0.0"
   continue
  }
  if {$count != 1} {error "LN4_DC_UNBOUND_MAPPED_LEAF $name $ref"}
  set area [get_attribute $lib area]
  set category interface_glue
  if {[string match RAMSP4096X16* $ref]} {
   if {[string match u_kwt1_mmio/* $name]} {set category private_SRAM
   } elseif {[string match u_shmem/* $name]} {set category shared_SRAM
   } elseif {[string match *itcm* $name]} {set category ITCM
   } elseif {[string match *dtcm* $name]} {set category DTCM
   } else {error "LN4_DC_UNKNOWN_SRAM_REGION $name"}
   puts $mf "$category\t$name\t$ref\t$area"
  } elseif {[string match u_kwt1_mmio/* $name]} {set category accelerator_logic
  } elseif {[string match u_e203_subsys_top/* $name]} {set category CPU_and_platform_logic
  } elseif {[string match u_shmem/* $name]} {set category shared_controller}
  dict set sums $category [expr {[dict get $sums $category]+$area}]
  puts $fd "$name\t$ref\t$category\t$area"
 }
 close $fd
 close $mf
 set fd [open $OUT/reports/area_ledger.tsv w]
 dict for {category area} $sums {puts $fd "$category\t$area"}
 close $fd
 # Inventory each physical macro once; verify its hierarchy against 20/64/8/8
 # in the launcher before accepting the result, not from textual module counts.
 set fd [open $OUT/reports/macro_instances.txt w]
 foreach_in_collection macro $macros {puts $fd [get_object_name $macro]}
 close $fd
 change_names -rules verilog -hierarchy
 if {![write -format ddc -hierarchy -output $OUT/mapped.ddc]} {error "LN4_DC_DDC_EXPORT_FAILED"}
 if {![write -format verilog -hierarchy -output $OUT/mapped.v]} {error "LN4_DC_NETLIST_EXPORT_FAILED"}
 if {![write_sdc -nosplit $OUT/mapped.sdc]} {error "LN4_DC_SDC_EXPORT_FAILED"}
 set_svf -off
 puts "LN4_FULL_SOURCE_DC_DONE"
} failure]} {
 puts stderr "LN4_DC_FATAL $failure"
 puts stderr $::errorInfo
 exit 1
}
exit
