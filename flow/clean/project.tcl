# Relocatable project: PDKs remain outside the source bundle.
set PROJECT [file normalize [file join [file dirname [info script]] ..]]
set TOP kwt1_mmio
set SDC $PROJECT/flow/constraints.sdc
foreach var {KWT_PDK_ROOT KWT_SRAM_DB_DIR} {
    if {![info exists ::env($var)]} { error "setenv $var before running this flow" }
}
set PDK [file normalize $::env(KWT_PDK_ROOT)]
set SRAMDIR [file normalize $::env(KWT_SRAM_DB_DIR)]
# EDA tool startup may add incompatible Python libraries to its environment.
# Clean only the child process; the DC/PT process keeps its library settings.
proc kwt_host_python {args} {
    set python /usr/bin/python3
    if {[info exists ::env(KWT_HOST_PYTHON)] && $::env(KWT_HOST_PYTHON) ne ""} {
        set python $::env(KWT_HOST_PYTHON)
    }
    if {![file executable $python]} { error "host Python is not executable: $python" }
    puts "KWT_HOST_PYTHON $python"
    return [eval [linsert $args 0 exec /usr/bin/env -u LD_LIBRARY_PATH -u LD_PRELOAD -u PYTHONHOME -u PYTHONPATH $python]]
}
proc require_file {path} {
    if {![file isfile $path]} { error "missing input: $path" }
}
proc corner_libs {corner} {
    global PDK SRAMDIR
    switch $corner {
        ss { set std ss_v0p99_125c; set ram ss_0p99v_0p99v_125c }
        ff { set std ff_v1p21_-40c; set ram ff_1p21v_1p21v_m40c }
        tt { set std tt_v1p1_25c; set ram tt_1p10v_1p10v_25c }
        default { error "unsupported corner $corner" }
    }
    set libs [list]
    foreach vt {HVT LVT RVT} {
        set lower [string tolower $vt]
        lappend libs $PDK/SCC40NLL_VHSC40_${vt}_V0.1/SCC40NLL_VHSC40_${vt}_V0p1/liberty/1.1v/scc40nll_vhsc40_${lower}_${std}_basic.db
    }
    lappend libs $SRAMDIR/RAMSP4096X16_${ram}.db
    foreach f $libs { require_file $f }
    return $libs
}
set rtl_files [list]
set fd [open $PROJECT/flow/rtl_sources.txt r]
foreach line [split [read $fd] \n] {
    set line [string trim $line]
    if {$line ne ""} { lappend rtl_files $PROJECT/$line }
}
close $fd
foreach f $rtl_files { require_file $f }
require_file $SDC
