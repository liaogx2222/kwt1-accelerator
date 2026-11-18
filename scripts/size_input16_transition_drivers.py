"""Strengthen measured transition violators and repeat the original checks."""
import json
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha


def main():
    root = ROOT / 'testdata/input16_rtl_20261105'
    source = root / 'p1_sizing_all'
    violations = root / 'p1_transition/max_transition.txt'
    out = root / 'p1_sizing_electrical'
    out.mkdir()
    for path in [source / 'mapped_simple.v', source / 'run.tcl', source / 'blackboxes.v', violations]:
        assert sha(path) == json.loads((path.parent / 'manifest.json').read_text())[path.name], path

    library = ROOT / 'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    blocks = re.split(r'^\s*cell\s*\((\w+)\)\s*\{', library.read_text(), flags=re.M)
    cells = dict(zip(blocks[1::2], blocks[2::2]))
    targets = set(re.findall(r'^(_\d+_)/(?:Z|ZN|Q|QN)\s', violations.read_text(), re.M))
    swaps = {}

    def signature(cell):
        return (sorted(re.findall(r'\bpin\s*\((\w+)\)', cells[cell])),
                re.findall(r'\bfunction\s*:\s*"([^"]+)"', cells[cell]))

    def swap(match):
        old, instance = match.group(2, 3)
        if instance not in targets:
            return match[0]
        new = old[:-1] + {'1': '2', '2': '4'}[old[-1]]
        assert new in cells and signature(old) == signature(new) and signature(old)[1], (old, new)
        assert not re.search(r'\b(ff|latch)\s*\(', cells[old] + cells[new])
        swaps[instance] = (old, new)
        return f'{match[1]}{new} {instance} ('

    original = (source / 'mapped_simple.v').read_text()
    updated = re.sub(r'^([ \t]*)(\w+) (_\d+_) \(', swap, original, flags=re.M)
    assert targets == set(swaps) and swaps
    (out / 'mapped_simple.v').write_text(updated, newline='\n')
    (out / 'blackboxes.v').write_bytes((source / 'blackboxes.v').read_bytes())
    rel = out.relative_to(ROOT).as_posix()
    tcl = (source / 'run.tcl').read_text().replace(source.relative_to(ROOT).as_posix(), rel)
    assert tcl.endswith('exit\n')
    tcl = tcl[:-len('exit\n')] + f'report_check_types -max_transition -all_violators -digits 6 > {rel}/max_transition.txt\nexit\n'
    (out / 'run.tcl').write_text(tcl)
    command = f'cd /mnt/e/project/ChipCompetition/keyword-transformer && tools/opensta_reference/root/usr/bin/sta -exit {rel}/run.tcl'
    process = subprocess.run(['wsl.exe', '-d', 'Ubuntu-24.04', '--', 'bash', '-lc', command], capture_output=True, text=True)
    log = process.stdout + process.stderr
    (out / 'execution.log').write_text(log)
    assert process.returncode == 0 and 'DONE_REFERENCE_STA' in log and not re.search(r'^Error:', log, re.M), log[-2000:]

    def metric(name):
        return float(re.search('^' + name + r' (\S+)', log, re.M)[1])

    def area(name):
        return float(re.search(r'\barea\s*:\s*([\d.]+)', cells[name])[1])

    report = dict(swaps=len(swaps), swaps_by_instance=swaps, period_ns=6.666667,
                  area_increment_mm2=sum(area(new)-area(old) for old, new in swaps.values())*1e-6,
                  WNS_ns=metric('WNS'), TNS_ns=metric('TNS'), endpoints=int(metric('ENDPOINTS')),
                  negative_setup_endpoints=int(metric('NEGATIVE')),
                  max_transition_violators=(out / 'max_transition.txt').read_text().count('(VIOLATED)'),
                  complete_150MHz_signoff=False)
    (out / 'verification.json').write_text(json.dumps(report, indent=2))
    (out / 'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix(): sha(p) for p in
        [Path(__file__), source / 'mapped_simple.v', source / 'run.tcl', source / 'blackboxes.v', violations, library]}, indent=2))
    (out / 'manifest.json').write_text(json.dumps({p.name: sha(p) for p in out.iterdir()}, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != 'swaps_by_instance'}, indent=2))


if __name__ == '__main__':
    main()
