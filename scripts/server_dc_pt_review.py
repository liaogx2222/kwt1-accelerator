"""Python 3.6 read-only evidence review; never turns partial reports into PASS.

Run from the accelerator project. Without --output this only reads files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review(root, pt_run='pt'):
    root = root.resolve()
    if not re.match(r'^(?:pt|pt_review[0-9]+)$', pt_run):
        raise ValueError('PT run must be pt or pt_review<number>')
    manifest_path = root/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    source_bad = [n for n, row in manifest['files'].items()
                  if not (root/n).is_file() or sha(root/n) != row['sha256']]
    paths = {'dc': root/'build/dc.console.log', 'pt': root/('build/'+pt_run+'.console.log')}
    logs = {k: p.read_text(errors='replace') if p.is_file() else '' for k, p in paths.items()}
    result = dict(scope='accelerator partition only', source_revision=manifest.get('git_revision'),
                  source_files=len(manifest['files']), source_mismatches=source_bad,
                  source_manifest_sha256=sha(manifest_path), tools={}, reports={},
                  verdict='REVIEW_REQUIRED', physical_signoff=False)
    for tool, text in logs.items():
        lines = text.splitlines()
        error_indices = [i for i, line in enumerate(lines) if re.match(r'^\s*Error:', line)]
        fatals = [line for line in lines if re.match(r'^KWT_FATAL\b', line)]
        # Only actual output lines; never accept echoed Tcl puts as a receipt.
        marker = ('KWT_CLEAN_SYNTH_DONE' if tool == 'dc' else
                  'KWT_CLEAN_PT_DONE' if pt_run == 'pt' else 'KWT_PT_REVIEW_REPORTS_DONE')
        finished = any(line.strip() == marker for line in lines)
        summary = [line for line in lines if 'Diagnostics summary:' in line]
        summary_errors = sum(int(m.group(1)) for line in summary
                             for m in [re.search(r'(\d+) errors?', line)] if m)
        context = []
        for i in error_indices[:5]:
            context.append('\n'.join('%d: %s' % (j+1, lines[j]) for j in range(max(0, i-3), min(len(lines), i+9))))
        blackbox = [line for line in lines if re.search(r'Unable to resolve reference|Creating black box|unresolved reference', line, re.I)]
        result['tools'][tool] = dict(log_present=paths[tool].is_file(),
            log_sha256=sha(paths[tool]) if paths[tool].is_file() else None,
            actual_completion_marker=finished, error_lines=[lines[i] for i in error_indices],
            fatal_lines=fatals, diagnostics_summary=summary, summary_errors=summary_errors,
            first_error_context=context, unresolved_or_blackbox_lines=blackbox,
            macro_lines=[line for line in lines if re.match(r'^KWT_(?:PT_MACROS|MAPPED_MACRO_INSTANCES)\b', line)],
            disabled_arc_warnings=[line for line in lines if 'PTE-003' in line])
    net = root/'build/dc/mapped.v'
    if net.is_file():
        text = re.sub(r'/\*.*?\*/|//[^\n]*', '', net.read_text(errors='replace'), flags=re.S)
        generic = sorted(set(re.findall(r'\b(?:GTECH\w*|SELECT_OP\w*)\b', text)))
        macros = len(re.findall(r'^\s*RAMSP4096X16\s+', text, re.M))
        receipt = root/'build/dc/netlist_manifest.json'
        recorded = json.loads(receipt.read_text()) if receipt.is_file() else {}
        expected = dict(source_manifest_sha256=sha(manifest_path), netlist_sha256=sha(net))
        result['netlist'] = dict(bytes=net.stat().st_size, sha256=sha(net), private_macros=macros,
                                 generic_cells=generic, receipt_matches=recorded == expected)
    report_paths = [root/'build/dc/reports'/n for n in
                    ['check_design.rpt', 'area.rpt', 'setup.rpt', 'hold.rpt', 'constraints.rpt']]
    report_paths += [root/'build'/pt_run/('%s_%s.rpt' % (kind, corner))
                     for corner in ['ss', 'ff', 'tt']
                     for kind in ['timing', 'check_timing', 'coverage', 'constraints', 'area']]
    for p in report_paths:
        text = p.read_text(errors='replace') if p.is_file() else ''
        interesting = [line for line in text.splitlines() if re.search(
            r'Total cell area|Macro/Black Box area|Critical Path Slack|Total Negative Slack|No\. of Violating Paths|'
            r'slack \(|VIOLATED|unconstrained|no_clock|not tested|untested|not analyzed|disabled|loop|Error:', line, re.I)]
        result['reports'][p.relative_to(root).as_posix()] = dict(present=p.is_file(),
            bytes=p.stat().st_size if p.is_file() else 0, sha256=sha(p) if p.is_file() else None,
            review_lines=interesting[:80], review_lines_total=len(interesting),
            error_lines=[line for line in text.splitlines() if re.match(r'^\s*Error:', line)])
    netlist_bad = ('netlist' not in result or result['netlist']['private_macros'] != 20 or
                   result['netlist']['generic_cells'] or not result['netlist']['receipt_matches'])
    redirected_errors = any(r['error_lines'] for r in result['reports'].values())
    if source_bad or netlist_bad or redirected_errors or any(not t['actual_completion_marker'] or t['error_lines'] or t['fatal_lines'] or t['summary_errors'] or
                         t['unresolved_or_blackbox_lines'] for t in result['tools'].values()):
        result['verdict'] = 'FAILED_OR_INCOMPLETE'
    # Even complete logs need path/coverage/disabled-arc adjudication.
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', type=Path, default=Path.cwd())
    ap.add_argument('--output', type=Path)
    ap.add_argument('--pt-run', default='pt')
    a = ap.parse_args()
    result = review(a.project, a.pt_run)
    if a.output:
        with a.output.open('x') as f:
            json.dump(result, f, indent=2)
    print('REVIEW_VERDICT '+result['verdict'])
    print('SOURCE files=%d mismatches=%d' % (result['source_files'], len(result['source_mismatches'])))
    print('NETLIST '+json.dumps(result.get('netlist', {}), sort_keys=True))
    for tool, row in result['tools'].items():
        print('%s completed=%d errors=%d summary_errors=%d fatal=%d blackbox=%d' %
              (tool.upper(), row['actual_completion_marker'], len(row['error_lines']),
               row['summary_errors'], len(row['fatal_lines']), len(row['unresolved_or_blackbox_lines'])))
        for context in row['first_error_context'][:1]:
            print(context)
    missing = [name for name, row in result['reports'].items() if not row['present'] or row['bytes'] == 0]
    for name, row in result['reports'].items():
        for line in row['error_lines'][:3]:
            print('REDIRECTED_ERROR '+name+' '+line)
    print('MISSING_OR_EMPTY_REPORTS '+', '.join(missing))
    print('SIGNOFF_REQUIRES setup/hold/recovery/removal, coverage, constraints, disabled arcs, mapped function')


if __name__ == '__main__':
    main()
