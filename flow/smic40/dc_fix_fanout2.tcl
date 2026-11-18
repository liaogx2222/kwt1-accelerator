# =============================================================================
# dc_fix_fanout2.tcl -- build a real fanout TREE on the async-reset distribution
#                       of the dc_synth7 netlist.  DRC-only, no logic change.
# -----------------------------------------------------------------------------
# WHY THE PREVIOUS ATTEMPT DID NOTHING (two independent reasons, both proven)
#
#   [A] set_max_fanout was given a NET.  DC T-2022.03 accepts only
#       design / port / PIN objects:
#           Error: Value for list 'object_list' must have 1 elements. (CMD-036)
#       That is the pair of errors at dc_synth7.log lines 624 and 629 -- both
#       set_max_fanout and set_max_transition were rejected, so at compile time
#       there was NO violated design rule and the design-rule fixer had nothing
#       to fix.  dc_synth6 (24743344 -> 24743332 bytes) is the same story.
#
#   [B] the fallback `set_max_fanout 64 [current_design]` is useless here:
#       on a design object it applies to the design's PORTS, not to internal
#       nets, so the reset distribution inside kwt_layer_banked stays free.
#
#   Also, constraining only `task_rst_n` itself would not be enough: that net
#   drives just the first buffer of the existing chain.  The violation lives on
#   EVERY stage of the chain (7 x CLKBF at 1.11-1.22 ns each).  So the target
#   has to be the whole fanout CONE of the reset, obtained with all_fanout.
#
# WHAT THIS DOES
#   1. read out/dc_synth7/mapped.v (the 0.963336 mm2 netlist), link, read SDC
#   2. set_dont_touch the 20 SRAM macros
#   3. find the reset net, take its DRIVER PIN, expand the whole fanout cone
#   4. set_max_fanout 32 / set_max_transition 0.400 on every pin of that cone
#      (scoped: nothing outside the reset distribution is touched)
#   5. compile_ultra -incremental -only_design_rule  -> buffers only
#   6. measure cells before/after so "did it actually do anything" is provable
#   7. write out/dc_synth8/mapped.v
#
# INVOKE
#   dc_shell -f /home/.../out/dc_fix_fanout2.tcl \
#            -output_log_file /home/.../out/dc_fix_fanout2.log
#   (want to watch it?  dc_shell -gui -f ...  and delete the trailing `exit`)
#
# SUCCESS LOOKS LIKE
#   KWT_RESET_DRIVER 1
#   KWT_RESET_CONE   <tens of thousands>
#   KWT_CELLS_AFTER  >  KWT_CELLS_BEFORE   (by ~1-3k buffers)
# =============================================================================

set_app_var sh_enable_page_mode false

set TOP     kwt1_mmio
set INNET   /path/to/project/out/dc_synth7/mapped.v
set OUT     /path/to/project/out/dc_synth8
set SDC     /path/to/project/server_signoff_20261106/keyword-transformer/flow/targets/smic40.server.sdc

set PDK     /path/to/project/pdk_extract/SMIC40/S40/smic
set HVT     $PDK/SCC40NLL_VHSC40_HVT_V0.1/SCC40NLL_VHSC40_HVT_V0p1/liberty/1.1v
set LVT     $PDK/SCC40NLL_VHSC40_LVT_V0.1/SCC40NLL_VHSC40_LVT_V0p1/liberty/1.1v
set RVT     $PDK/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/liberty/1.1v
set SRAMDIR /path/to/project/lib_smic40

if {![file isfile $INNET]} { error "netlist not found: $INNET" }

file mkdir $OUT
file mkdir $OUT/reports
define_design_lib WORK -path $OUT/WORK

# ss corner: same library set the netlist was mapped against, so the buffer
# cells chosen by the DRC fixer are consistent with dc_synth7.
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

# ---- locate the reset distribution -----------------------------------------
set rstnets [get_nets -hierarchical *task_rst* -quiet]
if {[sizeof_collection $rstnets] == 0} {
    puts "NOTE *task_rst* matched nothing; retrying with *rst_n*"
    set rstnets [get_nets -hierarchical *rst_n* -quiet]
}
puts "KWT_RESET_NETS [sizeof_collection $rstnets]"
if {[sizeof_collection $rstnets] == 0} {
    error "reset net not found by name; refusing to run without the fanout fix"
}

# driver pin of the reset net -- set_max_fanout needs a PIN, not a net
set rst_drv [get_pins -of_objects $rstnets -filter "direction == out" -quiet]
puts "KWT_RESET_DRIVER [sizeof_collection $rst_drv]"
if {[sizeof_collection $rst_drv] == 0} {
    error "no driver pin found on the reset net (set_max_fanout needs a pin object)"
}

# whole fanout cone: the violation is on EVERY stage of the existing buffer
# chain, not just on the first net, so the whole cone has to carry the rule.
set rst_cone [all_fanout -from $rst_drv -flat]
puts "KWT_RESET_CONE [sizeof_collection $rst_cone]"
if {[sizeof_collection $rst_cone] < 1000} {
    puts "WARN reset cone is unexpectedly small -- the rule may not reach the flops"
}

# ---- scoped design rule: reset distribution only ---------------------------
# Recorded as a scoped exception in the binding JSON
#   source: pt_signoff/timing_ss_0p99v_125c.rpt recovery path, WNS -5.19 ns
#   reason: SMIC40 .db carries no max_fanout on the async reset pin, and the
#           project SDC forbids a global override, so DC had no target at all.
set_max_fanout 32 $rst_cone
if {[catch {set_max_transition 0.400 $rst_cone} msg]} {
    puts "NOTE set_max_transition rejected: $msg"
}

# prove the rule is live: count the violated pins before compiling
redirect -file $OUT/reports/drc_before.rpt {
    report_constraint -all_violators -verbose
}

set cells_before [sizeof_collection [get_cells -hierarchical -quiet]]
puts "KWT_CELLS_BEFORE $cells_before"

# ---- design-rule-only optimisation ----------------------------------------
# -only_design_rule + -no_autoungroup is rejected (UID-207, misleading message:
# the offender is -no_autoungroup, not the missing -incremental), so fall back.
if {[catch {compile_ultra -incremental -only_design_rule -no_autoungroup} msg]} {
    puts "NOTE -no_autoungroup rejected ($msg); retrying without it"
    compile_ultra -incremental -only_design_rule
}

set cells_after [sizeof_collection [get_cells -hierarchical -quiet]]
puts "KWT_CELLS_AFTER $cells_after"
puts "KWT_BUFFERS_INSERTED [expr {$cells_after - $cells_before}]"
if {$cells_after <= $cells_before} {
    puts "WARN nothing was inserted; the reset distribution is still a chain"
} else {
    puts "OK reset tree built, [expr {$cells_after - $cells_before}] cells added"
}

# ---- reports ---------------------------------------------------------------
redirect -file $OUT/reports/area.rpt   { report_area }
redirect -file $OUT/reports/drc_after.rpt { report_constraint -all_violators -verbose }
redirect -file $OUT/reports/timing.rpt { report_timing -delay_type max -max_paths 20 -nworst 1 -nosplit }

# ---- write ----------------------------------------------------------------
write -format verilog -hierarchy -output $OUT/mapped.v
write -format ddc     -hierarchy -output $OUT/mapped.ddc
if {[catch {write_sdc -nosplit -output $OUT/mapped.sdc} msg]} {
    write_sdc -nosplit $OUT/mapped.sdc
}

set mapped_macro [get_cells -hierarchical -filter "ref_name =~ *RAMSP4096X16*" -quiet]
puts "KWT_MAPPED_MACRO_INSTANCES [sizeof_collection $mapped_macro]"
if {[sizeof_collection $mapped_macro] != 20} {
    error "mapped netlist lost SRAM macro blackboxes"
}

puts "KWT_FIX_FANOUT2_FINISHED"
exit
