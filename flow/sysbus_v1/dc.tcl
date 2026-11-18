if {[catch {
 source [file join [pwd] flow common.tcl]
 puts [host_python $PROJECT/flow/project.py check]
 set OUT $PROJECT/build/dc
 if {[file exists $OUT]} {error "preserve mapped outputs"}
 file mkdir $OUT/reports
 define_design_lib WORK -path $OUT/WORK
 set_app_var alib_library_analysis_path $OUT/alib
 file mkdir $OUT/alib
 set_host_options -max_cores 4
 set maximum [libs tt]
 set_app_var target_library $maximum
 set_app_var link_library [concat * $maximum]
 # Prefix EVERY cached design before analyzing new integration RTL. This
 # prevents stale cached subsystem wrappers from silently satisfying a link.
 read_ddc $PROJECT/cache/cpu_mapped.ddc
 current_design e203_subsys_top
 set old_core [get_cells u_e203_subsys_main/u_e203_cpu_top]
 if {[sizeof_collection $old_core] != 1} {error "cached CPU core boundary missing"}
 set core_reference [get_attribute $old_core ref_name]
 set cached_names [get_object_name [get_designs *]]
 foreach name $cached_names {rename_design $name cpu_cache_$name}
 set frozen_core cpu_cache_$core_reference
 set_dont_touch [get_designs $frozen_core] true
 read_ddc $PROJECT/cache/accelerator_mapped.ddc
 set accel_names [get_object_name [get_designs *kwt*]]
 # Accelerator names are disjoint from cpu_cache_ names; prefix all uncached
 # designs, including mathematical helper modules, not just the top.
 set uncached {}
 foreach_in_collection design [get_designs *] {
  set name [get_object_name $design]
  if {![string match cpu_cache_* $name]} {lappend uncached $name}
 }
 foreach name $uncached {rename_design $name accel_cache_$name}
 set_dont_touch [get_designs accel_cache_kwt1_mmio] true
 set fd [open $PROJECT/flow/includes.txt r]
 foreach d [split [read $fd] \n] {if {[string trim $d] ne ""} {lappend search_path $PROJECT/[string trim $d]}}
 close $fd
 set fd [open $PROJECT/flow/soc_sources.txt r];set files {}
 foreach name [split [read $fd] \n] {
  set name [string trim $name]
  # The cached core already contains the original CPU, NICE and TCMs.
  if {$name ne "" && [file tail $name] ne "e203_cpu_top.v"} {lappend files $PROJECT/$name}
 }
 close $fd
 if {![analyze -format sverilog -define {FPGA_SOURCE SYNTHESIS DISABLE_SV_ASSERTION} -lib WORK $files]} {error "System Bus RTL analysis failed"}
 # Loaded DDCs retain original-reference aliases. New HDL names prevent cached
 # subsystem wrappers from winning elaboration even after rename_design.
 # SYSBUS_PORT_CONTRACT is expanded by the exporter, not a runtime dependency.
 SYSBUS_PORT_CONTRACT
 foreach wrapper {sysbus_e203_subsys_main sysbus_e203_subsys_top} {
  elaborate $wrapper -lib WORK
  current_design $wrapper
  foreach {port width} {load_cmd_valid 1 load_cmd_ready 1 load_cmd_addr 32 load_cmd_wdata 32 load_rsp_valid 1 load_rsp_ready 1 load_rsp_rdata 32 load_rsp_error 1} {
   sysbus_require_port $port $width
  }
  puts "SYSBUS_NEW_WRAPPER_VERIFIED $wrapper"
 }
 elaborate $TOP -lib WORK
 current_design $TOP
 set new_top [get_cells u_e203_subsys_top]
 if {[get_attribute $new_top ref_name] ne "sysbus_e203_subsys_top"} {error "stale cached subsystem top bound"}
 set new_main [get_cells u_e203_subsys_top/u_e203_subsys_main]
 if {[get_attribute $new_main ref_name] ne "sysbus_e203_subsys_main"} {error "stale cached subsystem main bound"}
 set core [get_cells u_e203_subsys_top/u_e203_subsys_main/u_e203_cpu_top]
 if {[sizeof_collection $core] != 1} {error "new core instance missing"}
 change_link $core $frozen_core
 change_link [get_cells u_kwt1_mmio] accel_cache_kwt1_mmio
 set_app_var target_library $maximum
 set_app_var link_library [concat * $maximum]
 current_design $TOP
 if {![link]} {error "System Bus late cache link failed"}
 set_dont_touch $core true
 set_boundary_optimization $core false
 set_dont_touch [get_cells u_kwt1_mmio] true
 set_boundary_optimization [get_cells u_kwt1_mmio] false
 set macros [check_macros];set_dont_touch $macros true
 set clocks [all_clocks]
 if {[sizeof_collection $clocks] > 0} {remove_clock -all}
 read_soc_constraints
 if {[sizeof_collection [all_clocks]] != 3} {error "expected three reference clocks"}
 puts "SYSBUS_REUSED_CORE $frozen_core"
 puts "SYSBUS_ROUTE original_e203_subsys_mems width=32 private_loader=0 SRAM_backend_arbiter=0"
 if {![write -format ddc -hierarchy -output $OUT/linked_before_compile.ddc]} {error "linked checkpoint failed"}
 puts "SYSBUS_INCREMENTAL_MAPPING hold_fix=OFF frozen_core_and_accelerator=1"
 if {![compile_ultra -no_autoungroup]} {error "System Bus mapping failed"}
 check_macros
 if {![write -format ddc -hierarchy -output $OUT/post_compile.ddc]} {error "postcompile checkpoint failed"}
 # SYSBUS_ACCOUNTING_AND_EXPORT is replaced with the proven mapped-leaf ledger.
 SYSBUS_ACCOUNTING_AND_EXPORT
} failure]} {puts stderr "SOC_FATAL $failure";puts stderr $::errorInfo;exit 1}
exit
