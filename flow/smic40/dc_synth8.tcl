# =============================================================================
# dc_synth8.tcl -- re-synthesis of kwt1_mmio with the SRAM wrapper MAPPED
# -----------------------------------------------------------------------------
# WHY THIS RUN EXISTS  (supersedes dc_synth7)
#
#   dc_synth7 finished, but its netlist still contains UNMAPPED generic logic
#   inside the 20 SRAM wrappers:
#
#       Cell 'GTECH_BUF'     ... accel.banks.bank[0].ram.macro_cell.B_0
#       Cell 'GTECH_AND2'    ... macro_cell.C32( .A(en), .B(we), .Z(wr) )
#       Cell 'GTECH_NOT'     ... macro_cell.I_0( .A(en), .Z(cen_n) )
#       Cell 'SELECT_OP'     ... macro_cell.C29( 16-bit mux for wen_n )
#
#   Cause: dc_synth7.tcl did
#       set_dont_touch [get_designs kwt_tech_sram_4096x16]
#   which freezes the wrapper design BEFORE mapping, so the four assign
#   statements (wr / cen_n / gwen_n / wen_n) stay as GTECH cells forever.
#   A GTECH netlist is not a signoff netlist: those cells have no .db area and
#   no timing arcs, so PT either black-boxes them or drops the macro control
#   paths entirely.
#
#   History, so this is not repeated: dc_synth3.tcl ended with
#       current_design kwt_tech_sram_4096x16
#       compile -map_effort high
#       current_design kwt1_mmio
#   Those three lines looked like dead code and were removed in dc_synth7.
#   They were not dead -- the plain `compile` is what mapped the wrapper.
#   dc_synth5/mapped.v had GTECH count 0 precisely because of them.
#   The fix is NOT to bring them back (they also cost ~10% area because
#   current_design <subdesign> fails with UID-109 and the following plain
#   `compile` lands on the TOP, throwing away compile_ultra quality).
#   The fix is to stop dont_touching the wrapper and let compile_ultra map it.
#
# OTHER CHANGES vs dc_synth7
#   * the scoped reset set_max_fanout / set_max_transition block is GONE.
#     It never applied: DC T-2022.03 accepts only design/port/PIN objects and
#     answered `CMD-036: Value for list 'object_list' must have 1 elements`.
#     It is not needed either -- with the trailing plain `compile` removed,
#     compile_ultra builds the reset distribution itself and PT reports
#     **async_default** (max/setup) slack +1.66 with 0 violating paths.
#   * a hard GUARD after compile: zero GTECH / unmapped cells, else error out.
#     dc_synth7 produced a netlist that looked fine in every summary line but
#     could not be simulated; that must fail loudly from now on.
#   * change_names -rules verilog before write, so the netlist is legal
#     Verilog for VCS without post-processing.
#
# INVOKE
#   dc_shell -f /home/.../out/dc_synth8.tcl \
#            -output_log_file /home/.../out/dc_synth8.log
# =============================================================================

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

# ---- primary corner = ss_0p99v_125c, identical to dc_synth5 / dc_synth7 ----
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
# ONLY the macro instances are dont_touch.  Do NOT dont_touch the wrapper
# design -- that is what left dc_synth7 with GTECH cells inside macro_cell.
set_dont_touch $macro_cells

# ---- constraints ----------------------------------------------------------
read_sdc $SDC

redirect -file $OUT/reports/check_design.rpt { check_design -summary }

# ---- synthesis ------------------------------------------------------------
compile_ultra -no_autoungroup

# ---- [GUARD] no generic / unmapped cell may survive ------------------------
set gtech_cells [get_cells -hierarchical -filter "ref_name =~ GTECH*" -quiet]
set select_ops  [get_cells -hierarchical -filter "ref_name =~ SELECT_OP*" -quiet]
set n_gtech [sizeof_collection $gtech_cells]
set n_sel   [sizeof_collection $select_ops]
puts "KWT_GTECH_CELLS $n_gtech"
puts "KWT_SELECT_OP_CELLS $n_sel"
if {$n_gtech != 0 || $n_sel != 0} {
    error "unmapped generic logic survived synthesis ($n_gtech GTECH + $n_sel SELECT_OP); the netlist is not a signoff netlist"
}

# ---- reports --------------------------------------------------------------
redirect -file $OUT/reports/area.rpt          { report_area -hierarchy }
redirect -file $OUT/reports/cell.rpt          { report_cell -nosplit }
redirect -file $OUT/reports/timing_setup.rpt  { report_timing -delay_type max -max_paths 20 -nworst 1 -nosplit }
redirect -file $OUT/reports/timing_hold.rpt   { report_timing -delay_type min -max_paths 20 -nworst 1 -nosplit }
redirect -file $OUT/reports/constraints.rpt   { report_constraint -all_violators -verbose }

# ---- write ----------------------------------------------------------------
# change_names first: dc_synth7 wrote escaped identifiers straight through and
# the result was painful to compile with VCS.
change_names -rules verilog -hierarchy
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

puts "KWT_DC_SYNTH8_FINISHED"
exit
