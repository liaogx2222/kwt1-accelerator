# =============================================================================
# dc_synth7.tcl -- full re-synthesis of kwt1_mmio with a real reset fanout tree
# -----------------------------------------------------------------------------
# WHY THIS RUN EXISTS  (supersedes dc_synth5 / dc_synth3.tcl)
#
#   [1] RESET TREE -- the blocker.
#       PT on dc_synth5/mapped.v reported setup WNS = -5.19 ns:
#         Startpoint abort_hw (in) -> Endpoint accel/core/pe/acc_reg[2][1]/RDN
#         Path Group **async default**   (recovery check, Path Type max)
#       Delay breakdown was a CASCADE of clock buffers at 1.11-1.22 ns EACH
#       (U7225 0.96, U2692 1.22, U9816 1.19, U9337 1.13, U9336 1.11,
#        U9335 1.11, U9328 1.18, U9331 1.16, U9324 1.16) -> 11.16 ns arrival
#       against 5.96 ns required.  Cause: dc_synth3.tcl contains no
#       set_max_fanout anywhere, and flow/targets/smic40.server.sdc
#       deliberately forbids a global override, so DC had no fanout target for
#       task_rst_n and never built a tree.
#       Fix: SCOPED fanout target on the reset net only, applied BEFORE
#       compile_ultra so the tree is built during mapping.
#       (A post-mapped DRC pass cannot do this: compile_ultra -only_design_rule
#        answers "UID-207 ... only in conjunction with incremental option" and
#        then inserts zero buffers -- measured on dc_synth6, 24743344 ->
#        24743332 bytes, i.e. byte-identical apart from the timestamp.)
#
#   [2] FSM DEFAULT.
#       kwt_layer_banked case(state) had no default, so the ~186 unused 8-bit
#       encodings were don't-care and an X state could never recover.  Fixed in
#       RTL; this run picks it up.
#
#   [3] Dead code removed.  dc_synth3.tcl ended compile_ultra with
#         current_design kwt_tech_sram_4096x16 / compile -map_effort high /
#         current_design kwt1_mmio
#       which is a no-op (the wrapper is set_dont_touch) and is gone.
#
# All paths are LITERAL ABSOLUTE PATHS on purpose: with several terminal
# windows in use the env bindings are frequently not sourced, and an unset
# $VAR expands to nothing and silently runs the wrong thing.
#
# INVOKE  (from any directory)
#   dc_shell -f /home/.../out/dc_synth7.tcl -output_log_file /home/.../out/dc_synth7.log
#   want to watch?  dc_shell -gui -f ...   and delete the trailing `exit`
# =============================================================================

set_app_var sh_enable_page_mode false

set REPO    /home/2026contest/server6/s6_43usr/Desktop/project/server_signoff_20261106/keyword-transformer
set OUT     /home/2026contest/server6/s6_43usr/Desktop/project/out/dc_synth7
set WRAPPER $REPO/rtl/integration/smic40/kwt_tech_sram_4096x16.sv
set SDC     $REPO/flow/targets/smic40.server.sdc
set PDK     /home/2026contest/server6/s6_43usr/Desktop/project/pdk_extract/SMIC40/S40/smic
set SRAMDIR /home/2026contest/server6/s6_43usr/Desktop/project/lib_smic40
set TOP     kwt1_mmio
set MACREF  *RAMSP4096X16*

file mkdir $OUT
file mkdir $OUT/reports
define_design_lib WORK -path $OUT/WORK

# ---- primary corner = ss_0p99v_125c, identical to dc_synth5 ----------------
set target_library [list \
  $PDK/SCC40NLL_VHSC40_HVT_V0.1/SCC40NLL_VHSC40_HVT_V0p1/liberty/1.1v/scc40nll_vhsc40_hvt_ss_v0p99_125c_basic.db \
  $PDK/SCC40NLL_VHSC40_LVT_V0.1/SCC40NLL_VHSC40_LVT_V0p1/liberty/1.1v/scc40nll_vhsc40_lvt_ss_v0p99_125c_basic.db \
  $PDK/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/liberty/1.1v/scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db \
  $SRAMDIR/RAMSP4096X16_ss_0p99v_0p99v_125c.db]
set link_library   [concat "*" $target_library]
set search_path    [concat [list "." "$REPO/rtl/v2/generated" "$REPO/rtl/v2" "$REPO/rtl/micro"] $search_path]

# ---- read ONLY production RTL + the real macro wrapper ---------------------
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

# ---- blackbox integrity guard ---------------------------------------------
set macro_cells [get_cells -hierarchical -filter "ref_name =~ $MACREF" -quiet]
set macro_count [sizeof_collection $macro_cells]
puts "KWT_MACRO_INSTANCES $macro_count"
if {$macro_count != 20} {
    error "expected exactly 20 SRAM macro instances, found $macro_count"
}
set_dont_touch $macro_cells
if {[sizeof_collection [get_designs kwt_tech_sram_4096x16 -quiet]] > 0} {
    set_dont_touch [get_designs kwt_tech_sram_4096x16]
}

# ---- constraints ----------------------------------------------------------
read_sdc $SDC

# ---- [FIX 1] scoped reset fanout target -----------------------------------
# task_rst_n = rst_n && !abort feeds the async reset of every flop in
# kwt_layer_banked (~20k: probabilities, row_data, codes, gamma/beta, residual,
# multipliers, biases, ...).  With no fanout target DC left it on a serial
# buffer chain.  Constrain the net only -- NOT a global override.
set rstnets [get_nets -hierarchical *task_rst* -quiet]
if {[sizeof_collection $rstnets] == 0} {
    set rstnets [get_nets -hierarchical *rst_n* -quiet]
}
puts "KWT_RESET_NETS [sizeof_collection $rstnets]"
if {[sizeof_collection $rstnets] == 0} {
    error "reset net not found by name; refusing to run without the fanout fix"
}
set_max_fanout 32 $rstnets
catch {set_max_transition 0.400 $rstnets}

redirect -file $OUT/reports/check_design.rpt { check_design -summary }
redirect -file $OUT/reports/constraints_pre.rpt { report_constraint -all_violators -verbose }

# ---- synthesis ------------------------------------------------------------
compile_ultra -no_autoungroup

# ---- reports --------------------------------------------------------------
redirect -file $OUT/reports/area.rpt          { report_area -hierarchy }
redirect -file $OUT/reports/cell.rpt          { report_cell -nosplit }
redirect -file $OUT/reports/timing_setup.rpt  { report_timing -delay_type max -max_paths 20 -nworst 1 -nosplit }
redirect -file $OUT/reports/timing_hold.rpt   { report_timing -delay_type min -max_paths 20 -nworst 1 -nosplit }
redirect -file $OUT/reports/constraints.rpt   { report_constraint -all_violators -verbose }
redirect -file $OUT/reports/fanout.rpt        { report_constraint -all_violators -verbose -max_fanout }
redirect -file $OUT/reports/design.rpt        { report_design -nosplit }

# ---- write ----------------------------------------------------------------
write -format ddc     -hierarchy -output $OUT/mapped.ddc
write -format verilog -hierarchy -output $OUT/mapped.v
if {[catch {write_sdc -nosplit -output $OUT/mapped.sdc} msg]} {
    puts "write_sdc -output unavailable ($msg); retrying positional form"
    write_sdc -nosplit $OUT/mapped.sdc
}

set mapped_macro [get_cells -hierarchical -filter "ref_name =~ $MACREF" -quiet]
puts "KWT_MAPPED_MACRO_INSTANCES [sizeof_collection $mapped_macro]"
if {[sizeof_collection $mapped_macro] != 20} {
    error "mapped netlist lost SRAM macro blackboxes; area/timing results are invalid"
}

puts "KWT_DC_SYNTH7_FINISHED"
exit
