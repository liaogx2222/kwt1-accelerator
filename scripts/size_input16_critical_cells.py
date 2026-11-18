"""Trial same-function Nangate drive strengths on the measured residual path."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['all', 'even', 'odd'], required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True)
    base = ROOT / 'testdata/input16_rtl_20261105/p1_reset12_fixed_sta'
    net = base / 'mapped_simple.v'
    library = ROOT / 'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    manifest = json.loads((base / 'manifest.json').read_text())
    for name in ('mapped_simple.v', 'setup_paths.txt', 'run.tcl'):
        assert sha(base / name) == manifest[name], name

    def cells(text):
        blocks = re.split(r'^\s*cell\s*\((\w+)\)\s*\{', text, flags=re.M)
        return dict(zip(blocks[1::2], blocks[2::2]))

    def signature(text):
        pins = sorted(re.findall(r'\bpin\s*\((\w+)\)', text))
        functions = re.findall(r'\bfunction\s*:\s*"([^"]+)"', text)
        return pins, functions

    lib = cells(library.read_text())
    reports = (base / 'setup_paths.txt').read_text().split('Startpoint:')
    sequence = {}
    for path in reports:
        if 'slack (VIOLATED)' not in path:
            continue
        for name, old in re.findall(r'(_\d+_)/(?:Z|ZN)\s+\((\w+)\)', path):
            if old.endswith('_X1') and old[:-1] + '2' in lib:
                sequence[name] = old
    changes = {}
    for index, (name, old) in enumerate(sequence.items()):
        if args.mode != 'all' and index % 2 != (args.mode == 'odd'):
            continue
        new = old[:-1] + '2'
        sig = signature(lib[old])
        assert sig[1] and sig == signature(lib[new]), (old, new)
        assert not re.search(r'\b(ff|latch)\s*\(', lib[old] + lib[new])
        changes[name] = (old, new)
    found = set()

    def replace(match):
        old, name = match.group(2, 3)
        if name not in changes:
            return match[0]
        assert old == changes[name][0]
        found.add(name)
        return f'{match[1]}{changes[name][1]} {name} ('

    sized = re.sub(r'^([ \t]*)(\w+) (_\d+_) \(', replace, net.read_text(), flags=re.M)
    assert found == set(changes) and changes
    (out / 'mapped_simple.v').write_text(sized, newline='\n')
    rel = out.relative_to(ROOT).as_posix()
    previous = base.relative_to(ROOT).as_posix()
    tcl = (base / 'run.tcl').read_text().replace(previous, rel)
    (out / 'blackboxes.v').write_bytes((base / 'blackboxes.v').read_bytes())
    (out / 'run.tcl').write_text(tcl)
    cmd = f'cd /mnt/e/project/ChipCompetition/keyword-transformer && tools/opensta_reference/root/usr/bin/sta -exit {rel}/run.tcl'
    result = subprocess.run(['wsl.exe', '-d', 'Ubuntu-24.04', '--', 'bash', '-lc', cmd], capture_output=True, text=True)
    log = result.stdout + result.stderr
    (out / 'execution.log').write_text(log)
    assert result.returncode == 0 and 'DONE_REFERENCE_STA' in log and not re.search(r'^Error:', log, re.M), log[-2000:]

    def metric(name):
        return float(re.search('^' + name + r' (\S+)', log, re.M)[1])

    def area(name):
        return float(re.search(r'\barea\s*:\s*([\d.]+)', lib[name])[1])

    report = dict(mode=args.mode, swaps=len(changes), swaps_by_instance=changes,
                  function_and_pin_signatures_equal=True, area_increment_mm2=sum(area(new)-area(old) for old, new in changes.values())*1e-6,
                  period_ns=6.666667, reference_reg2reg_WNS_ns=metric('WNS'), reference_reg2reg_TNS_ns=metric('TNS'),
                  setup_endpoints_analyzed=int(metric('ENDPOINTS')), negative_setup_endpoints=int(metric('NEGATIVE')),
                  complete_150MHz_signoff=False)
    (out / 'verification.json').write_text(json.dumps(report, indent=2))
    (out / 'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix(): sha(p) for p in
        [Path(__file__), net, library, base / 'setup_paths.txt', base / 'run.tcl', base / 'blackboxes.v']}, indent=2))
    (out / 'manifest.json').write_text(json.dumps({p.name: sha(p) for p in out.iterdir()}, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != 'swaps_by_instance'}, indent=2))


if __name__ == '__main__':
    main()
