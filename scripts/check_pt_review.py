"""Installer/source preservation and Tcl control-flow tests, NOT actual STA."""
import argparse
import ast
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tkinter
import zlib
from pt_review_install import install

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True, type=Path)
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise ValueError('fresh output required')
    out.mkdir(parents=True)
    base = ROOT/'deliverables/rtl_v2_python_env_project_20261111/project'
    bundle = ROOT/'deliverables/pt_review_ready_20261111'
    meta = json.loads((bundle/'transfer_manifest.json').read_text())
    lines = (bundle/'commands.csh.txt').read_text().splitlines()
    parts = [re.search(r"write\('([^']+)'\)", line).group(1) for line in lines[:meta['parts']]]
    data = zlib.decompress(base64.b64decode(''.join(parts)))
    assert data == (bundle/'pt_review_fix.tar.gz').read_bytes()
    assert hashlib.sha256(data).hexdigest() == meta['sha256']
    project = out/'installed'
    shutil.copytree(base, project)
    dc = project/'build/dc'
    dc.mkdir(parents=True)
    net = dc/'mapped.v'
    net.write_text('module kwt1_mmio;\n'+'\n'.join('RAMSP4096X16 u%d();' % i for i in range(20))+'\nendmodule\n')
    (dc/'netlist_manifest.json').write_text(json.dumps(dict(
        source_manifest_sha256=sha(project/'manifest.json'), netlist_sha256=sha(net))))
    old_reports = project/'build/pt'
    old_reports.mkdir()
    (old_reports/'area_ss.rpt').write_text('preserve original PT failure')
    files = json.loads((project/'manifest.json').read_text())['files']
    before = {n: sha(project/n) for n in files}
    net_before = sha(net)
    capsule = bundle/'pt_review_fix'
    assert (capsule/'install.py').read_bytes() == (ROOT/'scripts/pt_review_install.py').read_bytes().replace(b'\r\n', b'\n')
    with contextlib.redirect_stdout(io.StringIO()):
        install(project, capsule)
        install(project, capsule)
    assert before == {n: sha(project/n) for n in files} and sha(net) == net_before
    assert (old_reports/'area_ss.rpt').read_text() == 'preserve original PT failure'
    for n, digest in meta['review_sha256'].items():
        assert sha(project/'review_tools'/n) == digest
    # Deliberately mocked tool commands test flow and error handling only.
    mock = out/'tcl_mock'
    (mock/'review_tools').mkdir(parents=True)
    (mock/'flow').mkdir()
    (mock/'build/dc').mkdir(parents=True)
    (mock/'build/dc/mapped.v').write_text('MOCK NETLIST')
    (mock/'flow/constraints.sdc').write_text('MOCK SDC')
    (mock/'flow/project.tcl').write_text('''
set PROJECT [file normalize [file join [file dirname [info script]] ..]]
set TOP kwt1_mmio
set SDC $PROJECT/flow/constraints.sdc
proc kwt_host_python {args} {return MOCK_SOURCE_CHECK}
proc require_file {p} {if {![file isfile $p]} {error "missing mock file $p"}}
proc corner_libs {c} {return [list MOCK_$c.db]}
''')
    for n in meta['review_sha256']:
        shutil.copyfile(project/'review_tools'/n, mock/'review_tools'/n)
    def interpreter(mode):
        t = tkinter.Tcl()
        t.setvar('MODE', mode)
        t.eval('''
set loaded 0
set remove_count 0
set update_count 0
set area_count 0
set qor_count 0
proc exit {{status 0}} {error MOCK_EXIT_$status}
proc set_app_var {args} {return 1}
proc get_designs {args} {if {$::loaded} {return design}; return {}}
proc sizeof_collection {x} {if {$x eq "macros"} {return 20}; return [llength $x]}
proc remove_design {args} {if {!$::loaded} {error EMPTY_REMOVE}; incr ::remove_count; set ::loaded 0}
proc read_verilog {args} {set ::loaded 1;return 1}
proc current_design {args} {if {!$::loaded} {error NO_DESIGN};return 1}
proc link_design {} {return 1}
proc link {} {return 1}
proc get_cells {args} {return macros}
proc read_sdc {args} {return 1}
proc update_timing {args} {incr ::update_count;return 1}
proc redirect {args} {
  if {[lindex $args 0] eq "-file"} {set args [lrange $args 1 end]}
  set f [open [lindex $args 0] w];puts $f MOCK_REPORT;close $f
  uplevel 1 [lindex $args 1]
}
proc report_timing {args} {return 1}
proc report_qor {} {incr ::qor_count;return 1}
proc check_timing {args} {return 1}
proc check_design {args} {return 1}
proc report_disable_timing {} {return 1}
proc report_analysis_coverage {} {return 1}
proc report_constraint {args} {return 1}
proc report_area {args} {if {$::MODE eq "PT"} {error FORBIDDEN_PT_AREA};incr ::area_count;return 1}
''')
        return t
    pt = interpreter('PT')
    script = mock/'review_tools/pt_review.tcl'
    try:
        pt.call('source', str(script))
    except tkinter.TclError as e:
        assert str(e) == 'MOCK_EXIT_0', str(e)
    else:
        raise AssertionError('mock PT exit missing')
    assert int(pt.getvar('remove_count')) == 2
    assert int(pt.getvar('update_count')) == 3 and int(pt.getvar('qor_count')) == 6
    assert int(pt.getvar('area_count')) == 0
    assert (mock/'build/pt_review1/complete').read_text().strip() == 'KWT_PT_REVIEW_REPORTS_DONE'
    assert all((mock/'build/pt_review1'/('timing_%s.rpt' % c)).exists() for c in ['ss', 'ff', 'tt'])
    prior = sha(mock/'build/pt_review1/timing_ss.rpt')
    repeat = interpreter('PT')
    try:
        repeat.call('source', str(script))
    except tkinter.TclError as e:
        assert str(e) == 'MOCK_EXIT_1', str(e)
    assert sha(mock/'build/pt_review1/timing_ss.rpt') == prior
    assert int(repeat.getvar('update_count')) == 0
    failure_script = mock/'review_tools/pt_failure_mock.tcl'
    failure_script.write_text(script.read_text().replace('build/pt_review1', 'build/pt_failure_mock'))
    failure = interpreter('PT')
    failure.eval('proc report_qor {} {error SIMULATED_REPORT_FAILURE}')
    try:
        failure.call('source', str(failure_script))
    except tkinter.TclError as e:
        assert str(e) == 'MOCK_EXIT_1', str(e)
    assert not (mock/'build/pt_failure_mock/complete').exists()
    assert not (mock/'build/pt_failure_mock/timing_ff.rpt').exists()
    dc_tcl = interpreter('DC')
    try:
        dc_tcl.call('source', str(mock/'review_tools/dc_mapped_review.tcl'))
    except tkinter.TclError as e:
        assert str(e) == 'MOCK_EXIT_0', str(e)
    assert int(dc_tcl.getvar('area_count')) == 1
    assert (mock/'build/dc_mapped_review1/check_design_full.rpt').exists()
    ast.parse((capsule/'install.py').read_text(), feature_version=(3, 6))
    result = dict(passed=True, source_59_files_unchanged=True, netlist_unchanged=True,
        original_PT_preserved=True, idempotent_installer=True, transport_reconstruction=True,
        mock_Tcl_three_corners=True, initial_empty_remove_avoided=True, no_PT_report_area=True,
        existing_report_directory_refused=True, report_failure_stops_without_completion=True,
        post_mapping_DC_flow_mocked=True,
        python36_syntax=True, actual_DC_PT_executed=False, actual_SoC_VCS_pass=False)
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
