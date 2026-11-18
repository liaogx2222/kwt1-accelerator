# =============================================================================
# Multi-corner 150 MHz timing checks with Synopsys Design Compiler
# -----------------------------------------------------------------------------
# STATUS: runnable skeleton, NOT a substitute for the platform's designated STA.
#   * If the designated platform supplies PrimeTime (pt_shell), run the formal
#     signoff there and keep this DC report only as a synthesis-side cross-check.
#   * If only DC is available, these reports are the evidence for S9, and the
#     tool limitation must be recorded in the platform difference table (App. C).
#   * Runs on the SAME mapped netlist / SAME SDC produced by
#     flow/smic40_dc_synthesis.tcl. Do not re-synthesize here.
#   * A passing DC timing report does NOT set physical_signoff=true; the final
#     judgment still belongs to the designated platform review.
#
# Corner definitions come from scripts/emit_dc_corners.py, which converts the
# AUTHORIZED `corners` list in flow/targets/smic40.binding.filled.json into Tcl.
# No PVT value is invented in this file.
#
# Invoke (from <REPO>/keyword-transformer):
#   dc_shell -f flow/smic40_dc_sta.tcl | tee ../signoff_out/dc_sta.log
# =============================================================================

set required {KWT_DC_CORNERS_FILE KWT_DC_NETLIST KWT_BOUND_SDC KWT_DC_STA_OUT}
foreach v $required {
    if {![info exists ::env($v)] || [string trim $::env($v)] eq ""} {
        error "MISSING BINDING $v"
    }
}
set CORNERS_FILE $::env(KWT_DC_CORNERS_FILE)
set NETLIST      $::env(KWT_DC_NETLIST)
set SDC          $::env(KWT_BOUND_SDC)
set OUT          $::env(KWT_DC_STA_OUT)
set TOP          "kwt1_mmio"
foreach f [list $CORNERS_FILE $NETLIST $SDC] {
    if {![file isfile $f]} { error "required file not found: $f" }
}
file mkdir $OUT
source $CORNERS_FILE
if {![info exists KWT_DC_CORNERS] || [llength $KWT_DC_CORNERS] == 0} {
    error "KWT_DC_CORNERS is empty; regenerate it from the filled binding JSON"
}

# Read the mapped design once.
if {[string match "*.ddc" $NETLIST]} {
    read_ddc $NETLIST
} else {
    read_verilog $NETLIST
}
current_design $TOP

set summary [open $OUT/timing_summary.txt w]
puts $summary "# corner setup_wns_ns setup_tns_ns hold_wns_ns hold_tns_ns unconstrained_ok"
# Apply the reviewed SDC exactly ONCE, after the first successful link.
# Re-running read_sdc per corner can duplicate clocks / I/O delays in DC.
set sdc_loaded 0

foreach corner $KWT_DC_CORNERS {
    array unset C
    array set C $corner
    set name $C(name)
    set cdir $OUT/$name
    file mkdir $cdir

    if {![info exists C(libs)] || [llength $C(libs)] == 0} {
        error "corner $name has no standard_cell_liberty .db files"
    }
    foreach lib $C(libs) {
        if {![file isfile $lib]} { error "corner $name library not found: $lib" }
    }
    if {[info exists C(sram_libs)]} {
        foreach lib $C(sram_libs) {
            if {![file isfile $lib]} { error "corner $name SRAM library not found: $lib" }
        }
        set link_library [concat "*" $C(libs) $C(sram_libs)]
    } else {
        set link_library [concat "*" $C(libs)]
    }
    set target_library $C(libs)
    if {[info exists C(opcond)] && $C(opcond) ne ""} {
        if {[catch {set_operating_conditions $C(opcond)} msg]} {
            puts "WARNING corner $name: set_operating_conditions failed ($msg); \
                  confirm the name against the authorized .db"
        }
    }
    link
    if {!$sdc_loaded} {
        read_sdc $SDC
        set sdc_loaded 1
    }

    # ---- Hard gate: unconstrained endpoints must be ZERO, reported FIRST ----
    redirect -file $cdir/check_timing.rpt { check_timing -verbose }
    redirect -file $cdir/constraints_all_violators.rpt {
        report_constraint -all_violators -verbose
    }
    redirect -file $cdir/timing_setup.rpt {
        report_timing -delay_type max -max_paths 50 -nworst 1 -nosplit
    }
    redirect -file $cdir/timing_hold.rpt {
        report_timing -delay_type min -max_paths 50 -nworst 1 -nosplit
    }
    redirect -file $cdir/exceptions.rpt { report_exceptions -nosplit }

    # ---- WNS / TNS ---------------------------------------------------------
    # get_timing_paths + foreach_in_collection are Synopsys Tcl extensions.
    # If your DC build lacks them, use the .rpt files above and fill the numbers
    # into signoff_inputs.json manually; do NOT guess them.
    set setup_wns "NA"
    set setup_tns "NA"
    set hold_wns  "NA"
    set hold_tns  "NA"
    if {![catch {
        foreach delay {max min} {
            set paths [get_timing_paths -delay_type $delay -max_paths 100000 -nworst 1]
            set wns 1.0e30
            set tns 0.0
            foreach_in_collection p $paths {
                set slack [get_attribute $p slack]
                if {$slack < $wns} { set wns $slack }
                if {$slack < 0}    { set tns [expr {$tns + $slack}] }
            }
            if {[sizeof_collection $paths] == 0} { set wns "NO_PATHS" }
            if {$delay eq "max"} { set setup_wns $wns; set setup_tns $tns } \
                             else { set hold_wns  $wns; set hold_tns  $tns }
        }
    } msg]} {
        puts "KWT_TIMING_PATH_API $name ok"
    } else {
        puts "WARNING corner $name: timing path API unavailable ($msg); parse the .rpt files manually"
    }
    puts $summary "$name $setup_wns $setup_tns $hold_wns $hold_tns SEE_check_timing.rpt"
    puts "KWT_CORNER_DONE $name setup_wns=$setup_wns setup_tns=$setup_tns hold_wns=$hold_wns hold_tns=$hold_tns"
}
close $summary

# =============================================================================
# S9 ACCEPTANCE (fill signoff_inputs.json only after all of these hold):
#   * check_timing.rpt shows ZERO unconstrained endpoints for EVERY bound corner.
#   * setup WNS >= 0 and hold WNS >= 0 at 6.666667 ns, for EVERY bound corner.
#   * macro clk->q/setup/hold/load, I/O drive/load, reset removal/recovery,
#     clock tree propagation and uncertainty are all backed by authorized data.
#   * every SDC exception has source + reason; no all_inputs/all_outputs/all_clocks
#     false path, no zero-delay substitution.
#   * after any reset-tree / driver resizing, rerun the full mapped cold-task,
#     in-flight cancel and hard-reset recovery regressions (12,672 codes).
#   * Nangate45 WNS +0.5940746 ns / 431 reset buffers are NOT inherited.
# =============================================================================
puts "KWT_DC_STA_FINISHED"
exit
