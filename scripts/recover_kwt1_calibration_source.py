"""Test the committed pre-sorting loader as a historical calibration source.

The original source is compiled in memory; the user's working-tree patch is
never edited. If the saved 2048-label sequence fails, no inference is run.
"""
import csv
import hashlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
os.environ.setdefault('CUDA_VISIBLE_DEVICES','0')
os.environ.setdefault('TF_FORCE_GPU_ALLOW_GROWTH','true')
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL','2')
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
OUT=ROOT/'testdata/p3b/legacy_source_probe'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    import numpy as np
    import tensorflow as tf
    tf.compat.v1.disable_eager_execution()
    from kws_streaming.train import model_train_eval
    from kws_streaming.data import input_data
    from validate_kwt1_ptq_activations import build_flags
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'summary.json').exists():raise FileExistsError('Preserve source probe')
    old=subprocess.run(['git','show','HEAD:kws_streaming/data/input_data.py'],cwd=str(ROOT),check=True,stdout=subprocess.PIPE).stdout
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=str(ROOT),check=True,stdout=subprocess.PIPE,text=True).stdout.strip()
    (OUT/'committed_input_data.py').write_bytes(old)
    source=ROOT/'kws_streaming/data/input_data.py';before=sha(source)
    exec(compile(old,str(OUT/'committed_input_data.py'),'exec'),input_data.__dict__)
    flags=build_flags(ROOT/'models_data_v2_12_labels/kwt1',ROOT/'data2',16)
    config=tf.compat.v1.ConfigProto();config.gpu_options.allow_growth=True
    with tf.compat.v1.Session(config=config) as sess:
        processor=input_data.AudioProcessor(flags)
        labels=[int(processor.word_to_index[r['label']]) for r in processor.data_index['training'][:2048]]
        identities=[]
        for i,item in enumerate(processor.data_index['training'][:2048]):
            p=Path(item['file']);silence=item['label']==input_data.SILENCE_LABEL
            identities.append({'offset':i,'label_id':labels[i],'source_label':item['label'],
                'waveform':'zeros:16000' if silence else p.relative_to(ROOT/'data2').as_posix(),
                'sha256':None if silence else sha(p)})
    oldpred=list(csv.DictReader((ROOT/'testdata/ptq_calibration/kwt1_ptq_training_predictions.csv').open(encoding='utf-8-sig',newline='')))
    saved=[int(r['true_label_id']) for r in oldpred]
    mismatch=[i for i,(x,y) in enumerate(zip(labels,saved)) if x!=y]
    result={'committed_git_head':head,'in_memory_loader_sha256':hashlib.sha256(old).hexdigest(),
        'working_tree_loader_unchanged':sha(source)==before,'training_label_order_mismatches':len(mismatch),
        'first_mismatches':mismatch[:30],'identity_list_claim':'candidate reconstructed from committed loader, not an original saved identity manifest',
        'testing_batches_requested':0,'calibration_replay_performed':False}
    (OUT/'candidate_training_identities.json').write_text(json.dumps(identities,indent=2),encoding='utf-8')
    if not mismatch:
        tf.keras.backend.clear_session()
        original=input_data.AudioProcessor.get_data
        def guard(self,*args,**kwargs):
            mode=kwargs.get('mode',args[6] if len(args)>6 else None)
            if mode!='training':raise RuntimeError('Only training allowed')
            return original(self,*args,**kwargs)
        input_data.AudioProcessor.get_data=guard
        sys.argv=[str(ROOT/'scripts/calibrate_kwt1_ptq.py'),'--batch-size','16','--max-samples','2048','--output-dir',str(OUT/'calibration_replay')]
        runpy.run_path(sys.argv[0],run_name='__main__');result['calibration_replay_performed']=True
        comparison={}
        for filename in ['kwt1_ptq_activation_scale_candidates.csv','kwt1_ptq_training_activation_stats.csv','kwt1_ptq_training_channel_stats.csv','kwt1_ptq_training_predictions.csv','kwt1_ptq_weight_stats.csv']:
            a,b=ROOT/'testdata/ptq_calibration'/filename,OUT/'calibration_replay'/filename
            aa=list(csv.DictReader(a.open(encoding='utf-8-sig',newline='')));bb=list(csv.DictReader(b.open(encoding='utf-8-sig',newline='')))
            comparison[filename]={'table_equal':aa==bb,'byte_equal':sha(a)==sha(b),'old_sha256':sha(a),'replay_sha256':sha(b)}
        result['comparison']=comparison
    assert sha(source)==before
    (OUT/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
