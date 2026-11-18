# =============================================================================
# pt_signoff8.tcl -- PrimeTime tri-corner STA for the dc_synth8 netlist
# -----------------------------------------------------------------------------
# DIFFERENCES vs pt_signoff.tcl (which points at dc_synth5):
#   1. NETLIST  -> out/dc_synth8/mapped.v   (the first netlist whose SRAM
#                  wrapper is fully mapped; dc_synth7 still carried GTECH)
#   2. OUT      -> out/pt_signoff8          (keep dc_synth5/7 results intact)
#   3. SAIF     -> out/gate_sim/kwt1_gate_c0.saif, and read ONLY IF THE FILE
#                  EXISTS.  pt_signoff.tcl called read_saif unconditionally,
#                  so any run made before the gate simulation finished died at
#                  the tt corner -- after the ss/ff reports were already
#                  written, which is why that failure was easy to miss.
#   4. an explicit async_default (recovery/removal) report per corner.
#      dc_synth8 dropped the scoped `set_max_fanout 32` on the *task_rst* nets,
#      on the argument that compile_ultra builds the reset tree itself.  The
#      evidence for that was dc_synth5's -5.19 ns cascade disappearing on
#      dc_synth7, but dc_synth7's wrapper was still GTECH.  This report is the
#      direct measurement; a recovery violation here means the block must go
#      back into the synthesis script (RTL untouched).
#   5. an explicit count of RAMSP4096X16 instances per corner.  A2 says
#      "Creating black box" must not appear; counting the 20 macros proves the
#      macro .db files actually bound rather than the netlist silently linking
#      against empty models.
#
# INPUTS
#   netlist  out/dc_synth8/mapped.v
#   sdc      flow/targets/smic40.server.sdc
#   saif     out/gate_sim/kwt1_gate_c0.saif   (optional, gate-level)
#
# OUTPUTS  out/pt_signoff8/
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

set TOP     kwt1_mmio
set NETLIST /path/to/project/out/dc_synth8/mapped.v
set SDC     /path/to/project/server_signoff_20261106/keyword-transformer/flow/targets/smic40.server.sdc
set SAIF    /path/to/project/out/gate_sim/kwt1_gate_c0.saif
set OUT     /path/to/project/out/pt_signoff8

set PDK     /path/to/project/pdk_extract/SMIC40/S40/smic
set HVT     $PDK/SCC40NLL_VHSC40_HVT_V0.1/SCC40NLL_VHSC40_HVT_V0p1/liberty/1.1v
set LVT     $PDK/SCC40NLL_VHSC40_LVT_V0.1/SCC40NLL_VHSC40_LVT_V0p1/liberty/1.1v
set RVT     $PDK/SCC40NLL_VHSC40_RVT_V0.1/SCC40NLL_VHSC40_RVT_V0p1/liberty/1.1v
set SRAMDIR /path/to/project/lib_smic40

file mkdir $OUT

if {![file isfile $NETLIST]} {
  error "netlist not found: $NETLIST -- do not run PT against a stale path"
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

  # ---- reset recovery/removal, reported on purpose (see header item 4) ----
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

puts "================ PT_SIGNOFF8_DONE ================"
exit
