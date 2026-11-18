"""Report remaining maximum-transition checks under the same reference setup."""
import json
import re
import subprocess

from local_tools import ROOT, sha


def main():
    base = ROOT / 'testdata/input16_rtl_20261105/p1_sizing_all'
    out = base.parent / 'p1_transition'
    out.mkdir()
    manifest = json.loads((base / 'manifest.json').read_text())
    for name in ('run.tcl', 'mapped_simple.v', 'blackboxes.v'):
        assert sha(base / name) == manifest[name], name
    rel = out.relative_to(ROOT).as_posix()
    text = (base / 'run.tcl').read_text()
    text = text[:text.index('check_setup')]
    text += f'report_check_types -max_transition -all_violators -digits 6 > {rel}/max_transition.txt\n'
    text += 'puts "DONE_TRANSITION"\nexit\n'
    (out / 'run.tcl').write_text(text)
    command = f'cd /mnt/e/project/ChipCompetition/keyword-transformer && tools/opensta_reference/root/usr/bin/sta -exit {rel}/run.tcl'
    result = subprocess.run(['wsl.exe', '-d', 'Ubuntu-24.04', '--', 'bash', '-lc', command], capture_output=True, text=True)
    log = result.stdout + result.stderr
    (out / 'execution.log').write_text(log)
    assert result.returncode == 0 and 'DONE_TRANSITION' in log and not re.search('^Error:', log, re.M), log[-2000:]
    violations = (out / 'max_transition.txt').read_text().count('(VIOLATED)')
    report = dict(passed=True, reference_max_transition_violators=violations,
                  complete_electrical_signoff=False, scope='ideal clock and standard-cell Liberty. No macro loads or route parasitics.')
    (out / 'verification.json').write_text(json.dumps(report, indent=2))
    (out / 'source_bindings.json').write_text(json.dumps({str(p.relative_to(ROOT)): sha(p) for p in
        [base / name for name in ('run.tcl', 'mapped_simple.v', 'blackboxes.v')]}, indent=2))
    (out / 'manifest.json').write_text(json.dumps({p.name: sha(p) for p in out.iterdir()}, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
