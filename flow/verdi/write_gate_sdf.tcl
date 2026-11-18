# =============================================================================
# Optional: emit SDF from the SAME mapped design, for gate-level timing sim.
# -----------------------------------------------------------------------------
# This is a SEPARATE add-on script. Do NOT edit flow/smic40_dc_synthesis.tcl:
# every file in the uploaded bundle is hash-bound by sha256sum.txt, and the
# frozen-source screening expects those bytes to stay unchanged.
#
# Run after S8 has produced mapped.ddc:
#   export KWT_GATE_DDC=../signoff_out/dc_synth/mapped.ddc
#   export KWT_GATE_SDF=../signoff_out/dc_synth/mapped.sdf
#   "$KWT_DC_SHELL" -f flow/verdi/write_gate_sdf.tcl | tee ../signoff_out/dc_synth/write_sdf.log
#
# CAVEAT: DC SDF is a PRE-LAYOUT wire-load estimate, not signoff timing. If the
# platform provides PrimeTime, prefer `pt_shell` write_sdf from the signed-off
# corner. Zero-delay functional simulation does not need this file at all.
# =============================================================================
set required {KWT_GATE_DDC KWT_GATE_SDF}
foreach v $required {
    if {![info exists ::env($v)] || [string trim $::env($v)] eq ""} {
        error "MISSING BINDING $v"
    }
}
set DDC $::env(KWT_GATE_DDC)
set SDF $::env(KWT_GATE_SDF)
if {![file isfile $DDC]} { error "mapped DDC not found: $DDC" }
file mkdir [file dirname $SDF]

read_ddc $DDC
current_design kwt1_mmio
link
# The DDC already carries the constraints applied at synthesis time.
# Do NOT read_sdc again here: it would duplicate clocks and I/O delays.

if {[file exists $SDF]} { file delete -force $SDF }
set written 0
if {![catch {write_sdf -version 3.0 -output $SDF} msg]} {
    if {[file isfile $SDF]} { set written 1 }
}
if {!$written} {
    if {![catch {write_sdf $SDF} msg2]} {
        if {[file isfile $SDF]} { set written 1 }
    }
}
if {$written} {
    puts "KWT_SDF_WRITTEN $SDF"
    puts "KWT_SDF_NOTE pre-layout DC estimate; not signoff timing"
} else {
    puts "KWT_SDF_UNAVAILABLE write_sdf failed on this DC build ($msg)"
    puts "KWT_SDF_NOTE fall back to ZERO-DELAY functional gate sim, or use pt_shell"
}
exit
