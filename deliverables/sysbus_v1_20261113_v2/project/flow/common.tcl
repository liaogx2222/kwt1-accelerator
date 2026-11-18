set PROJECT [file normalize [file join [file dirname [info script]] ..]]
set TOP kwt_soc_joint
foreach name {KWT_PDK_ROOT KWT_SRAM_DB_DIR} {
 if {![info exists ::env($name)]} { error "missing environment $name" }
}
set PDK [file normalize $::env(KWT_PDK_ROOT)]
set SRAMDIR [file normalize $::env(KWT_SRAM_DB_DIR)]
proc require_file {p} {if {![file isfile $p]} {error "missing file $p"}}
proc host_python {args} {
 return [eval [linsert $args 0 exec /usr/bin/env -u LD_LIBRARY_PATH -u LD_PRELOAD -u PYTHONHOME -u PYTHONPATH /usr/bin/python3]]
}
proc libs {corner} {
 global PDK SRAMDIR
 switch $corner {
  ss {set std ss_v0p99_125c;set ram ss_0p99v_0p99v_125c}
  ff {set std ff_v1p21_-40c;set ram ff_1p21v_1p21v_m40c}
  tt {set std tt_v1p1_25c;set ram tt_1p10v_1p10v_25c}
  default {error "bad corner"}
 }
 set result {}
 foreach vt {HVT LVT RVT} {
  lappend result $PDK/SCC40NLL_VHSC40_${vt}_V0.1/SCC40NLL_VHSC40_${vt}_V0p1/liberty/1.1v/scc40nll_vhsc40_[string tolower $vt]_${std}_basic.db
 }
 lappend result $SRAMDIR/RAMSP4096X16_${ram}.db
 foreach p $result {require_file $p}
 return $result
}
proc read_soc_constraints {} {
 global PROJECT
 source $PROJECT/flow/constraints.sdc
}
proc check_macros {} {
 set all [get_cells -hierarchical -quiet -filter {ref_name =~ RAMSP4096X16*}]
 set n [sizeof_collection $all]
 puts "SOC_MACRO_COUNT $n expected=100 private=20 shared=64 ITCM=8 DTCM=8"
 if {$n != 100} {error "complete SoC macro inventory mismatch"}
 return $all
}
