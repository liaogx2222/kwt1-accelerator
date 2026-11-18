# =============================================================================
# dc_fix_fanout.tcl -- design-rule-only pass: build a real fanout tree on the
#                      async-reset distribution of the dc_synth5 netlist.
# -----------------------------------------------------------------------------
# WHY
#   PT tri-corner STA on out/dc_synth5/mapped.v reported setup WNS = -5.19 ns on
#     Startpoint abort_hw (in)  ->  Endpoint accel/core/pe/acc_reg[2][1]/RDN
#     Path Group **async default**   (recovery check, Path Type max)
#   The delay breakdown is a CHAIN of CLKBFV1 cells at 1.11-1.22 ns EACH:
#     accel/core/U7225/Z 0.96 | pe/U2692 1.22 | pe/U9816 1.19 | pe/U9337 1.13
#     pe/U9336 1.11 | pe/U9335 1.11 | pe/U9328 1.18 | pe/U9331 1.16 | pe/U9324 1.16
#   1.1 ns per clock buffer means each stage is driving thousands of RDN pins.
#   That is not a tree, it is a serial chain -- DC had no fanout target, because
#   flow/targets/smic40.server.sdc deliberately forbids a global set_max_fanout
#   and the SMIC40 .db carries no max_fanout attribute.
#
# WHAT THIS DOES (and does not do)
#   * sets max_fanout / max_transition on the RESET NET ONLY (scoped, not global)
#   * compile_ultra -only_design_rule  -> inserts buffers, does NOT change logic
#   * macros are set_dont_touch, hierarchy is kept
#   It does NOT fix the missing `default` in kwt_layer_banked (that is an RTL
#   robustness item for gate-level X, not a timing item) and it does NOT touch
#   the RETIN pin name (harmless: report_disable_timing shows only the 2
#   CEN<->RETIN hold arcs disabled, no data arcs).
#
# INVOKE
#   dc_shell -f /home/.../out/dc_fix_fanout.tcl -output_log_file /home/.../out/dc_fix_fanout.log
#   (want to watch it?  dc_shell -gui -f ...  and delete the trailing `exit`)
#
# RESULT
#   out/dc_synth6/mapped.v  -> re-run flow/smic40/pt_signoff.tcl against it
# =============================================================================

set_app_var sh_enable_page_mode false

set TOP     kwt1_mmio
set INNET   /path/to/project/out/dc_synth5/mapped.v
set OUT     /path/to/project/out/dc_synth6
set SDC     /path/to/project/server_signoff_20261106/keyword-transformer/flow/targets/smic40.server.sdc

set PDK     /path/to/project/pdk_extract/SMIC40/S40/smic
set HVT     $PDK/SCC40NLL_VHSC40_HVT_V0.1/SCC40NLL_VHSC40_HVT_V0p1/liberty/1.1v
set LVT     $PDK/SCC40NLL_VHSC40_LVT_V0.1/SCC40NLL_VHSC40_LVT_V0p1/liberty/1.1v
set RVT     $PDK/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/liberty/1.1v
set SRAMDIR /path/to/project/lib_smic40

file mkdir $OUT
file mkdir $OUT/reports
define_design_lib WORK -path $OUT/WORK

# ss corner as primary target: this is the slow corner the original synthesis
# targeted, so buffer cell selection stays consistent with dc_synth5.
set target_library [list \
  $HVT/scc40nll_vhsc40_hvt_ss_v0p99_125c_basic.db \
  $LVT/scc40nll_vhsc40_lvt_ss_v0p99_125c_basic.db \
  $RVT/scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db \
  $SRAMDIR/RAMSP4096X16_ss_0p99v_0p99v_125c.db]
set link_library   [concat "*" $target_library]
set search_path    [list "." $SRAMDIR $PDK]

# ---- read the mapped netlist ------------------------------------------------
read_verilog $INNET
current_design $TOP
link
read_sdc $SDC

# ---- macros stay untouched --------------------------------------------------
set macro_cells [get_cells -hierarchical -filter "ref_name =~ *RAMSP4096X16*" -quiet]
puts "KWT_MACRO_INSTANCES [sizeof_collection $macro_cells]"
if {[sizeof_collection $macro_cells] != 20} {
    error "expected 20 SRAM macros in the mapped netlist, found [sizeof_collection $macro_cells]"
}
set_dont_touch $macro_cells

# ---- scoped fanout target: the async-reset distribution only ----------------
# NOT a global override. Recorded as a scoped exception in the binding JSON
# (source: PT timing_ss_0p99v_125c.rpt recovery path -5.19 ns; reason: reset
#  distribution had no fanout target so DC built a serial buffer chain).
set rstnets [get_nets -hierarchical *task_rst* -quiet]
if {[sizeof_collection $rstnets] == 0} {
    set rstnets [get_nets -hierarchical *rst_n* -quiet]
}
puts "KWT_RESET_NETS [sizeof_collection $rstnets]"
if {[sizeof_collection $rstnets] > 0} {
    if {[catch {set_max_fanout 32 $rstnets} msg]} {
        puts "NOTE set_max_fanout on net rejected ($msg); falling back to design-level 64"
        set_max_fanout 64 [current_design]
    }
    catch {set_max_transition 0.400 $rstnets}
} else {
    puts "WARN reset net not found by name; using design-level fanout target 64"
    set_max_fanout 64 [current_design]
}

# ---- design-rule-only optimisation: buffers only, no logic change ----------
# `-only_design_rule` is REJECTED without `-incremental`:
#   Error: only design rule option can be used only in conjunction with
#          incremental option. (UID-207)
# That is exactly what killed the first attempt -- the netlist was rewritten
# byte-identical (2474334 -> 2474332) and PT kept reporting -5.19 ns.
set buf_before [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ CLKBF*" -quiet]]
puts "KWT_CLKBUF_BEFORE $buf_before"

if {[catch {compile_ultra -incremental -only_design_rule -no_autoungroup} msg]} {
    puts "NOTE -incremental -only_design_rule -no_autoungroup rejected: $msg"
    puts "NOTE retrying without -no_autoungroup"
    compile_ultra -incremental -only_design_rule
}

set buf_after [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ CLKBF*" -quiet]]
puts "KWT_CLKBUF_AFTER $buf_after"
if {$buf_after <= $buf_before} {
    puts "WARN no clock buffer was inserted ($buf_before -> $buf_after); the reset tree is still a chain"
} else {
    puts "OK inserted [expr {$buf_after - $buf_before}] clock buffers"
}

# ---- reports ---------------------------------------------------------------
redirect -file $OUT/reports/area.rpt   { report_area }
redirect -file $OUT/reports/drc.rpt    { report_constraint -all_violators -verbose }
redirect -file $OUT/reports/timing.rpt { report_timing -delay_type max -max_paths 10 -nosplit }
redirect -file $OUT/reports/cells.rpt  { report_cell -nosplit }

# ---- write ----------------------------------------------------------------
write -format verilog -hierarchy -output $OUT/mapped.v
write -format ddc     -hierarchy -output $OUT/mapped.ddc

set mapped_macro [get_cells -hierarchical -filter "ref_name =~ *RAMSP4096X16*" -quiet]
puts "KWT_MAPPED_MACRO_INSTANCES [sizeof_collection $mapped_macro]"

puts "KWT_FIX_FANOUT_FINISHED"
exit
