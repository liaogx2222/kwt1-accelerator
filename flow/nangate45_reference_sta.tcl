# Reference standard-cell timing only. No SRAM timing/RC or platform I/O delays.
read_liberty third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib
read_verilog rtl/v2/kwt_tech_sram_blackbox.sv
read_verilog $::env(KWT_STA_NETLIST)
link_design kwt1_mmio
create_clock -name accel_clk -period 6.666667 [get_ports clk]
# Functional running mode; reset/abort transitions require separate acceptance.
set_case_analysis 1 [get_ports rst_n]
set_case_analysis 0 [get_ports abort_hw]
set_case_analysis 1 [get_ports core_enable]
set_case_analysis 1 [get_ports mem_enable]
# Ideal clock, default zero uncertainty and no wire parasitics are declared
# reference assumptions, not platform data. I/O delays remain UNSET.
set out $::env(KWT_STA_OUTPUT)
check_setup -verbose > $out/check_setup.txt
report_checks -unconstrained -group_count 20 -digits 6 > $out/unconstrained_examples.txt
set starts [all_registers -output_pins]
# OpenSTA 2.0.17 all_registers -data_pins ALSO includes RN/SN recovery pins.
# This Nangate netlist has exactly 29942 DFF D pins; keep data setup separate.
set ends [get_pins */D]
if {[llength $ends] != 29942} {error "Unexpected DFF data pin coverage"}
puts "REGISTER_OUTPUT_PINS [llength $starts]"
puts "REGISTER_DATA_PINS [llength $ends]"
report_checks -from $starts -to $ends -path_delay max -group_count 10 -format full_clock_expanded -fields {slew capacitance input_pin net} -digits 6 > $out/setup_paths.txt
report_checks -from $starts -to $ends -path_delay min -group_count 10 -format full_clock_expanded -fields {slew capacitance input_pin net} -digits 6 > $out/hold_paths.txt
report_worst_slack -digits 6 > $out/global_worst_slack_reference.txt
report_tns -digits 6 > $out/global_tns_reference.txt
set paths [find_timing_paths -from $starts -to $ends -path_delay max -group_count 100000 -endpoint_count 1]
set tns 0.0
set wns 1.0e30
set negative 0
foreach path $paths {
  set slack [get_property $path slack]
  if {$slack < $wns} {set wns $slack}
  if {$slack < 0} {set tns [expr {$tns+$slack}];incr negative}
}
puts "REG2REG_SETUP_PATHS [llength $paths]"
puts "REG2REG_WORST_SETUP_SLACK $wns"
puts "REG2REG_SETUP_TNS $tns"
puts "REG2REG_NEGATIVE_SETUP_ENDPOINTS $negative"
puts "REFERENCE_STA_FINISHED"
exit
