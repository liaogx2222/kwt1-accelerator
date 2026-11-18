"""Observe actual issue/ready intervals; never drive arithmetic results."""
import json
import sys
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
from integer_model.competitive_norm_pipeline import PipelinedNorm
from integer_model.competitive_softmax_pipeline import SoftmaxPipelinedAttention


def attach(model):
    rows=[];original=model.e.issue
    def issue(*args,**kwargs):
        result=original(*args,**kwargs);unit=kwargs.get('unit',args[4] if len(args)>4 else 'alu')
        if unit in ['sqrt','div']:rows.append(dict(unit=unit,start=result.ready-model.e.lat[unit],end=result.ready,id=result.id))
        return result
    model.e.issue=issue;return rows


def main():
    out=Path(sys.argv[1]).resolve();assert not out.exists();out.mkdir(parents=True)
    x,p,_=component.fixture();st=component.reference_stages(x,p);cases=[]
    for j in [1,2]:
        model=PipelinedNorm(p['exp_lut']);intervals=attach(model)
        a=x[0] if j==1 else st['layer_00/layernorm1_output'][0]
        b=st['layer_00/'+('attention_output_projection' if j==1 else 'ffn_dense2_output')][0]
        actual,metrics=model.run_norm(a,b,p,'l00',j);assert np.array_equal(actual,st[f'layer_00/layernorm{j}_output'][0])
        cases.append(dict(name=f'LN{j}',intervals=sorted(intervals,key=lambda r:r['start'])))
    model=SoftmaxPipelinedAttention(p['exp_lut']);intervals=attach(model)
    actual,_=model.run(*[st['layer_00/'+n+'_projection'][0] for n in ['q','k','v']],x[0],p,'l00')
    assert np.array_equal(actual,st['layer_00/attention_context'][0]);cases.append(dict(name='attention',intervals=sorted(intervals,key=lambda r:r['start'])))
    overlaps=[]
    for case in cases:
        for a,b in zip(case['intervals'],case['intervals'][1:]):
            if a['end']>b['start']:overlaps.append(dict(case=case['name'],previous=a,current=b))
    report=dict(passed=not overlaps,cases=cases,overlaps=overlaps)
    (out/'verification.json').write_text(json.dumps(report,indent=2));(out/'source_bindings.json').write_text(json.dumps({str(Path(__file__).relative_to(ROOT)).replace('\\','/'):sha(Path(__file__)),**{str((ROOT/'integer_model'/n).relative_to(ROOT)).replace('\\','/'):sha(ROOT/'integer_model'/n) for n in ['competitive_norm_pipeline.py','competitive_softmax_pipeline.py','competitive_nonlinear.py']}},indent=2))
    (out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2));print(json.dumps(dict(passed=not overlaps,overlap_count=len(overlaps),first=overlaps[:2]),indent=2))


if __name__=='__main__':main()
