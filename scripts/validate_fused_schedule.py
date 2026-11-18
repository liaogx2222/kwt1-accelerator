import argparse,json,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from run_r1r2_low_memory import install
from validate_kwt1_r1 import edge_input,boundary_oracle
from integer_model.fused_layer import FusedLayer
from integer_model.register_contract import static_layout
from integer_model.pipeline_contract import PIPELINE_STORAGE_BYTES,ITERATIVE_STORAGE_BYTES

def fused_budget(measured):
    # Reserve every physical slot even when empty. Dynamic intervals still count
    # in-flight operands/results, so overlapping data is conservatively counted twice.
    fixed=static_layout()['bytes']+PIPELINE_STORAGE_BYTES+ITERATIVE_STORAGE_BYTES
    peak=fixed+measured['peak_bytes']
    return dict(data_peak=measured['peak_bytes'],static_and_physical_pipeline_bytes=fixed,total_peak=peak,passed=peak<=4096,remaining=4096-peak)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--quick',action='store_true');a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True);install()
    p=dict(np.load(ROOT/'testdata/integer_v1/params/parameters.npz'));meta=json.loads((ROOT/'testdata/integer_v1/params/manifest.json').read_text())
    fixture=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r')
    x=np.clip(np.rint(fixture[187].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
    rows=[]
    for layer in range(1 if a.quick else 12):
        for mode in ('normal','boundary'):
            folder=a.output/f'{mode}_{layer:02d}';folder.mkdir(exist_ok=True)
            inp=x if mode=='normal' else edge_input();expected=boundary_oracle(p,layer,inp)
            start=time.time()
            model=FusedLayer(p,folder/'banks.gz',layer,coefficient_cache=True,gelu_ports=8,pingpong=True,
                             lifetimes=folder/'lifetimes.gz',event_trace=folder/'events.gz' if layer==0 else None)
            model.b.enabled=False
            out=model.run(inp,expected);np.save(folder/'output.npy',out)
            budget=fused_budget(model.measured);assert budget['passed'],budget
            stages={s:sum(v for (ss,t),v in model.b.stage_cycles.items() if ss==s) for s,t in model.b.stage_cycles}
            row=dict(layer=layer,mode=mode,mismatches=0,core_cycles=model.b.cycle-model.local_load_cycles-model.handoff_cycles,
                     handoff_cycles=model.handoff_cycles,stages=stages,register_budget=budget,liveness=model.measured,
                     reads=sum(v for (b,m),v in model.b.counts.items() if m=='r'),writes=sum(v for (b,m),v in model.b.counts.items() if m=='w'),elapsed=time.time()-start)
            (folder/'summary.json').write_text(json.dumps(row,indent=2),encoding='utf-8');rows.append(row)
            (a.output/'checkpoint.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
            if mode=='normal':x=out
            print('FUSED',layer,mode,row['core_cycles'],budget,round(time.time()-start,1),flush=True)
    (a.output/'summary.json').write_text(json.dumps(dict(passed=True,quick=a.quick,layers=rows),indent=2),encoding='utf-8')
if __name__=='__main__':main()
