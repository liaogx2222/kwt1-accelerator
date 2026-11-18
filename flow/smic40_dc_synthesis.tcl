# =============================================================================
# SMIC40 synthesis skeleton for Synopsys Design Compiler (dc_shell / "dccompiler")
# -----------------------------------------------------------------------------
# STATUS: runnable skeleton, NOT signoff evidence.
#   * All foundry library / macro / PVT / SDC values come from environment
#     variables bound on the server. No library name or PVT is invented here.
#   * Run ONLY after S6 `check_technology.py` exits 0 on the filled binding.
#   * This script produces a mapped netlist + area/timing reports. It does NOT
#     by itself establish 150 MHz qualification, complete counted area, or power.
#   * DC version differences exist (`-format sverilog` vs `verilog -sv`,
#     `sizeof_collection`, `check_timing`). Verify the few marked lines once on
#     the server before a real run.
#
# Invoke (from <REPO>/keyword-transformer):
#   dc_shell -f flow/smic40_dc_synthesis.tcl | tee ../signoff_out/dc_synth.log
# or, if your site wraps DC under another name:
#   $KWT_DC_SHELL -f flow/smic40_dc_synthesis.tcl ...
# =============================================================================

# ---- 0. Required bindings ---------------------------------------------------
# KWT_DC_TARGET_LIBS  colon-separated standard-cell .db for the PRIMARY corner
# KWT_DC_LINK_LIBS    colon-separated ALL .db (standard cells + SRAM macro)
# KWT_DC_SRAM_WRAPPER real macro wrapper defining module kwt_tech_sram_4096x16
# KWT_BOUND_SDC       reviewed SDC containing create_clock 6.66666... and I/O delays
# KWT_DC_MACRO_REF    glob for the macro cell ref_name after linking, e.g. "*SRAM4096X16*"
# KWT_DC_OUT_DIR      output directory for netlist/reports
set required {KWT_DC_TARGET_LIBS KWT_DC_LINK_LIBS KWT_DC_SRAM_WRAPPER
              KWT_BOUND_SDC KWT_DC_MACRO_REF KWT_DC_OUT_DIR}
foreach v $required {
    if {![info exists ::env($v)] || [string trim $::env($v)] eq ""} {
        error "MISSING BINDING $v : bind it from the authorized SMIC40 platform material"
    }
}

set TOP      "kwt1_mmio"
set OUT      $::env(KWT_DC_OUT_DIR)
set WRAPPER  $::env(KWT_DC_SRAM_WRAPPER)
set SDC      $::env(KWT_BOUND_SDC)
set RPT      $OUT/reports
file mkdir $RPT

if {![file isfile $WRAPPER]} { error "SRAM wrapper not found: $WRAPPER" }
if {![file isfile $SDC]}     { error "reviewed SDC not found: $SDC" }
# The behavioral array model MUST NOT be read: it would become 1,310,720 DFFs.
if {[string match "*tech_sram_model.sv" $WRAPPER]} {
    error "KWT_DC_SRAM_WRAPPER points at the behavioral SRAM array model; forbidden"
}
foreach f [concat [split $::env(KWT_DC_TARGET_LIBS) ":"] [split $::env(KWT_DC_LINK_LIBS) ":"]] {
    if {![file isfile $f]} { error "bound library not found: $f" }
}

# ---- 1. Library / search setup ---------------------------------------------
# HDL Compiler resolves `include via search_path; add the generated profile dir.
# If your DC version uses hdlin_incdir instead, set that variable as well.
set search_path [concat [list "." "rtl/v2/generated" "rtl/v2" "rtl/micro"] $search_path]
set target_library [split $::env(KWT_DC_TARGET_LIBS) ":"]
set link_library   [concat "*" [split $::env(KWT_DC_LINK_LIBS) ":"]]
if {[info exists ::env(KWT_DC_OP_COND)] && $::env(KWT_DC_OP_COND) ne ""} {
    set_operating_conditions $::env(KWT_DC_OP_COND)
}
define_design_lib WORK -path $OUT/WORK

# ---- 2. Read ONLY production RTL + the real macro wrapper -------------------
# Keep the exact rtl/v2/files.f order. `tech_sram_model.sv` is deliberately absent.
set rtl_files [list \
    $WRAPPER \
    rtl/micro/mul_pipe.sv \
    rtl/micro/rne_pipe.sv \
    rtl/v2/kwt_sram_sp.sv \
    rtl/v2/kwt_mac8x8.sv \
    rtl/v2/kwt_iterative.sv \
    rtl/v2/kwt_math.sv \
    rtl/v2/kwt_packet_loader.sv \
    rtl/v2/kwt_layer_banked.sv \
    rtl/v2/kwt1_accel.sv \
    rtl/v2/kwt1_mmio.sv]
foreach f $rtl_files { if {![file isfile $f]} { error "RTL source not found: $f" } }

# KWT_TECH_SRAM switches kwt_sram_sp.sv from a 4096x16 register array to the
# macro instance. Without this define the synthesis result is invalid.
# NOTE: confirm `-format sverilog -define` on your DC version before the real run.
analyze -format sverilog -define KWT_TECH_SRAM -lib WORK $rtl_files
elaborate $TOP -lib WORK
current_design $TOP
link

# ---- 3. Blackbox integrity guard -------------------------------------------
# Exactly 20 macro boundaries. Adapt KWT_DC_MACRO_REF to the physical macro cell
# name from the authorized .db (ref_name changes once instances are linked).
set macro_cells [get_cells -hierarchical \
    -filter "ref_name =~ $::env(KWT_DC_MACRO_REF)" -quiet]
set macro_count [sizeof_collection $macro_cells]
puts "KWT_MACRO_INSTANCES $macro_count"
if {$macro_count != 20} {
    error "expected exactly 20 SRAM macro instances, found $macro_count; \
           check KWT_TECH_SRAM, KWT_DC_MACRO_REF and the wrapper"
}
set_dont_touch $macro_cells
# A resolved blackbox must stay a blackbox; forbid DC from touching its contents.
if {[sizeof_collection [get_designs kwt_tech_sram_4096x16 -quiet]] > 0} {
    set_dont_touch [get_designs kwt_tech_sram_4096x16]
}

# ---- 4. Constraints --------------------------------------------------------
read_sdc $SDC
redirect -file $RPT/check_design.rpt { check_design -summary }
# Zero unconstrained endpoints is a hard gate, not a report to skim later.
redirect -file $RPT/check_timing.rpt { check_timing -verbose }
redirect -file $RPT/constraints_all_violators.rpt { report_constraint -all_violators -verbose }

# ---- 5. Synthesis ----------------------------------------------------------
# Do not enable auto-ungroup across the macro boundary; keep the hierarchy for
# the area ledger and for the same-netlist STA/power stages.
compile_ultra -no_autoungroup

# ---- 6. Outputs ------------------------------------------------------------
redirect -file $RPT/area.rpt            { report_area -hierarchy }
redirect -file $RPT/cell.rpt            { report_cell -nosplit }
redirect -file $RPT/timing_setup.rpt    { report_timing -delay_type max -max_paths 20 -nworst 1 -nosplit }
redirect -file $RPT/timing_hold.rpt     { report_timing -delay_type min -max_paths 20 -nworst 1 -nosplit }
redirect -file $RPT/constraints.rpt     { report_constraint -all_violators -verbose }
redirect -file $RPT/design.rpt          { report_design -nosplit }

write -format ddc     -hierarchy -output $OUT/mapped.ddc
write -format verilog -hierarchy -output $OUT/mapped.v
# write_sdc accepts -output on newer DC and a positional filename on older ones.
if {[catch {write_sdc -nosplit -output $OUT/mapped.sdc} msg]} {
    puts "write_sdc -output unavailable ($msg); retrying positional form"
    write_sdc -nosplit $OUT/mapped.sdc
}

# Re-check the macro count on the MAPPED netlist (some DC flows re-link cells).
set mapped_macro [get_cells -hierarchical \
    -filter "ref_name =~ $::env(KWT_DC_MACRO_REF)" -quiet]
puts "KWT_MAPPED_MACRO_INSTANCES [sizeof_collection $mapped_macro]"
if {[sizeof_collection $mapped_macro] != 20} {
    error "mapped netlist lost SRAM macro blackboxes; area/timing results are invalid"
}

# =============================================================================
# AREA LEDGER NOTE (feeds S10, not computed here):
#   report_area gives standard-cell area in LIBRARY area units (um^2 for most
#   SMIC40 libraries -- CONFIRM the unit in the .db). Blackboxed macros are NOT
#   counted by report_area unless they are linked to a characterized library
#   cell with an area attribute. Therefore:
#     complete_counted_area_mm2 = std_cell_um2/1e6 + 20 * area_per_instance_um2/1e6
#   and must include ALL newly added interface logic without double counting.
#   Reused E203 / shared 512KiB / fixed bus are reported SEPARATELY.
#
# POWER NOTE (feeds S10):
#   DC report_power is only meaningful after annotating switching activity from
#   a gate-level SAIF/VCD of THIS SAME mapped netlist, THIS SAME corner, and the
#   SAME 12-task window. Without that, SoC_average_power_mW must stay null.
#   Default/toggle-derived estimates are not signoff power.
#
# TIMING NOTE (feeds S9):
#   The reports above are for the PRIMARY synthesis corner only. Formal
#   150 MHz qualification needs every bound PVT corner (flow/smic40_dc_sta.tcl).
#   Nangate45 WNS +0.5940746 ns and its 431 reset-tree buffers are NOT inherited.
# =============================================================================
puts "KWT_DC_SYNTH_FINISHED"
exit
