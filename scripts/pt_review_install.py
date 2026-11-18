"""Python 3.6: create independent PT/DC review entries without editing production."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_pt(original):
    substitutions = [
        ('[file join [file dirname [info script]] project.tcl]',
         '[file join [file dirname [info script]] .. flow project.tcl]'),
        ('set OUT $PROJECT/build/pt', 'set OUT $PROJECT/build/pt_review1'),
        ('if {[file exists $OUT/complete]}', 'if {[file exists $OUT]}'),
        ('    remove_design -all',
         '    if {[sizeof_collection [get_designs -quiet *]] > 0} { remove_design -all }'),
        ('redirect $OUT/area_$corner.rpt { report_area }',
         'redirect $OUT/area_$corner.rpt { report_qor }'),
        ('report_timing -delay_type max -max_paths 20',
         'report_timing -significant_digits 6 -delay_type max -max_paths 20'),
        ('report_timing -delay_type min -max_paths 20',
         'report_timing -significant_digits 6 -delay_type min -max_paths 20'),
        ('puts stderr "KWT_FATAL $kwt_failure"',
         'puts stderr "KWT_FATAL $kwt_failure"\n    puts stderr $::errorInfo')]
    text = original
    for before, after in substitutions:
        if text.count(before) != 1:
            raise ValueError('unexpected original PT source: '+before)
        text = text.replace(before, after)
    text = text.replace('KWT_CLEAN_PT_DONE', 'KWT_PT_REVIEW_REPORTS_DONE')
    lines = []
    for line in text.splitlines():
        if line.strip().startswith('redirect $OUT/'):
            indent = line[:len(line)-len(line.lstrip())]
            target = line.strip().split()[1]
            lines.append(indent+'puts "KWT_REVIEW_REPORT '+target+'"')
        lines.append(line)
    return '\n'.join(lines)+'\n'


def make_dc():
    return '''# Read-only mapped-netlist design/constraint review. No compile/ECO/write.
if {[catch {
set fd [open [file join [file dirname [info script]] .. flow project.tcl] r]
set config [read $fd]
close $fd
eval $config
puts [kwt_host_python $PROJECT/flow/project.py check-dc]
puts [kwt_host_python $PROJECT/flow/project.py preflight]
set OUT $PROJECT/build/dc_mapped_review1
if {[file exists $OUT]} { error "preserve existing mapped review" }
file mkdir $OUT
set libs [corner_libs ss]
set_app_var target_library $libs
set_app_var link_library [concat "*" $libs]
read_verilog $PROJECT/build/dc/mapped.v
current_design $TOP
if {![link]} { error "mapped DC link failed" }
set n [sizeof_collection [get_cells -hierarchical -filter "ref_name =~ RAMSP4096X16*" -quiet]]
if {$n != 20} { error "mapped macro count changed" }
puts "KWT_DC_REVIEW_MACROS $n"
read_sdc $SDC
redirect -file $OUT/check_design_full.rpt { check_design }
redirect -file $OUT/setup.rpt { report_timing -significant_digits 6 -delay_type max -max_paths 10 -nosplit }
redirect -file $OUT/hold.rpt { report_timing -significant_digits 6 -delay_type min -max_paths 10 -nosplit }
redirect -file $OUT/constraints.rpt { report_constraint -all_violators -verbose }
redirect -file $OUT/area.rpt { report_area -hierarchy }
puts "KWT_DC_MAPPED_REVIEW_REPORTS_DONE"
} failure]} {
puts stderr "KWT_FATAL $failure"
puts stderr $::errorInfo
exit 1
}
exit
'''


def make_runner():
    return '''#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Set LC only in this child process if a real executable is available on PATH.
LC_EXE=$(command -v lc_shell || true)
if [[ -n "$LC_EXE" && -x "$LC_EXE" && "$LC_EXE" == */bin/lc_shell ]]; then
  export SYNOPSYS_LC_ROOT="${LC_EXE%/bin/lc_shell}"
  echo "KWT_REVIEW_LC_ROOT $SYNOPSYS_LC_ROOT"
else
  echo "KWT_REVIEW_LC_NOT_DISCOVERED: retain any PT-063 diagnostic for review"
fi
unset KWT_GATE_SAIF
exec /eda/synopsys/prime/prime_2022.03-SP5-1/bin/pt_shell -f review_tools/pt_review.tcl
'''


def install(project, capsule):
    project = project.resolve()
    metadata = json.loads((capsule/'metadata.json').read_text())
    raw = (project/'manifest.json').read_bytes()
    if sha(raw) != metadata['source_manifest_sha256']:
        raise SystemExit('REVIEW_SOURCE_MANIFEST_MISMATCH')
    m = json.loads(raw)
    failures = [n for n, row in m['files'].items()
                if not (project/n).is_file() or sha((project/n).read_bytes()) != row['sha256']]
    if failures:
        raise SystemExit('REVIEW_SOURCE_MISMATCH '+', '.join(failures[:8]))
    p = subprocess.run([sys.executable, str(project/'flow/project.py'), 'check-dc'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if p.returncode or 'KWT_NETLIST_VERIFIED ' not in p.stdout:
        raise SystemExit('REVIEW_NETLIST_REJECTED\n'+p.stdout+p.stderr)
    planned = {'pt_review.tcl': make_pt((project/'flow/pt.tcl').read_text()).encode(),
               'dc_mapped_review.tcl': make_dc().encode(), 'run_pt_review.sh': make_runner().encode()}
    if {n: sha(b) for n, b in planned.items()} != metadata['review_sha256']:
        raise SystemExit('REVIEW_GENERATED_TOOL_MISMATCH')
    out = project/'review_tools'
    for name, data in planned.items():
        if (out/name).exists() and (out/name).read_bytes() != data:
            raise SystemExit('REVIEW_REFUSE_OVERWRITE '+name)
    out.mkdir(exist_ok=True)
    for name, data in planned.items():
        (out/name).write_bytes(data)
    print(p.stdout.strip())
    print('REVIEW_TOOLS_INSTALLED source_unchanged=1 netlist_unchanged=1 original_PT_preserved=1')


if __name__ == '__main__':
    install(Path.cwd(), Path(__file__).resolve().parent)
