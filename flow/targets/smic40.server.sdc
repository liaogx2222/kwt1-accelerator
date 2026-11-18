# =============================================================================
# kwt1_mmio @ 150 MHz -- SMIC40 constraint set
# -----------------------------------------------------------------------------
# STATUS: PRE-LAYOUT ASSUMPTION SET, not a reviewed platform contract.
#   This file exists so S8/S9 can run with an explicit, auditable budget.
#   It must NOT be cited as evidence for a 150 MHz signoff claim until the four
#   assumptions below are replaced by the platform integrator's numbers.
#
#   A-01 clock uncertainty 0.300 ns (4.50% of period) : jitter + skew before CTS.
#        Hold uncertainty 0.150 ns. Replace with the post-CTS number.
#   A-02 I/O budget 1.500 ns per direction (22.50%)   : on-chip synchronous MMIO
#        bus, equal split in/out. Internal logic therefore gets
#        6.666667 - 0.300 - 1.500 - 1.500 = 3.366667 ns.
#   A-03 input transition 150 ps, output load 20 fF   : placeholder driver/load
#        until the E203 bus contract is supplied.
#   A-04 reset: asynchronous assertion, synchronous de-assertion, TIMED AS DATA.
#        No whole-domain false path is used (prohibited by the signoff plan), so
#        DC must build and time a real reset tree in SMIC40. The Nangate45
#        result (431 reset buffers, WNS +0.5940746 ns) is NOT inherited.
#
# Unconstrained endpoints are a hard gate: S9 requires check_timing to report 0.
# =============================================================================

set clk_name   accel_clk
set clk_uncert 0.300
set hold_uncert 0.150
set io_delay   1.500

# ---- clock ----------------------------------------------------------------
create_clock -name accel_clk -period 6.666667 [get_ports clk]
set_clock_uncertainty -setup $clk_uncert  [get_clocks $clk_name]
set_clock_uncertainty -hold  $hold_uncert [get_clocks $clk_name]
set_clock_transition 0.150 [get_clocks $clk_name]

# ---- port groups ----------------------------------------------------------
set in_ports  [get_ports {abort_hw core_enable mem_enable req_valid \
                          req_write req_addr req_wdata req_wstrb resp_ready}]
set out_ports [get_ports {req_ready resp_valid resp_rdata resp_error irq}]
set rst_port  [get_ports rst_n]

# ---- I/O timing (A-02) ----------------------------------------------------
set_input_delay  -clock $clk_name -max $io_delay $in_ports
set_input_delay  -clock $clk_name -min 0.000     $in_ports
set_output_delay -clock $clk_name -max $io_delay $out_ports
set_output_delay -clock $clk_name -min 0.000     $out_ports

# ---- reset (A-04) ---------------------------------------------------------
# Timed as a normal input on purpose: no blanket false path. Recovery/removal
# at the async pins will force a real reset buffer tree.
set_input_delay -clock $clk_name -max $io_delay $rst_port
set_input_delay -clock $clk_name -min 0.000     $rst_port

# ---- drive / load (A-03) --------------------------------------------------
# The obvious one-liner
#     set_input_transition 0.150 [remove_from_collection [all_inputs] [get_ports clk]]
# does NOT work on this platform: dc_shell T-2022.03-SP5 answers
#     Error: unknown command 'remove_from_collection' (CMD-005)
# and then SKIPS THE WHOLE LINE, leaving every input at the library default
# transition -- i.e. an optimistic, silently unconstrained budget. Apply the
# transition to the named groups instead; the clock port is excluded by
# construction, which is exactly what the original expression meant.
set_input_transition 0.150 $in_ports
set_input_transition 0.150 $rst_port
set_load 0.020 [all_outputs]

# =============================================================================
# Deliberately NOT constrained here:
#   * no whole-domain timing exceptions of any kind (prohibited by the signoff
#     plan; any future exception needs "source" and "reason" in the binding JSON
#     under "exceptions", and must be scoped to a named path group)
#   * no set_max_transition / set_max_fanout override: the SMIC40 libraries
#     carry their own design rules and a global override can conflict with them.
#     The macro input pins declare max_transition 0.760 ns; DC will pick that up
#     from the bound .db.
#   * no clock latency / propagated clock: pre-layout, ideal clock.
# =============================================================================
