"""Canonical packet driven RTL: 12 paired profiles/classes (optional full matrix)."""
import argparse,hashlib,json,subprocess,sys,time,shutil
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from validate_kwt1_r2 import artifacts
from integer_model.hw_abi import HEADER,ENTRY
from integer_model.runtime import Encoder

def hexwords(path,data):
    assert len(data)%4==0
    path.write_text(''.join(f'{int.from_bytes(data[i:i+4],"little"):08x}\n' for i in range(0,len(data),4)),encoding='ascii')

def prepare(out,quick,matrix=False):
    packets,p=artifacts();heads={};offsets={}
    for name,data in packets.items():
        hexwords(out/(name+'.hex'),data);heads[name]=[int.from_bytes(data[i:i+4],'little') for i in range(0,64,4)]
        h=HEADER.unpack(data[:64]);local={}
        for i in range(h[4]):
            e=ENTRY.unpack(data[64+i*128:64+(i+1)*128]);key=e[0].rstrip(b'\0').decode();suffix=key if name=='common.bin' else key[4:]
            local[suffix]=64+h[5]+e[8]
        if name=='common.bin':offsets['exp_base']=local['exp_lut']
        elif not offsets.get('q_w'):offsets.update(local)
        else:assert all(offsets[k]==v for k,v in local.items())
    text=[]
    for key,value in offsets.items():
        name=('W_'+key[:-2].upper()) if key.endswith('_w') else key.upper()
        text.append(f'localparam integer {name}={value};\n')
    text.append('function automatic [31:0] header_word(input integer iscommon,input integer layer_id,input integer pos);\nbegin\n if(iscommon)case(pos)\n')
    for i,v in enumerate(heads['common.bin']):text.append(f'{i}:header_word=32\'h{v:08x};\n')
    text.append('default:header_word=0;endcase\n else case(layer_id*16+pos)\n')
    for layer in range(12):
        for i,v in enumerate(heads[f'layer_{layer:02d}.bin']):text.append(f'{layer*16+i}:header_word=32\'h{v:08x};\n')
    text.append('default:header_word=0;endcase\nend\nendfunction\n')
    (out/'profile_rom.svh').write_text(''.join(text),encoding='ascii')
    meta=json.loads((ROOT/'testdata/integer_v1/params/manifest.json').read_text());fixture=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r')
    labels=np.load(ROOT/'testdata/integer_v1/fixture/labels.npy');names=json.loads((ROOT/'testdata/integer_v1/fixture/manifest.json').read_text())['label_names']
    samples=[int(np.flatnonzero(labels==i)[0]) for i in range(12)];cases=[]
    for label,sample in enumerate(samples[:1] if quick else samples):
        q=np.clip(np.rint(fixture[sample].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
        taps={};Encoder(p,lambda n,v,c:taps.update({n:v[0].copy()}) if n.count('/')==1 else None)(q[None])
        current=q
        for layer in range(1 if quick else 12):
            current=q if layer==0 else taps[f'layer_{layer-1:02d}/layernorm2_output']
            if not quick and not matrix and layer!=label:continue
            index=len(cases);expected=taps[f'layer_{layer:02d}/layernorm2_output']
            hexwords(out/f'input_{index:03d}.hex',current.tobytes());hexwords(out/f'expected_{index:03d}.hex',expected.tobytes())
            # Debug scoreboard taps never enter the DUT.
            if index==0:
                for k in ['q_projection','k_projection','v_projection','layernorm1_output','gelu_output']:
                    hexwords(out/(k+'.hex'),taps[f'layer_{layer:02d}/'+k].tobytes())
            cases.append(dict(case=index,profile=layer,label=label,label_name=names[label],sample=sample));current=expected
    (out/'cases.txt').write_text(''.join(f'{c["case"]} {c["profile"]}\n' for c in cases),encoding='ascii')
    (out/'cases.json').write_text(json.dumps(cases,indent=2),encoding='utf-8')
    return cases

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--quick',action='store_true');ap.add_argument('--matrix',action='store_true');a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    cases=prepare(a.output,a.quick,a.matrix);bin=Path('E:/project/FPGAcompetition/RISCV_CPU/tools/iverilog/bin');logs=[]
    def run(cmd):
        r=subprocess.run(cmd,capture_output=True,text=True);logs.append(dict(command=cmd,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
        (a.output/'tool_log.json').write_text(json.dumps(logs,indent=2),encoding='utf-8')
        if r.returncode:raise RuntimeError(r.stdout+r.stderr)
        return r.stdout
    binary=a.output/'layer.vvp'
    source_hashes={}
    for path in [*[ROOT/'rtl/micro'/f for f in ['mul_pipe.sv','rne_pipe.sv','rq_pipe.sv','wide_arith.sv']],ROOT/'rtl/layer/kwt_layer.sv',ROOT/'rtl/layer/tb_layer.sv']:
        target=a.output/'rtl_source'/path.relative_to(ROOT/'rtl');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        source_hashes[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    (a.output/'rtl_source_hashes.json').write_text(json.dumps(source_hashes,indent=2),encoding='utf-8')
    run([str(bin/'iverilog.exe'),'-g2012','-I',str(a.output),'-s','tb_layer','-o',str(binary),
         *[str(ROOT/'rtl/micro'/f) for f in ['mul_pipe.sv','rne_pipe.sv','rq_pipe.sv','wide_arith.sv']],
         str(ROOT/'rtl/layer/kwt_layer.sv'),str(ROOT/'rtl/layer/tb_layer.sv')])
    start=time.time();result=run([str(bin/'vvp.exe'),str(binary),'+root='+str(a.output.resolve()).replace('\\','/')])
    assert f'PASS cases={len(cases)}' in result;print(result,flush=True)
    (a.output/'summary.json').write_text(json.dumps(dict(passed=True,quick=a.quick,cases=len(cases),profiles=sorted(set(c['profile'] for c in cases)),
        labels=sorted(set(c['label'] for c in cases)),coverage='full 12x12 cross product' if a.matrix else '12 profile/class pairs; every profile and class once',output_codes=len(cases)*6336,mismatches=0,elapsed=time.time()-start,
        result=result,scope='functional behavioral SRAM; macro/port lowering and whole-layer cycle equivalence pending'),indent=2),encoding='utf-8')
if __name__=='__main__':main()
