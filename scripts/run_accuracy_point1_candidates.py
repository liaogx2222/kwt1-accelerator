"""Preregistered integer scale candidates for <=0.1pp Validation loss.

Weights and arithmetic formulas stay unchanged. Scale recipes depend only on
the existing frozen training calibration. No training, test-set access or
per-sample outputs are used to construct parameters. v1 is never overwritten.
"""
import argparse
import csv
import importlib.util
import json
import math
import os
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT, sha
import sys
sys.path.insert(0,str(ROOT))
from integer_model.runtime import Encoder

RECIPES={
 'input_max': 'Use training max_abs for encoder_input only; all other scales p999.',
 'context_max': 'Use training max_abs for all attention_context tensors only; other scales p999.',
 'mid_all': 'Use geometric mean of training p999 and max_abs for all signed INT8 activation scales.',
 'max_all': 'Use training max_abs for all signed INT8 activation scales.'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--recipe',choices=list(RECIPES),required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--batch-size',type=int,default=32)
    args=ap.parse_args();out=args.output.resolve();assert not out.exists(),'New candidate directory required';out.mkdir(parents=True)
    begin=time.time();fixture=ROOT/'testdata/integer_v1/fixture';v1=ROOT/'testdata/integer_v1/params'
    calibration=ROOT/'testdata/ptq_calibration/kwt1_ptq_activation_scale_candidates.csv'
    sources=[Path(__file__),ROOT/'integer_model/runtime.py',ROOT/'integer_model/export.py',ROOT/'integer_model/cuda_matmul.py',
             calibration,ROOT/'testdata/ptq_calibration/kwt1_ptq_calibration_manifest.json',v1/'manifest.json',v1/'parameters.npz',
             fixture/'manifest.json',fixture/'encoder_input.npy',fixture/'labels.npy',fixture/'fp_logits.npy',fixture/'raw_parameters.npz']
    bindings={path.relative_to(ROOT).as_posix():sha(path) for path in sources}
    (out/'source_bindings.json').write_text(json.dumps(bindings,indent=2))
    fm=json.loads((fixture/'manifest.json').read_text());assert fm['partition']=='validation' and fm['testing_batches_requested']==0
    calibration_meta=json.loads(sources[5].read_text());assert calibration_meta['calibration_partition']=='training' and not calibration_meta['testing_partition_accessed']
    with calibration.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
    choices={}
    for row in rows:
        if row['format']=='INT8':choices.setdefault(row['tensor'],{})[row['threshold_source']]=row
    selected={};new=[]
    for tensor,options in choices.items():
        use_max=args.recipe=='max_all' or (args.recipe=='input_max' and tensor=='encoder_input') or (args.recipe=='context_max' and tensor.endswith('/attention_context'))
        row=dict(options['max_abs' if use_max else 'abs_p999_est'])
        source=row['threshold_source']
        if args.recipe=='mid_all':
            scale=math.sqrt(float(options['abs_p999_est']['scale'])*float(options['max_abs']['scale']))
            row.update(scale=repr(scale),step=repr(scale),clip_threshold=repr(127*scale),estimated_tail_fraction='',note='Geometric mean of two frozen training thresholds; not Validation-fitted')
            source='geometric_mean_training_p999_and_max'
        row['threshold_source']='candidate_selected'
        selected[tensor]=dict(source=source,scale=float(row['scale']))
        new.append(row)
    (out/'recipe.json').write_text(json.dumps(dict(recipe=args.recipe,description=RECIPES[args.recipe],
        parameter_selection_uses_validation_labels=False,testing_used=False,selected_scales=selected),indent=2))
    candidate_calibration=out/'selected_training_scales.csv'
    with candidate_calibration.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(new)
    # Preserve original exporter; archive the exact selector-only derivative.
    export_source=(ROOT/'integer_model/export.py').read_text()
    anchor='r["threshold_source"] == "abs_p999_est"';assert export_source.count(anchor)==1
    export_source=export_source.replace(anchor,'r["threshold_source"] == "candidate_selected"')
    export_source=export_source.replace('"numeric_spec": "INTEGER_NUMERICS_V1"','"numeric_spec": "INTEGER_V1_FORMULAS_SCALE_CANDIDATE"')
    export_source=export_source.replace('"training abs_p999_est, 2048 samples"','"frozen training calibration; recipe.json specifies per-tensor choice"')
    exporter=out/'export_candidate_executed.py';exporter.write_text(export_source)
    spec=importlib.util.spec_from_file_location('candidate_export',exporter);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    pm=module.export(fixture/'raw_parameters.npz',candidate_calibration,out/'params')
    p=dict(np.load(out/'params/parameters.npz'));baseline=dict(np.load(v1/'parameters.npz'))
    assert p.keys()==baseline.keys()
    assert all(p[key].shape==baseline[key].shape and p[key].dtype==baseline[key].dtype for key in p)
    weights=[key for key in p if key.endswith('_w')];assert len(weights)==72 and all(np.array_equal(p[key],baseline[key]) for key in weights)
    from integer_model.cuda_matmul import CudaInt8Matmul
    import torch
    torch.set_num_threads(1)
    backend=CudaInt8Matmul();encoder=Encoder(p,dense_matmul=backend)
    inputs=np.load(fixture/'encoder_input.npy',mmap_mode='r');labels=np.load(fixture/'labels.npy');fp=np.load(fixture/'fp_logits.npy')
    assert len(labels)==4445
    logits=np.empty((4445,12),np.float32);outputs=np.lib.format.open_memmap(out/'encoder_output_int8.npy',mode='w+',dtype=np.int8,shape=(4445,99,64))
    raw=np.load(fixture/'raw_parameters.npz');checked_codes=checked_stages=0
    run_begin=time.time()
    for offset in range(0,4445,args.batch_size):
        stop=min(offset+args.batch_size,4445)
        q=np.clip(np.rint(inputs[offset:stop].astype(np.float64)/pm['decode_scales']['encoder_input']),-127,127).astype(np.int8)
        y=encoder(q);outputs[offset:stop]=y
        if offset==0:
            stages=[{},{}]
            for captured,mm in zip(stages,[None,backend]):
                Encoder(p,lambda name,value,clipped:captured.update({name:value.copy()}),dense_matmul=mm)(q[:1])
            assert stages[0].keys()==stages[1].keys()
            for name in stages[0]:assert np.array_equal(stages[0][name],stages[1][name]),name
            checked_codes=sum(value.size for value in stages[0].values());checked_stages=len(stages[0])
            cpu=Encoder(p)(q[:3]);assert np.array_equal(cpu,y[:3])
        decoded=y[:,0,:].astype(np.float32)*np.float32(pm['final_scale'])
        logits[offset:stop]=decoded@raw['head_w']+raw['head_b']
        if offset==0 or stop==4445 or stop%256==0:print(f'{args.recipe} {stop}/4445 elapsed={time.time()-run_begin:.1f}s',flush=True)
    outputs.flush();np.save(out/'logits.npy',logits)
    assert np.isfinite(logits).all()
    pred=logits.argmax(axis=1);fpp=fp.argmax(axis=1);correct=int(np.count_nonzero(pred==labels));fp_correct=int(np.count_nonzero(fpp==labels));assert fp_correct==4348
    required=fp_correct-math.floor(4445*0.1/100)
    shifts=np.concatenate([value.reshape(-1) for key,value in p.items() if key.endswith('_s')])
    residual=[int(value[2]) for key,value in p.items() if key.endswith('_coeff')]
    report=dict(completed=True,recipe=args.recipe,scope='new scale candidate software only; not adopted v1 or RTL-approved',samples=4445,
        fp_correct=fp_correct,integer_correct=correct,accuracy_percent=100*correct/4445,accuracy_drop_pp=100*(fp_correct-correct)/4445,
        target_drop_pp=0.1,required_integer_correct=required,target_met=correct>=required,testing_used=False,training_performed=False,
        numeric_formulas_changed=False,weights_changed=False,all_72_weight_arrays_identical=True,
        CPU_CUDA_first_sample_stage_tensors=checked_stages,CPU_CUDA_stage_codes=checked_codes,CPU_CUDA_mismatches=0,
        CPU_CUDA_full_output_codes=3*6336,parameter_array_shapes_unchanged=True,
        requant_shift_range=[int(shifts.min()),int(shifts.max())],residual_shift_values=sorted(set(residual)),
        final_scale=pm['final_scale'],runtime_seconds=time.time()-run_begin,total_seconds=time.time()-begin,
        historical_LN_E01_inherited=False,new_LN_quality_gate_completed=False,RTL_bit_equivalence_completed=False,
        candidate_parameters_sha256=sha(out/'params/parameters.npz'),logits_finite=True,
        device=torch.cuda.get_device_name(0),torch_version=torch.__version__)
    np.save(out/'predictions.npy',pred)
    for name,digest in bindings.items():assert sha(ROOT/name)==digest,name
    (out/'metrics.json').write_text(json.dumps(report,indent=2));(out/'manifest.json').write_text(json.dumps({path.relative_to(out).as_posix():sha(path) for path in out.rglob('*') if path.is_file() and path.name!='manifest.json'},indent=2));print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
