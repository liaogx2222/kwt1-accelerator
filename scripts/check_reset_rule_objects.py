"""Typed Tcl collection regression for UID-91 and silent tool return=0.

Mocks model object eligibility and status returns, not actual Synopsys timing.
"""
import argparse
import json
from pathlib import Path
import tkinter

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise ValueError('fresh output required')
    out.mkdir(parents=True)
    results = {}
    for mode in ['normal', 'fanout_zero', 'transition_zero', 'wrong_design_object', 'mapped_rename', 'final_rename', 'preflight', 'missing_anchor', 'small_mapped_cone', 'missing_named_reset', 'unknown_stage']:
        t = tkinter.Tcl()
        t.setvar('mode', mode)
        stage = {'mapped_rename': 'mapped', 'final_rename': 'final', 'preflight': 'mapped_contract_preflight', 'missing_anchor': 'mapped_contract_preflight', 'small_mapped_cone': 'mapped', 'unknown_stage': 'typo'}.get(mode, 'elaborated')
        t.eval('''
set TOP kwt1_mmio
set objects [dict create kwt1_mmio {design none} rst_n {port in} abort_hw {port in} root/Y {pin out} req_ready {port out} load/RN {pin in}]
set cone {root/Y req_ready load/RN}
for {set i 0} {$i < 1100} {incr i} {
  set name buf$i/Y
  dict set objects $name {pin out}
  lappend cone $name
}
set fanout_called 0
set transition_called 0
set target_names {}
set named_queries 0
set anchor_queries 0
proc get_nets {args} {
 incr ::named_queries
 if {$::mode in {mapped_rename final_rename missing_named_reset}} {return {}}
 return reset_net
}
proc get_ports {args} {
 incr ::anchor_queries
 if {$::mode eq "missing_anchor"} {return rst_n}
 return {rst_n abort_hw}
}
proc get_pins {args} {return root/Y}
proc sizeof_collection {x} {return [llength $x]}
proc all_fanout {args} {
 if {$::mode eq "small_mapped_cone"} {return [lrange $::cone 0 9]}
 return $::cone
}
proc get_designs {args} {
  if {$::mode eq "wrong_design_object"} {return req_ready}
  return kwt1_mmio
}
proc filter_collection {collection query} {
  if {$query ne {object_class != design}} {error UNKNOWN_FILTER}
  set result {}
  foreach item $collection {
    if {[lindex [dict get $::objects $item] 0] ne "design"} {lappend result $item}
  }
  return $result
}
proc set_max_fanout {value targets} {
  incr ::fanout_called
  set ::target_names $targets
  foreach item $targets {
    lassign [dict get $::objects $item] class direction
    if {$class ne "design"} {error UNSUPPORTED_TARGET}
  }
  if {$value != 32} {error WRONG_LIMIT}
  return [expr {$::mode ne "fanout_zero"}]
}
proc set_max_transition {value targets} {
  incr ::transition_called
  if {$value != 0.400} {error WRONG_LIMIT}
  return [expr {$::mode ne "transition_zero"}]
}
''')
        t.call('source', (ROOT/'flow/clean/reset_rules.tcl').as_posix())
        failed = False
        message = ''
        try:
            t.call('kwt_reset_distribution_rules', stage)
        except tkinter.TclError as e:
            failed = True
            message = str(e)
        assert failed == (mode not in ['normal', 'mapped_rename', 'final_rename', 'preflight']), (mode, message)
        names = t.splitlist(t.getvar('target_names'))
        if mode in ['normal', 'fanout_zero', 'transition_zero', 'mapped_rename', 'final_rename', 'preflight']:
            assert 'req_ready' not in names and 'load/RN' not in names
            assert names == ('kwt1_mmio',), names
        if mode in ['wrong_design_object', 'missing_anchor', 'small_mapped_cone', 'missing_named_reset', 'unknown_stage']:
            assert int(t.getvar('fanout_called')) == 0
        if mode == 'fanout_zero':
            assert 'set_max_fanout failed' in message and int(t.getvar('transition_called')) == 0
        if mode == 'transition_zero':
            assert 'set_max_transition failed' in message
        if stage in ['mapped', 'final', 'mapped_contract_preflight']:
            assert int(t.getvar('named_queries')) == 0
            assert int(t.getvar('anchor_queries')) == 1
        results[mode] = dict(stage=stage, failed=failed, message=message, targets=len(names))
    report = dict(passed=True, typed_collection_cases=results,
        top_output_port_excluded=True, input_load_pin_excluded=True,
        mapped_rename_tolerated=True, missing_interface_rejected=True, documented_design_target_only=True, constraint_scope="whole_accelerator_design", silent_zero_rejected=True, actual_DC_executed=False)
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
