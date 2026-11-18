"""Real packet/input stream into the complete S16-first-input RTL candidate."""
import argparse
import json
import subprocess
import time
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
import validate_competitive_resident_core as core
from validate_layer_rtl import hexwords


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--stage',choices=['layer','full'],default='layer');ap.add_argument('--quick',action='store_true');ap.add_argument('--stress',action='store_true');ap.add_argument('--model',type=Path);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);rtl=ROOT/'rtl/input16_signed';base=ROOT/'testdata/input16_rtl_20261105/derivation'
    for f,h in json.loads((base/'manifest.json').read_text()).items():assert sha(base/f)==h
    for f in base.glob('*.bin'):hexwords(out/(f.name+'.hex'),f.read_bytes())
    x,indices=core.inputs(12);p=dict(np.load(component.BASE/'run/params/parameters.npz'));cases=[];saved={}
    for label in range(1 if a.quick else 12):
        ref=component.reference_stages(x[label:label+1],p);layer=label if a.stage=='layer' else 0
        source=x[label] if layer==0 else ref[f'layer_{layer-1:02d}/layernorm2_output'][0].astype(np.int16)
        expected=ref[f'layer_{layer if a.stage=="layer" else 11:02d}/layernorm2_output'][0]
        hexwords(out/f'input_{label:03d}.hex',source.astype('<i2').tobytes());hexwords(out/f'expected_{label:03d}.hex',expected.tobytes());saved[f'case{label:02d}_input']=source;saved[f'case{label:02d}_expected']=expected
        cases.append(dict(case=label,label=label,profile=layer,source_index=indices[label]))
        if label==0:
            for name in ['q_projection','k_projection','v_projection','layernorm1_output','gelu_output']:hexwords(out/(name+'.hex'),ref['layer_00/'+name][0].tobytes())
    np.savez_compressed(out/'fixtures.npz',**saved);(out/'cases.txt').write_text(''.join(f'{c["case"]} {c["profile"]}\n' for c in cases));(out/'cases.json').write_text(json.dumps(cases,indent=2))
    names=['kwt_sram_sp.sv','kwt_mac8x8.sv','kwt_iterative.sv','kwt_math.sv','kwt_packet_loader.sv','kwt_layer_banked.sv','kwt1_accel.sv'];sources=[ROOT/'rtl/micro/mul_pipe.sv',ROOT/'rtl/micro/rne_pipe.sv',*[rtl/n for n in names]]
    def run(command,name):
        result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+command],capture_output=True,text=True);(out/(name+'.log')).write_text(result.stdout+result.stderr);assert result.returncode==0,(name,result.stdout[-1500:],result.stderr[-1500:]);return result.stdout
    rel=out.relative_to(ROOT).as_posix();r=rtl.relative_to(ROOT).as_posix();single=int(a.stage=='layer');started=time.time()
    if a.model:model=a.model.resolve()
    else:
        model=out/'model';cmd=f'verilator --cc --exe --build -j 2 --no-timing --top-module kwt1_accel -Wno-fatal -DKWT_SIM -I{r}/generated -GSINGLE_LAYER={single} --Mdir {rel}/model -CFLAGS -O1 '+ ' '.join(s.relative_to(ROOT).as_posix() for s in sources)+f' {r}/sim_accel.cpp'
        # Absolute C++ path is required by make inside --Mdir.
        cmd=cmd.replace(f' {r}/sim_accel.cpp',f' /mnt/e/project/ChipCompetition/keyword-transformer/{r}/sim_accel.cpp');run(cmd,'build')
    text=run(f'{model.relative_to(ROOT).as_posix()}/Vkwt1_accel {rel} {single}'+(' stress' if a.stress else ''),'simulation');assert f'PASS cases={1 if a.stress else len(cases)} ' in text
    completed=1 if a.stress else len(cases);codes=0
    for c in cases[:completed]:
        data=b''.join(int(v,16).to_bytes(4,'little') for v in (out/f'observed_{c["case"]:03d}.hex').read_text().split());actual=np.frombuffer(data,np.int8).reshape(99,64);goal=saved[f'case{c["case"]:02d}_expected'];assert np.array_equal(actual,goal);codes+=actual.size
    metrics=[[int(v) for v in l.split()] for l in (out/'native_metrics.txt').read_text().splitlines()];assert len(metrics)==completed
    report=dict(passed=True,stage=a.stage,cases=cases[:completed],codes=codes,mismatches=0,real_13_packets=a.stage=='full',input_bytes=12672,output_bytes=6336,
        metrics=metrics,scope='actual 8x8 S16-first-input complete encoder RTL, native valid/ready, periodic core/SRAM/output stalls, includes final ACK; no CPU/SoC power',
        stress=a.stress,summary=text,model_directory=model.relative_to(ROOT).as_posix(),runtime_seconds=time.time()-started)
    (out/'verification.json').write_text(json.dumps(report,indent=2));bound=[Path(__file__),Path(component.__file__),Path(core.__file__),rtl/'sim_accel.cpp',rtl/'generated/kwt_profile.svh',component.BASE/'run/params/parameters.npz',*sources]
    (out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in bound},indent=2));(out/'manifest.json').write_text(json.dumps({f.relative_to(out).as_posix():sha(f) for f in out.rglob('*') if f.is_file() and 'model' not in f.relative_to(out).parts},indent=2));print(json.dumps(dict(passed=True,codes=codes,cycles=[m[2] for m in metrics]),indent=2))


if __name__=='__main__':main()
