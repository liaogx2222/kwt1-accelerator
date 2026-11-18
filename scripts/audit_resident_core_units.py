"""Count actual accepted arithmetic requests, not scalar element estimates."""
import collections
import json
import sys
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
from integer_model.competitive_resident_core import ResidentCore


def main():
    out=Path(sys.argv[1]).resolve();assert not out.exists();out.mkdir(parents=True)
    x,p,_=component.fixture();ref=component.reference_stages(x,p);model=ResidentCore(p['exp_lut']);original=model.e.issue
    units=collections.Counter();ops=collections.Counter();starts=collections.defaultdict(list);started=time.time()
    def issue(*a,**k):
        result=original(*a,**k);unit=k.get('unit',a[4] if len(a)>4 else 'alu');units[unit]+=1;ops[a[0]]+=1
        starts[unit].append(result.ready-model.e.lat[unit]);return result
    model.e.issue=issue;actual,metrics=model.run(x[0],p)
    assert np.array_equal(actual,ref['layer_11/layernorm2_output'][0]) and metrics['cycles']==2040236
    for unit,times in starts.items():
        times.sort();assert all(b-a>=model.e.II[unit] for a,b in zip(times,times[1:])),unit
    assert units['vmul']==511572 and units['mac']==367584 and units['vrne']==373764
    np.save(out/'observed_final.npy',actual)
    report=dict(passed=True,cycles=metrics['cycles'],unit_requests=dict(units),operation_requests=dict(ops),
        unit_initiation_intervals=model.e.II,unit_latencies=model.e.lat,wide_mul_request_lower_bound=units['vmul'],
        wide_mul_issue_utilization=units['vmul']/metrics['cycles'],target_625000_required_wide_mul_utilization=units['vmul']/625000,
        latency_is_not_task_lower_bound=True,all_units_II_checked=True,final_output_codes=6336,mismatches=0,runtime_seconds=time.time()-started,
        scope='same full-core execution, arithmetic observer only; lower bounds do not include dependency/port/transport constraints')
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),ROOT/'integer_model/competitive_resident_core.py',Path(component.__file__),component.BASE/'run/params/parameters.npz']
    (out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in sources},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(report,indent=2))

if __name__=='__main__':main()
