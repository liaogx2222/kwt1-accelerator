"""P3b: frozen v1 replay, exact full-population LN percentiles; no tuning."""
import argparse
import csv
import hashlib
import json
import math
import sys
import time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integer_model.runtime import Encoder, rq, shift_rne
from integer_model.cuda_matmul import CudaInt8Matmul
from integer_model.export import sha


class Tail:
    """Keep the largest N-floor(.99*(N-1)) values: exact np.percentile linear."""
    def __init__(self,n):
        self.n = n
        self.index = (n-1)*99//100
        self.k = n-self.index
        self.values = np.empty(0,np.float64)
        self.count = 0
    def add(self,x):
        a = np.asarray(x,np.float64).ravel()
        self.count += a.size
        if len(self.values) == self.k:
            a = a[a >= self.values.min()]
        if not a.size:
            return
        v = np.concatenate([self.values,a])
        if len(v)>self.k:
            v = np.partition(v,len(v)-self.k)[-self.k:]
        self.values = v
    def result(self):
        assert self.count == self.n
        v = np.sort(self.values)
        # Quantile index is (N-1)*99/100, interpolate the two exact order stats.
        rem = ((self.n-1)*99)%100
        return float(v[0]+(v[1]-v[0])*(rem/100)) if rem else float(v[0])


class Diagnostic:
    def __init__(self,p,meta,raw,n,bad,sample_writer):
        self.p,self.meta,self.raw = p,meta,raw
        self.n,self.bad,self.writer = n,bad,sample_writer
        self.offset = 0
        self.cache,self.rows,self.tails,self.groups = {},{},{},{}
        self.oracle_anomalies = []
    def __call__(self,name,q,clipped):
        if name.endswith(('residual1_sum','residual2_sum')):
            self.cache['residual'] = q.copy()
        elif name.endswith('/normalized_q14'):
            self.cache['normalized'] = q.copy()
        elif name.endswith(('layernorm1_output','layernorm2_output')):
            i,j = int(name[6:8]), (1 if name.endswith('1_output') else 2)
            key = f'l{i:02d}_ln{j}'
            rn = f'layer_{i:02d}/residual{j}_sum'
            sy,sr = self.meta['decode_scales'][name],self.meta['decode_scales'][rn]
            r = self.cache.pop('residual')
            nq = self.cache.pop('normalized')
            x = r.astype(np.float64)*sr
            c = x-x.mean(-1,keepdims=True)
            norm = c/np.sqrt(np.mean(c*c,-1,keepdims=True)+1e-6)
            fp = norm*self.raw[key+'_g']+self.raw[key+'_b']
            fpclip = np.clip(fp,-127*sy,127*sy)
            idealq = np.clip(np.rint(fp/sy),-127,127).astype(np.int8)
            ideal = idealq.astype(np.float64)*sy
            val = q.astype(np.float64)*sy
            ei,er,ec = val-ideal,ideal-fpclip,fpclip-fp
            diff = val-fp
            affine = shift_rne(nq*self.p[key+'_g'],14)+self.p[key+'_b']
            before = rq(affine,self.p[key+'_m'],self.p[key+'_s'])
            actual_mask = np.abs(before)>127
            reference_mask = np.abs(fp)>127*sy
            assert int(actual_mask.sum()) == clipped
            code_diff = q.astype(np.int16)-idealq.astype(np.int16)
            row = self.rows.setdefault(name,{'stage':name,'elements':0,'clip_actual':0,'clip_fp_reference':0,
                'code_histogram':{},'sse_integer_approx':0.,'sse_output_round':0.,'sse_clip':0.,
                'cross_i_round':0.,'cross_i_clip':0.,'cross_round_clip':0.,'sse_total':0.,
                'fp_energy':0.,'clipped_fp_energy':0.,'ideal_energy':0.,'sse_vs_clipped_fp_reference':0.,
                'normalized_error_sse':0.,'normalized_energy':0.,'max_code_error':0})
            row['elements'] += q.size
            row['clip_actual'] += int(actual_mask.sum())
            row['clip_fp_reference'] += int(reference_mask.sum())
            for k,a in [('sse_integer_approx',ei*ei),('sse_output_round',er*er),('sse_clip',ec*ec),
                        ('cross_i_round',2*ei*er),('cross_i_clip',2*ei*ec),('cross_round_clip',2*er*ec),
                        ('sse_total',diff*diff),('fp_energy',fp*fp),('clipped_fp_energy',fpclip*fpclip),
                        ('ideal_energy',ideal*ideal),('sse_vs_clipped_fp_reference',(val-fpclip)**2),
                        ('normalized_error_sse',(nq/(1 << 14)-norm)**2),('normalized_energy',norm*norm)]:
                row[k] += float(np.sum(a))
            row['max_code_error'] = max(row['max_code_error'],int(np.abs(code_diff).max()))
            values,counts = np.unique(code_diff,return_counts=True)
            for value,count in zip(values,counts):
                v = str(int(value));row['code_histogram'][v] = row['code_histogram'].get(v,0)+int(count)
            if name not in self.tails:
                self.tails[name] = [Tail(self.n*99*64),Tail(self.n*99*64)]
            self.tails[name][0].add(np.abs(diff)/sy)
            self.tails[name][1].add(np.abs(val-fpclip)/sy)
            masks = {'all':np.ones(q.shape,bool),'actual_integer_clipped':actual_mask,
                     'fp_reference_clipped':reference_mask,'cls':np.broadcast_to(np.arange(99)[None,:,None]==0,q.shape),
                     'non_cls':np.broadcast_to(np.arange(99)[None,:,None]!=0,q.shape),
                     'fp_correct_integer_wrong':np.broadcast_to(self.bad[self.offset:self.offset+len(q),None,None],q.shape)}
            for group,mask in masks.items():
                g = self.groups.setdefault((name,group),{'stage':name,'group':group,'elements':0,'actual_clip':0,
                    'sse_vs_fp':0.,'fp_energy':0.,'sse_vs_clipped_fp_reference':0.,'clipped_fp_energy':0.,
                    'sse_vs_ideal_int8':0.,'ideal_energy':0.,'code_mismatch':0})
                g['elements'] += int(mask.sum())
                g['actual_clip'] += int(actual_mask[mask].sum())
                for k,a in [('sse_vs_fp',diff**2),('fp_energy',fp**2),('sse_vs_clipped_fp_reference',(val-fpclip)**2),
                            ('clipped_fp_energy',fpclip**2),('sse_vs_ideal_int8',ei**2),('ideal_energy',ideal**2)]:
                    g[k] += float(np.sum(a[mask]))
                g['code_mismatch'] += int(np.count_nonzero(code_diff[mask]))
            for b in range(len(q)):
                self.writer.writerow({'offset':self.offset+b,'stage':name,'fp_correct_integer_wrong':int(self.bad[self.offset+b]),
                    'actual_clipped':int(actual_mask[b].sum()),'cls_clipped':int(actual_mask[b,0].sum()),
                    'sse_vs_fp':float(np.sum(diff[b]**2)),'sse_integer_approx':float(np.sum(ei[b]**2)),
                    'sse_output_round':float(np.sum(er[b]**2)),'sse_clip':float(np.sum(ec[b]**2)),
                    'code_mismatches':int(np.count_nonzero(code_diff[b]))})
            # Any >1-code discrepancy is independently checked using Python integers.
            for loc in np.argwhere(np.abs(code_diff)>1)[:20]:
                b,t,ch = map(int,loc)
                xx = list(map(int,r[b,t]));s = sum(xx);v = 64*sum(z*z for z in xx)-s*s
                h = (v << 16)+int(self.p[key+'_eps'])
                def round_int(a,d):
                    z,rem = divmod(abs(a),d)
                    z += int(2*rem>d or (2*rem==d and z%2))
                    return -z if a<0 else z
                inv = round_int(1 << 40,math.isqrt(h))
                nn = round_int((64*xx[ch]-s)*inv,1 << 18)
                aff = round_int(nn*int(self.p[key+'_g'][ch]),1 << 14)+int(self.p[key+'_b'][ch])
                code = max(-127,min(127,round_int(aff*int(self.p[key+'_m']),1 << int(self.p[key+'_s']))))
                assert code == int(q[b,t,ch])
                self.oracle_anomalies.append({'offset':self.offset+b,'stage':name,'token':t,'channel':ch,'gold':code,'ideal_quantized':int(idealq[b,t,ch])})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=ROOT/'testdata/p3b/ln_full')
    ap.add_argument('--batch-size',type=int,default=16)
    a = ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if (a.output/'summary.json').exists():raise FileExistsError('Preserve evidence')
    base = ROOT/'testdata/integer_v1'
    meta = json.loads((base/'params/manifest.json').read_text())
    assert sha(base/'params/parameters.npz') == meta['parameters_sha256']
    params = dict(np.load(base/'params/parameters.npz'));raw = np.load(base/'fixture/raw_parameters.npz')
    x = np.load(base/'fixture/encoder_input.npy',mmap_mode='r')
    golden = np.load(base/'validation/encoder_output_int8.npy',mmap_mode='r')
    labels = np.load(base/'fixture/labels.npy');fp = np.load(base/'fixture/fp_logits.npy').argmax(-1)
    ip = np.load(base/'validation/logits.npy').argmax(-1);bad = (fp==labels)&(ip!=labels)
    n = len(x);start = time.time()
    with (a.output/'per_sample.csv').open('w',encoding='utf-8',newline='') as f:
        fields = ['offset','stage','fp_correct_integer_wrong','actual_clipped','cls_clipped','sse_vs_fp','sse_integer_approx','sse_output_round','sse_clip','code_mismatches']
        writer = csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        diag = Diagnostic(params,meta,raw,n,bad,writer);enc = Encoder(params,diag,CudaInt8Matmul())
        for offset in range(0,n,a.batch_size):
            diag.offset = offset
            q = np.clip(np.rint(x[offset:offset+a.batch_size].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
            out = enc(q)
            assert np.array_equal(out,golden[offset:offset+len(q)]),'Replay changed codes'
            if offset%(a.batch_size*10)==0 or offset+len(q)==n:print(f'LN {offset+len(q)}/{n} {time.time()-start:.1f}s',flush=True)
    rows = []
    for name,r in diag.rows.items():
        r['p99_abs_output_lsb_vs_fp'] = diag.tails[name][0].result()
        r['p99_abs_output_lsb_vs_clipped_fp_reference'] = diag.tails[name][1].result()
        total = r['sse_integer_approx']+r['sse_output_round']+r['sse_clip']+r['cross_i_round']+r['cross_i_clip']+r['cross_round_clip']
        assert abs(total-r['sse_total'])<=max(1e-7,r['sse_total']*1e-10)
        r['sse_decomposition_residual'] = total-r['sse_total']
        r['nrmse_vs_fp'] = math.sqrt(r['sse_total']/r['fp_energy'])
        r['nrmse_vs_clipped_fp_reference'] = math.sqrt(r['sse_vs_clipped_fp_reference']/r['clipped_fp_energy'])
        r['nrmse_vs_ideal_int8_ln'] = math.sqrt(r['sse_integer_approx']/r['ideal_energy'])
        r['normalized_q14_nrmse'] = math.sqrt(r['normalized_error_sse']/r['normalized_energy'])
        rows.append(r)
    summary = {'samples':n,'parameter_manifest_sha256':sha(base/'params/manifest.json'),
        'runtime_sha256':sha(ROOT/'integer_model/runtime.py'),'diagnostic_sha256':sha(__file__),
        'exact_percentile_method':'fixed-N top-tail, numpy linear order-statistic interpolation, no sampling',
        'all_final_codes_equal_saved_golden':True,'fp_correct_integer_wrong_samples':int(bad.sum()),
        'ln_gt_1pct':[r['stage'] for r in rows if r['nrmse_vs_fp']>.01],
        'ln_p99_gt_1lsb':[r['stage'] for r in rows if r['p99_abs_output_lsb_vs_fp']>1],
        'max_ideal_quantized_code_error':max(r['max_code_error'] for r in rows),
        'anomalies_checked_with_python_integer_oracle':diag.oracle_anomalies,
        'stages':rows,'groups':list(diag.groups.values()),'elapsed_seconds':time.time()-start}
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print('LN complete',summary['ln_gt_1pct'],summary['ln_p99_gt_1lsb'],flush=True)


if __name__=='__main__':main()
