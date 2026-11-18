"""Build or verify the designated-technology signoff metrics ledger.

Fail closed: a metric becomes a number only when every required input exists and
is qualified. Otherwise it stays null with an explicit missing-item list.
This replaces build_full_scope_metrics.py for signoff; that script hard-codes
the three metrics to None and must not be used as evidence of completion.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT.parent / 'docs/architecture/METRICS_SCOPE_AND_REPORTING_20261105.json'
KEYS = ('throughput_tasks_per_second', 'SoC_average_power_mW', 'complete_counted_area_mm2')
OUTPUT_FILES = ('metrics.json', 'verification.json', 'source_bindings.json', 'manifest.json')
POWER_COMPONENTS = ('E203', 'accelerator', 'interconnect', 'private_SRAM', 'shared_512KiB_SRAM')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path):
    p = Path(path).resolve()
    try:
        return os.path.relpath(p, ROOT).replace('\\', '/')
    except ValueError:
        # Different drive/mount: bind the absolute path so --check can still resolve it.
        return p.as_posix()


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def source_ok(path, sources, missing, label):
    """A referenced evidence file must exist and be hash-bound."""
    if not path:
        missing.append(label + ': missing source reference')
        return False
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.is_file():
        missing.append(label + ': source file not found: ' + str(path))
        return False
    sources.add(p.resolve())
    return True


def evaluate_throughput(cfg, qual, sources):
    missing = []
    t = cfg.get('throughput') or {}
    wns = qual.get('wns_ns')
    freq = qual.get('frequency_hz')
    unconstrained = qual.get('unconstrained_endpoints')
    corners = qual.get('pvt_corners') or []
    if not positive(t.get('total_cycles')):
        missing.append('throughput: same-window total cycle count from designated SoC')
    if not positive(t.get('tasks')):
        missing.append('throughput: number of tasks in the same window')
    if not positive(freq):
        missing.append('qualification: qualified operating frequency')
    if not isinstance(wns, (int, float)) or isinstance(wns, bool) or wns < 0:
        missing.append('qualification: WNS >= 0 at 150 MHz in every bound corner')
    if unconstrained != 0:
        missing.append('qualification: zero unconstrained timing endpoints')
    if not corners:
        missing.append('qualification: bound PVT corner list')
    if t.get('platform_diff_signed') is not True:
        missing.append('throughput: signed reference-vs-designated platform difference table')
    if not source_ok(t.get('timing_source'), sources, missing, 'throughput'):
        pass
    if not source_ok(qual.get('timing_source'), sources, missing, 'qualification'):
        pass
    if not source_ok(qual.get('functional_verification'), sources, missing, 'functional verification'):
        pass
    if not source_ok(qual.get('mapped_netlist'), sources, missing, 'mapped netlist'):
        pass
    value = None
    if not missing:
        value = t['tasks'] / (t['total_cycles'] / freq)
    return value, missing


def evaluate_power(cfg, sources):
    missing = []
    p = cfg.get('power') or {}
    components = p.get('components') or {}
    if not positive(p.get('average_mW')):
        missing.append('power: same-window SoC average power in mW')
    for name in POWER_COMPONENTS:
        entry = components.get(name) or {}
        for kind in ('dynamic_mW', 'static_mW'):
            if entry.get(kind) is None:
                missing.append('power: ' + name + '.' + kind)
    if p.get('activity_window_same') is not True:
        missing.append('power: same-window SAIF/VCD activity for the same netlist and corner')
    unannotated = p.get('unannotated') or []
    if unannotated:
        missing.append('power: unannotated activity must be null, never zero: ' + ', '.join(map(str, unannotated)))
    if not source_ok(p.get('source'), sources, missing, 'power'):
        pass
    if not source_ok(p.get('activity_source'), sources, missing, 'activity'):
        pass
    value = None if missing else p['average_mW']
    return value, missing


def evaluate_area(cfg, sources):
    missing = []
    a = cfg.get('area') or {}
    std = a.get('standard_cell_mm2')
    per = a.get('macro_area_per_instance_um2')
    count = a.get('macro_instances')
    if not positive(std):
        missing.append('area: complete mapped standard-cell area including all new interface logic')
    if not positive(per):
        missing.append('area: characterized macro area per instance in um^2')
    if count != 20:
        missing.append('area: exactly 20 private SRAM macro instances')
    if a.get('interface_included') is not True:
        missing.append('area: confirmation that new interface logic is included and not double counted')
    if a.get('reused_reported_separately') is not True:
        missing.append('area: reused E203 / shared 512KiB / fixed bus reported separately')
    if not source_ok(a.get('source'), sources, missing, 'area'):
        pass
    value = None
    if not missing:
        value = std + count * per / 1e6
    return value, missing


def build(args):
    inp = Path(args.input).resolve()
    out = Path(args.output).resolve()
    if out.exists():
        raise SystemExit('refusing to overwrite existing output directory: ' + str(out))
    cfg = json.loads(inp.read_text(encoding='utf-8'))
    policy = json.loads(POLICY.read_text(encoding='utf-8'))
    assert policy['same_frozen_configuration_required'] and policy['missing_component_must_not_be_zero']
    assert policy['partial_partition_area_is_not_scoring_area']
    if cfg.get('accuracy', {}).get('official_600') is not False:
        raise SystemExit('official_600 must be false until the organizer publishes the 600-sample evaluation')

    qual = cfg.get('qualification') or {}
    sources = {inp, POLICY, Path(__file__).resolve()}
    throughput, m_t = evaluate_throughput(cfg, qual, sources)
    power, m_p = evaluate_power(cfg, sources)
    area, m_a = evaluate_area(cfg, sources)
    values = dict(zip(KEYS, (throughput, power, area)))
    complete = all(v is not None for v in values.values())

    metrics = dict(
        schema='designated_technology_signoff_metrics_v1',
        configuration=cfg.get('configuration'),
        supersedes=cfg.get('supersedes', []),
        policy=policy,
        values=values,
        throughput_tasks_per_second=throughput,
        SoC_average_power_mW=power,
        complete_counted_area_mm2=area,
        missing_for_complete_throughput=m_t,
        missing_for_complete_power=m_p,
        missing_for_complete_area=m_a,
        complete_scoring_PPA_available=complete,
        qualification=dict(
            frequency_hz=qual.get('frequency_hz'),
            wns_ns=qual.get('wns_ns'),
            unconstrained_endpoints=qual.get('unconstrained_endpoints'),
            pvt_corners=qual.get('pvt_corners'),
            timing_source=qual.get('timing_source'),
            note='Nangate45 reference WNS +0.5940746 ns and the 431-buffer reset tree are NOT inherited.'),
        accuracy=dict(official_600=False, accuracy_eligible=False,
                      note='Reference platform has no official 600-sample evaluation; qualification is open, no efficiency or innovation score is claimed.'),
        area_limit_mm2=2.25,
        area_within_limit=None if area is None else area <= 2.25,
        area_scope=dict(counted=['complete new accelerator standard cells', 'all newly added interface logic', 'all private SRAM macro instances'],
                        reported_separately=['reused E203', 'fixed 512KiB shared SRAM', 'fixed bus and peripherals']),
        isolation=dict(compact_candidate='compact-e203-softmax-radix4-v2',
                       rule='Compact partition results and the trim2 reference must not share performance, power or area totals (manifest/compact_lineage_20261106.json:148).'),
        source_exceptions=dict(SOURCE_E01='OPEN', LN_E01='fixed profile exception retained'))
    verification = dict(passed=complete, mandatory_metric_keys_present=True,
                        missing_metrics_explicit_null=not complete,
                        complete_scoring_PPA_available=complete,
                        official_600=False,
                        partial_results_never_substituted_for_required_metrics=True)

    # Serialize everything in memory first: a failure must never leave a partial ledger.
    def sha_text(text):
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    texts = {
        'metrics.json': json.dumps(metrics, indent=2, ensure_ascii=False),
        'verification.json': json.dumps(verification, indent=2, ensure_ascii=False),
        'source_bindings.json': json.dumps({rel(p): sha(p) for p in sorted(sources, key=lambda x: str(x))},
                                           indent=2, ensure_ascii=False),
    }
    texts['manifest.json'] = json.dumps({f: sha_text(t) for f, t in texts.items()},
                                        indent=2, ensure_ascii=False)
    out.mkdir(parents=True)
    for name, text in texts.items():
        # Explicit newline keeps the byte-level hashes identical on Windows and Linux.
        with (out / name).open('w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
    print(json.dumps(dict(output=str(out), complete_scoring_PPA_available=complete,
                          values=values, missing=dict(throughput=m_t, power=m_p, area=m_a)),
                     indent=2, ensure_ascii=False))
    return 0 if complete else 2


def safe_sha(path):
    try:
        return sha(path)
    except OSError:
        return None


def check(args):
    out = Path(args.output).resolve()
    problems = []
    for f in OUTPUT_FILES:
        if not (out / f).is_file():
            problems.append('missing output file: ' + f)
    if problems:
        print(json.dumps(dict(passed=False, problems=problems), indent=2))
        return 2
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    expected = set(OUTPUT_FILES) - {'manifest.json'}
    if set(manifest) != expected:
        problems.append('manifest key set must be exactly ' + ', '.join(sorted(expected)))
    for name, digest in manifest.items():
        if name not in expected or safe_sha(out / name) != digest:
            problems.append('manifest hash mismatch: ' + name)
    bindings = json.loads((out / 'source_bindings.json').read_text(encoding='utf-8'))
    for name, digest in bindings.items():
        p = Path(name)
        if not p.is_absolute():
            p = ROOT / p
        if not p.is_file() or safe_sha(p) != digest:
            problems.append('source binding broken: ' + name)
    m = json.loads((out / 'metrics.json').read_text(encoding='utf-8'))
    v = json.loads((out / 'verification.json').read_text(encoding='utf-8'))
    for key in KEYS:
        if key not in m:
            problems.append('missing mandatory key: ' + key)
        elif m[key] is None and not m['missing_for_complete_' + {'throughput_tasks_per_second': 'throughput', 'SoC_average_power_mW': 'power', 'complete_counted_area_mm2': 'area'}[key]]:
            problems.append('null metric without a missing-item list: ' + key)
    if m.get('accuracy', {}).get('official_600') is not False:
        problems.append('official_600 must remain false without organizer evaluation')
    if m.get('accuracy', {}).get('accuracy_eligible') is not False:
        problems.append('accuracy_eligible must remain false without organizer evaluation')
    if v.get('official_600') is not False:
        problems.append('verification.official_600 must remain false')
    if v.get('complete_scoring_PPA_available') != m.get('complete_scoring_PPA_available'):
        problems.append('verification/metrics disagreement on complete_scoring_PPA_available')
    if m.get('complete_scoring_PPA_available'):
        if any(m[k] is None for k in KEYS):
            problems.append('complete_scoring_PPA_available=true with a null metric')
        wns = m.get('qualification', {}).get('wns_ns')
        if not isinstance(wns, (int, float)) or isinstance(wns, bool) or wns < 0:
            problems.append('PPA marked complete but WNS is negative or absent')
    print(json.dumps(dict(passed=not problems, problems=problems,
                          complete_scoring_PPA_available=m.get('complete_scoring_PPA_available')),
                     indent=2, ensure_ascii=False))
    return 0 if not problems else 2


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, help='server-side signoff_inputs.json')
    ap.add_argument('--output', type=Path, required=True, help='fresh output directory (build) or existing ledger (--check)')
    ap.add_argument('--check', action='store_true', help='verify an existing ledger, fail closed')
    a = ap.parse_args()
    if a.check:
        return check(a)
    if not a.input:
        ap.error('--input is required unless --check is used')
    return build(a)


if __name__ == '__main__':
    sys.exit(main())
