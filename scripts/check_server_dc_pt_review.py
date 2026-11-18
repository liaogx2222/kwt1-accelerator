"""Guard against false acceptance of echoed markers and incomplete PT logs."""
import argparse
import hashlib
import json
from pathlib import Path
from server_dc_pt_review import review


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True, type=Path)
    a = ap.parse_args()
    p = a.output.resolve()
    if p.exists():
        raise ValueError('fresh output required')
    (p/'build/dc').mkdir(parents=True)
    (p/'source.sv').write_text('module top; endmodule')
    (p/'manifest.json').write_text(json.dumps(dict(git_revision='synthetic', files={
        'source.sv': dict(sha256=sha(p/'source.sv'))})))
    net = p/'build/dc/mapped.v'
    def bind_net(text):
        net.write_text(text)
        (p/'build/dc/netlist_manifest.json').write_text(json.dumps(dict(
            source_manifest_sha256=sha(p/'manifest.json'), netlist_sha256=sha(net))))
    bind_net('\n'.join('RAMSP4096X16 u%d();' % i for i in range(20)))
    dc = p/'build/dc.console.log'
    pt = p/'build/pt.console.log'
    dc.write_text('KWT_CLEAN_SYNTH_DONE\n')
    pt.write_text('puts "KWT_CLEAN_PT_DONE"\nDiagnostics summary: 3 errors, 3 warnings\n')
    r = review(p)
    assert not r['tools']['pt']['actual_completion_marker'] and r['tools']['pt']['summary_errors'] == 3
    assert r['verdict'] == 'FAILED_OR_INCOMPLETE'
    pt.write_text('Error: unsupported option\nKWT_FATAL failed\n')
    r = review(p)
    assert 'unsupported option' in r['tools']['pt']['first_error_context'][0]
    pt.write_text('Creating black box BAD\nKWT_CLEAN_PT_DONE\n')
    assert review(p)['verdict'] == 'FAILED_OR_INCOMPLETE'
    pt.write_text('KWT_CLEAN_PT_DONE\nDiagnostics summary: 0 errors, 0 warnings\n')
    assert review(p)['verdict'] == 'REVIEW_REQUIRED'
    redirected = p/'build/pt/area_ss.rpt'
    redirected.parent.mkdir()
    redirected.write_text("Error: unknown command 'report_area' (CMD-005)\n")
    assert review(p)['verdict'] == 'FAILED_OR_INCOMPLETE'
    assert 'report_area' in review(p)['reports']['build/pt/area_ss.rpt']['error_lines'][0]
    redirected.write_text('MOCK QOR AREA')
    bind_net('GTECH_AND u();\n'+'\n'.join('RAMSP4096X16 u%d();' % i for i in range(20)))
    assert review(p)['verdict'] == 'FAILED_OR_INCOMPLETE'
    bind_net('\n'.join('RAMSP4096X16 u%d();' % i for i in range(19)))
    assert review(p)['verdict'] == 'FAILED_OR_INCOMPLETE'
    (p/'source.sv').write_text('changed source')
    assert review(p)['source_mismatches'] == ['source.sv']
    result = dict(passed=True, echoed_completion_rejected=True, summary_only_errors_detected=True,
                  first_error_context=True, blackbox_rejected=True, generic_rejected=True,
                  wrong_macro_count_rejected=True, changed_source_detected=True,
                  redirected_error_detected=True, no_automatic_physical_PASS=True,
                  real_server_reports_reviewed=False)
    (p/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
