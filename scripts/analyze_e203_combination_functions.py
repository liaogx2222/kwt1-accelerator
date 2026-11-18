"""Exclusive shadow-IR PC attribution for the measured AC/ABC main windows."""
import argparse
import json
from pathlib import Path
from local_tools import ROOT, sha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    base, out = args.input.resolve(), args.output.resolve()
    assert not out.exists(), 'Use a fresh output directory'
    results, sources = {}, {}
    for group in ['compare_ac', 'compare_abc']:
        folder = base / group
        manifest = json.loads((folder / 'manifest.json').read_text())
        for name in ['firmware.nm', 'window_job_00.txt', 'summary.json']:
            path = folder / name
            assert sha(path) == manifest[name], path
            sources[path.relative_to(ROOT).as_posix()] = sha(path)
        symbols = []
        for line in (folder / 'firmware.nm').read_text().splitlines():
            address, kind, name = line.split()
            if kind.lower() == 't':
                symbols.append((int(address, 16), name))
        bins = {}
        for line in (folder / 'window_job_00.txt').read_text().splitlines():
            fields = line.split()
            if fields[:2] != ['pc', '0']:
                continue
            address, cycles, retired = map(int, fields[2:])
            name = max(symbol for symbol in symbols if symbol[0] <= address)[1]
            row = bins.setdefault(name, dict(cycles=0, retired=0))
            row['cycles'] += cycles
            row['retired'] += retired
        main_window = json.loads((folder / 'summary.json').read_text())['jobs'][0]['main']
        assert sum(row['cycles'] for row in bins.values()) == main_window['cycles']
        assert sum(row['retired'] for row in bins.values()) == main_window['retired']
        for row in bins.values():
            row['main_cycle_percent'] = 100 * row['cycles'] / main_window['cycles']
        results[group] = dict(sorted(bins.items(), key=lambda item: -item[1]['cycles']))
    report = dict(passed=True, groups=results, source_sha256=sources,
                  script_sha256=sha(Path(__file__)),
                  semantics='exclusive shadow-IR PC bins include stalls; not inclusive call latency, hardware utilization, or phase attribution')
    out.mkdir(parents=True)
    (out / 'function_comparison.json').write_text(json.dumps(report, indent=2))
    (out / 'manifest.json').write_text(json.dumps({p.name: sha(p) for p in out.iterdir()
                                                if p.is_file()}, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
