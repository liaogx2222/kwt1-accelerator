# =============================================================================
# pt_signoff.tcl -- PrimeTime tri-corner STA + check_timing + tt-corner power
# -----------------------------------------------------------------------------
# WHY PRIMETIME, NOT DC:
#   dc_shell T-2022.03-SP5 on RServer06 does not implement `check_timing`
#   (MD-013), and flow/targets/smic40.server.sdc states that "unconstrained
#   endpoints are a hard gate: S9 requires check_timing to report 0".  PT has
#   the command, so the gate can actually be evaluated here.
#
# INPUTS
#   netlist  out/dc_synth5/mapped.v        (the ONLY valid netlist; dc_synth3
#                                           still carries the non-ASCII RETIN pin)
#   sdc      flow/targets/smic40.server.sdc
#   saif     out/gate_sim/kwt1_gate.saif   (written by tb_gate_tasks.sv,
#                                           $toggle_report scope tb_gate_tasks.dut)
#
# OUTPUTS  out/pt_signoff/
#   timing_ss_0p99v_125c.rpt / _ff_1p21v_m40c.rpt / _tt_1p10v_25c.rpt
#   check_timing_<corner>.rpt
#   power_tt.rpt
#
# KNOWN LIMITATION, must be quoted with the number:
#   pre-layout, no SPEF.  Net switching power is therefore absent and the
#   reported dynamic power is cell internal + cell switching only.  This is an
#   optimistic lower bound, not a post-route signoff number.
# =============================================================================

set_app_var sh_enable_page_mode false

# PT ships with power analysis OFF; report_power fails with PWR-001 otherwise.
set_app_var power_enable_analysis true
if {[catch {set power_analysis_mode average} m]} {
  puts "NOTE power_analysis_mode not settable here: $m"
}

set TOP     kwt1_mmio
set NETLIST /path/to/project/out/dc_synth5/mapped.v
set SDC     /path/to/project/server_signoff_20261106/keyword-transformer/flow/targets/smic40.server.sdc
set SAIF    /path/to/project/out/gate_sim/kwt1_gate.saif
set OUT     /path/to/project/out/pt_signoff

set PDK     /path/to/project/pdk_extract/SMIC40/S40/smic
set HVT     $PDK/SCC40NLL_VHSC40_HVT_V0.1/SCC40NLL_VHSC40_HVT_V0p1/liberty/1.1v
set LVT     $PDK/SCC40NLL_VHSC40_LVT_V0.1/SCC40NLL_VHSC40_LVT_V0p1/liberty/1.1v
set RVT     $PDK/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/liberty/1.1v
set SRAMDIR /path/to/project/lib_smic40

file mkdir $OUT

foreach c {ss_0p99v_125c ff_1p21v_m40c tt_1p10v_25c} {

  if {$c eq "ss_0p99v_125c"} {
    set libs [list \
      $HVT/scc40nll_vhsc40_hvt_ss_v0p99_125c_basic.db \
      $LVT/scc40nll_vhsc40_lvt_ss_v0p99_125c_basic.db \
      $RVT/scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db \
      $SRAMDIR/RAMSP4096X16_ss_0p99v_0p99v_125c.db]
  } elseif {$c eq "ff_1p21v_m40c"} {
    set libs [list \
      $HVT/scc40nll_vhsc40_hvt_ff_v1p21_-40c_basic.db \
      $LVT/scc40nll_vhsc40_lvt_ff_v1p21_-40c_basic.db \
      $RVT/scc40nll_vhsc40_rvt_ff_v1p21_-40c_basic.db \
      $SRAMDIR/RAMSP4096X16_ff_1p21v_1p21v_m40c.db]
  } else {
    set libs [list \
      $HVT/scc40nll_vhsc40_hvt_tt_v1p1_25c_basic.db \
      $LVT/scc40nll_vhsc40_lvt_tt_v1p1_25c_basic.db \
      $RVT/scc40nll_vhsc40_rvt_tt_v1p1_25c_basic.db \
      $SRAMDIR/RAMSP4096X16_tt_1p10v_1p10v_25c.db]
  }

  puts "================ CORNER $c ================"
  remove_design -all
  set link_path "* [join $libs { }]"

  read_verilog $NETLIST
  current_design $TOP
  link_design
  read_sdc $SDC
  update_timing -full

  # ---- timing -------------------------------------------------------------
  redirect $OUT/timing_$c.rpt {
    puts "CORNER $c"
    report_timing -delay_type max -max_paths 20 -nworst 5 -path_type full_clock_expanded
    report_timing -delay_type min -max_paths 20 -nworst 5
    report_qor
  }

  # ---- unconstrained endpoints (the S9 hard gate) -------------------------
  # PTE-003 ("some timing arcs have been disabled for breaking timing loops or
  # because of constant propagation") is reported here too: if the SRAM macro's
  # `when = RETIN ...` setup arcs got disabled, every macro-to-register path is
  # silently unconstrained and the setup numbers are optimistic.
  redirect $OUT/check_timing_$c.rpt {
    puts "CORNER $c"
    check_timing -verbose
    puts "---- disabled timing arcs (PTE-003) ----"
    report_disable_timing
  }

  # ---- power: tt only, with the RTL-generated SAIF ------------------------
  if {$c eq "tt_1p10v_25c"} {
    read_saif $SAIF -strip_path tb_gate_tasks/dut
    update_timing -full
    update_power
    redirect $OUT/power_tt.rpt {
      puts "CORNER $c  SAIF=$SAIF"
      puts "NOTE pre-layout: no SPEF, net switching power absent"
      report_power -verbose
    }
  }
}

puts "================ PT_SIGNOFF_DONE ================"
exit
