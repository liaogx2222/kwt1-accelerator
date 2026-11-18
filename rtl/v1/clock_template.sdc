# Example only. This is an input constraint, not a timing result.
create_clock -name accel_clk -period 6.666667 [get_ports clk]
# Platform integrator supplies I/O delay, clock uncertainty, reset and macro
# timing constraints from the designated library and interconnect contract.
