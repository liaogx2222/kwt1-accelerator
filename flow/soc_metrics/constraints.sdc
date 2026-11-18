# Reference clocks: same FPGA_SOURCE clock bypass as the functional reference.
# Analog PLL/pads are excluded, all digital logic and SRAM are included in power.
create_clock -name hfclk -period 6.666667 [get_ports hfextclk]
create_clock -name lfclk -period 30517.578125 [get_ports lfextclk]
create_clock -name jtagclk -period 100.000 [get_ports io_pads_jtag_TCK_i_ival]
set_clock_uncertainty -setup 0.300 [all_clocks]
set_clock_uncertainty -hold 0.150 [all_clocks]
# No asynchronous clock groups or reset false paths are introduced.
set data_in [remove_from_collection [all_inputs] [get_ports {hfextclk lfextclk io_pads_jtag_TCK_i_ival}]]
set_input_delay -clock hfclk -max 1.500 $data_in
set_input_delay -clock hfclk -min 0.000 $data_in
set_input_transition 0.150 $data_in
set diagnostics [get_ports -quiet mon_*]
set physical_out [remove_from_collection [all_outputs] $diagnostics]
set_output_delay -clock hfclk -max 1.500 $physical_out
set_output_delay -clock hfclk -min 0.000 $physical_out
set_load 0.020 $physical_out
# Zero-load observations retain test visibility; these are not physical I/O.
set_output_delay -clock hfclk -max 0.000 $diagnostics
set_output_delay -clock hfclk -min 0.000 $diagnostics
set_load 0.000 $diagnostics
