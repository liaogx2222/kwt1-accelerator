"""Qualify actual-value 16x16 Dense/RQ banks; no whole-task throughput claim."""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
sys.path.insert(0,str(ROOT))
from integer_model.competitive_tile16 import Tile16Dense,MacroClock,Scratch,VectorEngine


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--stage',choices=['smoke','all'],default='smoke');ap.add_argument('--lanes',type=int,default=4)
    args=ap.parse_args();out=args.output.resolve();assert not out.exists(),'New qualification output';out.mkdir(parents=True)
    candidate=ROOT/'testdata/accuracy_point1_20261104/input16_only'
    for name,digest in json.loads((candidate/'manifest.json').read_text()).items():assert sha(candidate/name)==digest,name
    pm=json.loads((candidate/'run/params/manifest.json').read_text());p=dict(np.load(candidate/'run/params/parameters.npz'))
    # Golden fixture generation stays outside the candidate executor. Avoid
    # importing the frozen derivative and rewriting its bytecode cache.
    path=candidate/'runtime_input16.py';namespace={'__file__':str(path),'__name__':'fixture_reference'}
    exec(compile(path.read_text(),str(path),'exec'),namespace)
    fixture=ROOT/'testdata/integer_v1/fixture';labels=np.load(fixture/'labels.npy');features=np.load(fixture/'encoder_input.npy',mmap_mode='r')
    sample=int(np.flatnonzero(labels==0)[0]);x=np.clip(np.rint(features[sample:sample+1].astype(np.float64)/pm['decode_scales']['encoder_input']),-32767,32767).astype(np.int16)
    stages={};namespace['Encoder'](p,lambda name,value,clip:stages.update({name:value.copy()}))(x)
    names=[(i,kind) for i in range(12) for kind in ['q','k','v','o','fc1','fc2']] if args.stage=='all' else [(0,'q'),(0,'fc1'),(0,'fc2')]
    cases=[];codes=0;start=time.time()
    for layer,kind in names:
        prefix=f'layer_{layer:02d}/';key=f'l{layer:02d}_{kind}'
        if kind in ['q','k','v']:
            source='encoder_input' if layer==0 else f'layer_{layer-1:02d}/layernorm2_output'
            expected=prefix+kind+'_projection'
        elif kind=='o':source=prefix+'attention_context';expected=prefix+'attention_output_projection'
        elif kind=='fc1':source=prefix+'layernorm1_output';expected=prefix+'ffn_dense1_output'
        else:source=prefix+'gelu_output';expected=prefix+'ffn_dense2_output'
        a=stages[source][0];model=Tile16Dense(p['exp_lut'],args.lanes)
        actual,metrics=model.run(a,p[key+'_w'],p[key+'_b'],p[key+'_m'],p[key+'_s'])
        assert np.array_equal(actual,stages[expected][0]),(layer,kind,np.max(np.abs(actual.astype(int)-stages[expected][0].astype(int))))
        assert metrics['register_4KiB_pass'] and metrics['max_operand_A_address']<metrics['LUT_reserved_A_word_base']
        assert metrics['scratch_peak_bytes']<=32768 and max(metrics['scratch_bank_peak_bytes'])<=8192
        codes+=actual.size;row=dict(layer=layer,operation=kind,input_bits=a.dtype.itemsize*8,output_codes=actual.size,**metrics);cases.append(row)
        print(f'TILE16 layer={layer} {kind} codes={actual.size} cycles={metrics["kernel_cycles_excluding_common"]} registers={metrics["total_register_peak_bytes"]} elapsed={time.time()-start:.1f}s',flush=True)
    # Directed negative contracts: bank conflict, bounds, use-after-free,
    # consumption before completion, and a plausible wrong RNE result.
    tests=[];clock=MacroClock()
    for name,ops in [('bank_conflict',[('A0',0,'r',0),('A0',1,'r',0)]),('bounds',[('A0',1024,'r',0)])]:
        try:clock.tick(ops)
        except ValueError:tests.append(name)
        else:raise AssertionError(name)
    pool=Scratch(clock);t=pool.allocate('released',1,1);pool.release(t)
    try:t.word(0,0)
    except RuntimeError:tests.append('use_after_free')
    else:raise AssertionError('use_after_free')
    clock=MacroClock();e=VectorEngine(clock);clock.engine=e
    a=e.source(np.array([3,5,7,9]),32);b=e.source(np.array([2,2,2,2]),32)
    product=e.issue('vmul',[a,b],64,True,'vmul',(4,),[a,b],False)
    try:e.read(product,wait=False)
    except RuntimeError:tests.append('early_use')
    else:raise AssertionError('early_use')
    assert np.array_equal(e.consume(product),[6,10,14,18]);e.drop(product);e.close()
    bad=Tile16Dense(p['exp_lut'],args.lanes,inject=True)
    wrong,_=bad.run(stages['encoder_input'][0],p['l00_q_w'],p['l00_q_b'],p['l00_q_m'],p['l00_q_s'])
    assert not np.array_equal(wrong,stages['layer_00/q_projection'][0]);tests.append('wrong_RNE_result_detected')
    report=dict(passed=True,stage=args.stage,matrix_profiles=len(cases),kernel_output_codes=codes,mismatches=0,
        cases=cases,directed_negative_tests=tests,compressed_exp_exact_entries=4097,compressed_exp_bytes=5024,
        full_task_executed=False,complete_IO_model=False,MAC_RQ_overlap_implemented=False,
        new_RTL_implemented=False,all_competition_targets_met=False,
        scope='standalone real-value Dense/RQ kernel qualification; fixture dependencies between kernels are golden-generated, not a full-task executor',
        max_register_peak_bytes=max(row['total_register_peak_bytes'] for row in cases),
        max_scratch_peak_bytes=max(row['scratch_peak_bytes'] for row in cases),runtime_seconds=time.time()-start)
    sources=[Path(__file__),ROOT/'integer_model/competitive_tile16.py',ROOT/'integer_model/event_arithmetic.py',candidate/'run/params/parameters.npz',candidate/'manifest.json']
    (out/'verification.json').write_text(json.dumps(report,indent=2));(out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2));(out/'manifest.json').write_text(json.dumps({s.name:sha(s) for s in out.iterdir() if s.is_file()},indent=2))
    print(json.dumps(dict(passed=True,matrix_profiles=len(cases),codes=codes,peak_register=report['max_register_peak_bytes']),indent=2))


if __name__=='__main__':main()
