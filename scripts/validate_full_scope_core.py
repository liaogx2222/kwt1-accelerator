"""Meter selected full-core schedules by bank and actual arithmetic issues."""
import argparse
from collections import Counter
import json
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
import validate_competitive_resident_core as original
from integer_model.competitive_graph_windows import WindowRowsCore


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--classes',default='0,1');ap.add_argument('--buffers',type=int,choices=[1,2],default=2);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    classes=[int(x) for x in a.classes.split(',')];assert len(set(classes))==len(classes) and all(0<=c<12 for c in classes)
    x,indices=original.inputs(12);p=dict(np.load(component.BASE/'run/params/parameters.npz'));model=WindowRowsCore(p['exp_lut'],fusion='ln',window=128,accumulator_buffers=a.buffers);identity=id(model);cases=[];codes=0;start=time.time()
    for task,label in enumerate(classes):
        if task:model.reset()
        assert id(model)==identity;ref=component.reference_stages(x[label:label+1],p);saved={};chunks={};requests=Counter();intervals=[];issue=model.e.issue
        def observed_issue(*args,**kwargs):
            result=issue(*args,**kwargs);unit=kwargs.get('unit',args[4] if len(args)>4 else 'alu');requests[unit]+=1
            if unit in ['div','sqrt']:intervals.append(dict(unit=unit,start=result.ready-model.e.lat[unit],end=result.ready))
            return result
        model.e.issue=observed_issue
        def observe(layer,op,value,offset=None):
            expected=ref[component.expected_key(layer,op)][0];key=f'l{layer:02d}_{op}'
            if offset is None:assert np.array_equal(value,expected);saved[key]=value.copy()
            else:assert np.array_equal(value,expected[offset:offset+len(value)]);chunks.setdefault(key,[]).append(value.copy())
            if op=='ln2':print(f'METER buffers={a.buffers} class={label} layer={layer} cycle={model.b.cycle}',flush=True)
        actual,m=model.run(x[label],p,observe);assert np.array_equal(actual,ref['layer_11/layernorm2_output'][0])
        for key,parts in chunks.items():saved[key]=np.concatenate(parts,axis=0)
        n=0
        for layer in range(12):
            for op in ['q','k','v','qk','softmax','pv','o','ln1','fc1','gelu','fc2','ln2']:
                v=saved[f'l{layer:02d}_{op}'];assert np.array_equal(v,ref[component.expected_key(layer,op)][0]);n+=v.size
        assert n==1451736;codes+=n;np.savez_compressed(out/f'class{label:02d}_observed.npz',**saved)
        intervals.sort(key=lambda r:r['start']);assert len(intervals)==5940 and all(i['end']<=j['start'] for i,j in zip(intervals,intervals[1:]))
        banks={bank:{mode:model.b.counts[bank,mode] for mode in ['r','w']} for bank in model.b.mem}
        assert sum(v['r'] for v in banks.values())==m['SRAM_reads'];assert sum(v['w'] for v in banks.values())==m['SRAM_writes']
        assert m['register_4KiB_pass'] and m['Softmax_pending_rows_max']==2 and m['LN_pending_rows_max']==2
        m.update(label=label,source_index=indices[label],bank_accesses=banks,unit_requests=dict(requests),iterative_intervals=intervals)
        cases.append(m);(out/'partial.json').write_text(json.dumps(cases,indent=2))
    report=dict(passed=True,classes=classes,cases=cases,independent_output_codes=codes,mismatches=0,same_model_object=True,explicit_model_cold_reset_between_tasks=True,
        window=128,fusion='ln',accumulator_buffers=a.buffers,complete_CPU_packet_IO=False,new_RTL=False,full_SoC_power_measured=False,runtime_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2));sources=[Path(__file__),Path(component.__file__),Path(original.__file__),component.BASE/'run/params/parameters.npz']
    sources+=[ROOT/'integer_model'/n for n in component.SOURCE_NAMES+['competitive_graph_windows.py','competitive_fused_rows.py','competitive_core_tradeoff.py','competitive_resident_core.py','competitive_resident_attention.py','competitive_resident_ffn.py','competitive_norm_pipeline.py','competitive_softmax_pipeline.py']]
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2));(out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2));print(json.dumps(dict(passed=True,cycles=[m['cycles'] for m in cases],peak=max(m['total_register_peak_bytes'] for m in cases),codes=codes),indent=2))


if __name__=='__main__':main()
