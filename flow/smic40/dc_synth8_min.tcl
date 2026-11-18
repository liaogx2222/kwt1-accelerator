# dc_synth8.tcl (compact) -- re-synthesis with the SRAM wrapper MAPPED.
# Fix vs dc_synth7: do NOT set_dont_touch the wrapper DESIGN (only the 20 macro
# instances).  dc_synth7 left GTECH_BUF/AND2/NOT/SELECT_OP inside macro_cell, so
# PT black-boxed them and the macro control paths wr/cen_n/gwen_n/wen_n were
# never timed.  The three lines at the end of dc_synth3.tcl that mapped the
# wrapper were removed in dc_synth7 under the mistaken belief they were dead.
# Also: the reset set_max_fanout block is gone -- DC rejected it (CMD-036) and
# compile_ultra builds the reset distribution by itself once the trailing plain
# `compile` is absent (PT: **async_default** max slack +1.66, 0 violating).
set_app_var sh_enable_page_mode false
set REPO    /path/to/project/server_signoff_20261106/keyword-transformer
set OUT     /path/to/project/out/dc_synth8
set WRAPPER $REPO/rtl/integration/smic40/kwt_tech_sram_4096x16.sv
set SDC     $REPO/flow/targets/smic40.server.sdc
set PDK     /path/to/project/pdk_extract/SMIC40/S40/smic
set SRAMDIR /path/to/project/lib_smic40
set TOP     kwt1_mmio
set MACREF  *RAMSP4096X16*
file mkdir $OUT
file mkdir $OUT/reports
define_design_lib WORK -path $OUT/WORK
set target_library [list \
  $PDK/SCC40NLL_VHSC40_HVT_V0.1/SCC40NLL_VHSC40_HVT_V0p1/liberty/1.1v/scc40nll_vhsc40_hvt_ss_v0p99_125c_basic.db \
  $PDK/SCC40NLL_VHSC40_LVT_V0.1/SCC40NLL_VHSC40_LVT_V0p1/liberty/1.1v/scc40nll_vhsc40_lvt_ss_v0p99_125c_basic.db \
  $PDK/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/liberty/1.1v/scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db \
  $SRAMDIR/RAMSP4096X16_ss_0p99v_0p99v_125c.db]
set link_library   [concat "*" $target_library]
set search_path    [concat [list "." "$REPO/rtl/v2/generated" "$REPO/rtl/v2" "$REPO/rtl/micro"] $search_path]
set rtl_files [list \
    $WRAPPER \
    $REPO/rtl/micro/mul_pipe.sv \
    $REPO/rtl/micro/rne_pipe.sv \
    $REPO/rtl/v2/kwt_sram_sp.sv \
    $REPO/rtl/v2/kwt_mac8x8.sv \
    $REPO/rtl/v2/kwt_iterative.sv \
    $REPO/rtl/v2/kwt_math.sv \
    $REPO/rtl/v2/kwt_packet_loader.sv \
    $REPO/rtl/v2/kwt_layer_banked.sv \
    $REPO/rtl/v2/kwt1_accel.sv \
    $REPO/rtl/v2/kwt1_mmio.sv]
foreach f $rtl_files { if {![file isfile $f]} { error "RTL source not found: $f" } }
analyze -format sverilog -define KWT_TECH_SRAM -lib WORK $rtl_files
elaborate $TOP -lib WORK
current_design $TOP
link
set macro_cells [get_cells -hierarchical -filter "ref_name =~ $MACREF" -quiet]
set macro_count [sizeof_collection $macro_cells]
puts "KWT_MACRO_INSTANCES $macro_count"
if {$macro_count != 20} { error "expected exactly 20 SRAM macro instances, found $macro_count" }
set_dont_touch $macro_cells
read_sdc $SDC
redirect -file $OUT/reports/check_design.rpt { check_design -summary }
compile_ultra -no_autoungroup
set n_gtech [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ GTECH*" -quiet]]
set n_sel   [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ SELECT_OP*" -quiet]]
puts "KWT_GTECH_CELLS $n_gtech"
puts "KWT_SELECT_OP_CELLS $n_sel"
if {$n_gtech != 0 || $n_sel != 0} {
    error "unmapped generic logic survived synthesis ($n_gtech GTECH + $n_sel SELECT_OP); netlist is not signoff grade"
}
redirect -file $OUT/reports/area.rpt          { report_area -hierarchy }
redirect -file $OUT/reports/cell.rpt          { report_cell -nosplit }
redirect -file $OUT/reports/timing_setup.rpt  { report_timing -delay_type max -max_paths 20 -nworst 1 -nosplit }
redirect -file $OUT/reports/timing_hold.rpt   { report_timing -delay_type min -max_paths 20 -nworst 1 -nosplit }
redirect -file $OUT/reports/constraints.rpt   { report_constraint -all_violators -verbose }
change_names -rules verilog -hierarchy
write -format ddc     -hierarchy -output $OUT/mapped.ddc
write -format verilog -hierarchy -output $OUT/mapped.v
if {[catch {write_sdc -nosplit -output $OUT/mapped.sdc} msg]} {
    puts "write_sdc -output unavailable ($msg); retrying positional form"
    write_sdc -nosplit $OUT/mapped.sdc
}
set mapped_macro [get_cells -hierarchical -filter "ref_name =~ $MACREF" -quiet]
puts "KWT_MAPPED_MACRO_INSTANCES [sizeof_collection $mapped_macro]"
if {[sizeof_collection $mapped_macro] != 20} { error "mapped netlist lost SRAM macro blackboxes" }
puts "KWT_DC_SYNTH8_FINISHED"
exit
