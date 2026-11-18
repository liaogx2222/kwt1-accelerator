# Template for the designated synthesis tool. Run check_technology.py first.
# No tool/vendor library API is assumed and this file is not a signoff run.
if {![info exists ::env(KWT_BOUND_LIBRARIES)] || ![info exists ::env(KWT_BOUND_SRAM_WRAPPER)]} {
    error "Bind authorized standard-cell + SRAM libraries and wrapper first"
}
# Read ONLY production RTL with KWT_TECH_SRAM defined, and the physical wrapper.
# Exclude rtl/integration/tech_sram_model.sv and behavioral SRAM data arrays.
# Verify top=kwt1_mmio and exactly 20 kwt_tech_sram_4096x16 boundaries.
# Apply the reviewed target SDC (clock 6.666667 ns plus sourced I/O/uncertainty).
# Emit mapped Verilog, unmapped/blackbox list, timing coverage and area reports.
# Area ledger = standard cells including interface + 20 actual macro areas.
# Any unresolved logic, missing macro, unconstrained endpoint or source drift
# prevents signoff. Tool-specific binding is intentionally pending.
