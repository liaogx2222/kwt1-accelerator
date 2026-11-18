# Diagnose the real reset cone, then apply documented design-level DRC rules.
# No timing exceptions, no reset false path, no pipeline/state change.
# set_max_fanout supports input ports/designs, not arbitrary fanout pins.
proc kwt_reset_distribution_rules {stage} {
    global TOP
    if {$stage eq "elaborated"} {
        set nets [get_nets -hierarchical *task_rst_n* -quiet]
        if {[sizeof_collection $nets] == 0} { error "task reset net missing at $stage" }
        set roots [get_pins -of_objects $nets -filter "direction == out" -quiet]
        if {[sizeof_collection $roots] == 0} { error "task reset driver missing at $stage" }
        set basis named_task_reset
        set cone [all_fanout -from $roots -flat]
    } elseif {$stage in {mapped_contract_preflight mapped final}} {
        # Internal names can disappear during mapping. These top ports are an
        # immutable interface contract; this is a diagnostic, not a false path.
        set roots [get_ports -quiet {rst_n abort_hw}]
        if {[sizeof_collection $roots] != 2} { error "reset/abort interface anchors missing at $stage" }
        set basis interface_ports
        set cone [all_fanout -from $roots -flat -endpoints_only]
    } else {
        error "unknown reset rule stage: $stage"
    }
    set n [sizeof_collection $cone]
    puts "KWT_RESET_RULES $stage basis=$basis roots=[sizeof_collection $roots] cone=$n"
    if {$n < 1000} { error "task reset cone unexpectedly small at $stage" }
    set targets [get_designs $TOP -quiet]
    set bad [filter_collection $targets {object_class != design}]
    if {[sizeof_collection $targets] != 1 || [sizeof_collection $bad] != 0} {
        error "invalid design constraint target collection at $stage"
    }
    puts "KWT_RESET_LEGAL_TARGETS $stage scope=whole_accelerator_design targets=1 invalid=0"
    # A broader, stricter DRC is intentional; measure its area/timing cost anew.
    # Synopsys can print Error and return 0 without throwing a Tcl exception.
    if {![set_max_fanout 32 $targets]} { error "set_max_fanout failed at $stage" }
    if {![set_max_transition 0.400 $targets]} { error "set_max_transition failed at $stage" }
}
