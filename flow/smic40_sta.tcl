# Template, not executable STA evidence. Use the SAME mapped design/corner.
if {![info exists ::env(KWT_BOUND_LIBRARIES)] || ![info exists ::env(KWT_BOUND_SDC)]} {
    error "STA requires authorized libraries, actual mapped netlist and reviewed SDC"
}
# Read/link standard-cell and all 20 SRAM macro timing models at each PVT.
# Read the mapped netlist and target SDC; report all unconstrained paths first.
# Report setup/hold WNS/TNS, clock propagation assumption and applied exceptions.
# Never replace unbound I/O constraints with zero delays or a domain false path.
# Require WNS >= 0 at 150 MHz only after complete timing coverage is established.
