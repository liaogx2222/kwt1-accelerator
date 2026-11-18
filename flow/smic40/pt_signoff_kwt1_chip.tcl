# =============================================================================
# pt_signoff.tcl -- PrimeTime tri-corner STA + power for kwt1_chip
# -----------------------------------------------------------------------------
# This is the kwt1_chip-tree edition of flow/smic40/pt_signoff8.tcl.
# Only the four INPUT/OUTPUT paths changed; every measurement, guard and
# caveat of the original is kept verbatim, because the numbers already
# reported (ss setup 0 violations / TNS 0.00 / 20 macro cells bound) came
# from exactly this script body.
#
# PATH RESOLUTION
#   The four paths are derived from the location of this file, so the tree
#   can be moved or copied without editing.  Run it from kwt1_chip/sta:
#       pt_shell -f pt_signoff.tcl -output_log_file pt.log
#   PDK / SRAM .db stay absolute on purpose: they live outside the tree, and
#   a wrong relative path there would silently drop a library.
#
# INPUTS
#   netlist  syn/accel/netlist/kwt1_mmio.v      (dc_synth8 mapped netlist)
#   sdc      syn/accel/script/constraints.sdc   (copy of smic40.server.sdc)
#   saif     sim/gate/kwt1_gate_c0.saif         (optional, gate-level)
#
# OUTPUTS  sta/report/
#   timing_<corner>.rpt / async_default_<corner>.rpt / check_timing_<corner>.rpt
#   power_tt.rpt   (only when the SAIF exists)
#
# KNOWN LIMITATION, must be quoted with any number taken from here:
#   pre-layout, no SPEF.  Net switching power is absent, so dynamic power is
#   cell internal + cell switching only -- an optimistic lower bound.
# =============================================================================

set_app_var sh_enable_page_mode false

# PT ships with power analysis OFF; report_power fails with PWR-001 otherwise.
set_app_var power_enable_analysis true
if {[catch {set power_analysis_mode average} m]} {
  puts "NOTE power_analysis_mode not settable here: $m"
}

# sta/pt_signoff.tcl -> sta -> kwt1_chip
set ROOT    [file dirname [file dirname [file normalize [info script]]]]
set TOP     kwt1_mmio
set NETLIST $ROOT/syn/accel/netlist/kwt1_mmio.v
set SDC     $ROOT/syn/accel/script/constraints.sdc
set SAIF    $ROOT/sim/gate/kwt1_gate_c0.saif
set OUT     $ROOT/sta/report

set PDK     /path/to/project/pdk_extract/SMIC40/S40/smic
set HVT     $PDK/SCC40NLL_VHSC40_HVT_V0.1/SCC40NLL_VHSC40_HVT_V0p1/liberty/1.1v
set LVT     $PDK/SCC40NLL_VHSC40_LVT_V0.1/SCC40NLL_VHSC40_LVT_V0p1/liberty/1.1v
set RVT     $PDK/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/liberty/1.1v
set SRAMDIR /path/to/project/lib_smic40

file mkdir $OUT

puts "PT_ROOT $ROOT"
if {![file isfile $NETLIST]} {
  error "netlist not found: $NETLIST -- do not run PT against a stale path"
}
if {![file isfile $SDC]} {
  error "constraints not found: $SDC"
}
puts "PT_NETLIST $NETLIST"
puts "PT_NETLIST_BYTES [file size $NETLIST]"

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

  # ---- did the 20 macros really bind? -------------------------------------
  if {[catch {
      set nmac [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ RAMSP4096X16*" -quiet]]
      puts "PT_MACRO_CELLS $nmac"
      if {$nmac != 20} {
        puts "PT_WARNING expected 20 RAMSP4096X16 instances, found $nmac"
      }
  } m]} {
    puts "PT_MACRO_CELLS_UNAVAILABLE: $m"
  }

  # ---- timing -------------------------------------------------------------
  redirect $OUT/timing_$c.rpt {
    puts "CORNER $c"
    puts "NETLIST $NETLIST"
    report_timing -delay_type max -max_paths 20 -nworst 5 -path_type full_clock_expanded
    report_timing -delay_type min -max_paths 20 -nworst 5
    report_qor
  }

  # ---- reset recovery/removal, reported on purpose ------------------------
  if {[catch {
      redirect $OUT/async_default_$c.rpt {
        puts "CORNER $c  path group async_default"
        report_timing -delay_type max -group async_default -max_paths 5 -nworst 1
      }
  } m]} {
    puts "NOTE async_default group not reported at $c : $m"
  }

  # ---- unconstrained endpoints (the S9 hard gate) -------------------------
  redirect $OUT/check_timing_$c.rpt {
    puts "CORNER $c"
    check_timing -verbose
    puts "---- disabled timing arcs (PTE-003) ----"
    report_disable_timing
  }

  # ---- power: tt only, and only when a SAIF actually exists --------------
  if {$c eq "tt_1p10v_25c"} {
    if {[file isfile $SAIF]} {
      puts "PT_SAIF $SAIF"
      read_saif $SAIF -strip_path tb_gate_tasks/dut
      update_timing -full
      update_power
      redirect $OUT/power_tt.rpt {
        puts "CORNER $c  SAIF=$SAIF"
        puts "NOTE pre-layout: no SPEF, net switching power absent"
        report_power -verbose
      }
    } else {
      puts "SKIP_POWER_SAIF_ABSENT $SAIF"
      puts "SKIP_POWER_SAIF_ABSENT: no average power will be reported this run"
    }
  }
}

puts "================ PT_SIGNOFF_DONE ================"
exit
