"""Python 3.6 sidecar: parse native PT power and prepare a separate slew review.

Paste this file through stdin in the server SoC directory. It prepares files
outside the running source manifest; it never starts or changes a gate job.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

SCALE={'W':1.,'mW':1e-3,'uW':1e-6,'nW':1e-9,'pW':1e-12,'fW':1e-15}


def field(text,label,kind):
    m=re.search(r'^\s*'+re.escape(label)+r'\s*=\s*([-+0-9.eE]+)\s*([munpf]?W)?',text,re.M)
    if not m:raise ValueError('POWER_FIELD_MISSING '+label)
    unit=m.group(2)
    factor=1.
    if not unit:
        u=re.search(kind+r' Power Units\s*=\s*([0-9.eE+-]+)\s*([munpf]?W)',text)
        if not u:raise ValueError('POWER_UNITS_MISSING '+kind)
        factor=float(u.group(1));unit=u.group(2)
    value=float(m.group(1))*factor*SCALE[unit]
    if not math.isfinite(value) or value<0:raise ValueError('INVALID_POWER '+label)
    return value


def power(text,label,kind):
    if label=='Total Dynamic Power' and not re.search(r'^\s*Total Dynamic Power\s*=',text,re.M):
        return field(text,'Cell Internal Power','Dynamic')+field(text,'Net Switching Power','Dynamic')
    return field(text,label,kind)


def totals(text):
    dynamic=power(text,'Total Dynamic Power','Dynamic')
    leakage=power(text,'Cell Leakage Power','Leakage')
    # The native report rounds fields independently; retain that qualification.
    total=field(text,'Total Power','Dynamic')
    assert abs(dynamic+leakage-total)<=max(total*.005,1e-12),'POWER_SUM_DISAGREES'
    return dict(dynamic_W=dynamic,leakage_W=leakage,total_from_components_W=dynamic+leakage,
                displayed_total_W=total,independent_report_rounding=True)


def prepare(root):
    root=root.resolve()
    assert root.name=='kwt_soc_input16_metrics_595724b_tt_20261112','WRONG_SOC_PROJECT'
    work=root/'review_tools/power_report_review_v1'
    assert not work.exists(),'PRESERVE_EXISTING_POWER_REVIEW'
    original=(root/'flow/pt.tcl').read_text()
    code=original
    pairs=[
      ('source [file join [file dirname [info script]] common.tcl]','source {'+str(root/'flow/common.tcl')+'}'),
      ('set OUT $PROJECT/build/pt\n','set OUT $PROJECT/build/pt_review_v1\n'),
      ('read_soc_constraints\n','read_soc_constraints\n  set_clock_transition 0.150 [all_clocks]\n  puts "SOC_REVIEW_ASSUMED_CLOCK_SLEW_NS 0.150"\n'),
      ('   redirect $OUT/activity_tt.rpt {report_switching_activity;report_switching_activity -list_not_annotated}\n'
       '   redirect $OUT/power_checks_tt.rpt {check_power -verbose}\n   update_power\n',
       '   update_power\n'
       '   redirect $OUT/activity_tt.rpt {report_switching_activity;report_switching_activity -list_not_annotated}\n'
       '   redirect $OUT/power_checks_tt.rpt {check_power -verbose}\n')]
    for old,new in pairs:
        assert code.count(old)==1,'PT_TEMPLATE_DRIFT '+old[:60]
        code=code.replace(old,new)
    collect=(root/'flow/collect.py').read_text()
    old="ROOT/'build/metrics_reference.json'"
    assert collect.count(old)==1,'COLLECT_TEMPLATE_DRIFT'
    assert not (root/'build/metrics_reference_review_v1.json').exists(),'PRESERVE_REVIEW_METRICS'
    work.mkdir(parents=True)
    (work/'pt_review.tcl').write_text(code)
    (work/'collector_snapshot.py').write_text(collect.replace(old,"ROOT/'build/metrics_reference_review_v1.json'"))
    script_source=globals().get('SCRIPT_SOURCE')
    if script_source is None:script_source=Path(__file__).read_text()
    (work/'power_parser.py').write_text(script_source)
    collect_runner="""from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from power_parser import power,totals
root=Path(__file__).resolve().parents[2]
work=Path(__file__).resolve().parent
text=(root/'build/pt_review_v1/power_soc_tt.rpt').read_text()
totals(text)
src=(work/'collector_snapshot.py').read_text()
src=src.replace('build/pt/power_soc_tt.rpt','build/pt_review_v1/power_soc_tt.rpt')
ns={'__file__':str(root/'flow/collect.py'),'__name__':'review_collector'}
exec(compile(src,str(work/'collector_snapshot.py'),'exec'),ns)
ns['power']=power
result=ns['collect']()
import json
result['power_review_assumptions']=json.loads((work/'assumptions.json').read_text())
(root/'build/metrics_reference_review_v1.json').write_text(json.dumps(result,indent=2)+'\\n')
"""
    (work/'collect_review.py').write_text(collect_runner)
    metadata=dict(original_pt_sha256=hashlib.sha256(original.encode()).hexdigest(),
        original_collector_sha256=hashlib.sha256(collect.encode()).hexdigest(),
        operating_condition='TT 1.1V 25C, 150MHz',clock_slew_ns=.150,
        slew_basis='explicit reference assumption; not extracted clock-tree slew',
        coverage_report_after_update_power=True,no_gate_rerun=True,not_signoff=True)
    (work/'assumptions.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print('POWER_REVIEW_PREPARED '+str(work))
    pre=root/'build/pt_preflight/power_soc_tt.rpt'
    if pre.exists():print('DEFAULT_ACTIVITY_PARSE_CHECK_ONLY '+json.dumps(totals(pre.read_text())))
    print('RUN_LATER_AFTER_COLD_SAIF_AND_RESULT_EXIST:')
    print('env -u SOC_PT_PREFLIGHT /eda/synopsys/prime/prime_2022.03-SP5-1/bin/pt_shell -f review_tools/power_report_review_v1/pt_review.tcl')
    print('THEN: python3 review_tools/power_report_review_v1/collect_review.py')


if __name__=='__main__':prepare(Path.cwd())
