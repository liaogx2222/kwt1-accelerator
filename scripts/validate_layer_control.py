import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from validate_layer_rtl import prepare
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--quick',action='store_true');a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True);prepare(a.output,True)
    tool=Path('E:/project/FPGAcompetition/RISCV_CPU/tools/iverilog/bin');binary=a.output/'control.vvp';logs=[]
    commands=[[str(tool/'iverilog.exe'),'-g2012','-I',str(a.output),'-s','tb_layer_control','-o',str(binary),
               *[str(ROOT/'rtl/micro'/f) for f in ['mul_pipe.sv','rne_pipe.sv','rq_pipe.sv','wide_arith.sv']],
               str(ROOT/'rtl/layer/kwt_layer.sv'),str(ROOT/'rtl/layer/tb_layer_control.sv')],
              [str(tool/'vvp.exe'),str(binary),'+root='+str(a.output.resolve()).replace('\\','/')]]
    for cmd in commands:
        r=subprocess.run(cmd,capture_output=True,text=True);logs.append(dict(command=cmd,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
        (a.output/'tool_log.json').write_text(json.dumps(logs,indent=2),encoding='utf-8')
        if r.returncode:raise RuntimeError(r.stdout+r.stderr)
    assert 'PASS control ' in logs[-1]['stdout'];print(logs[-1]['stdout'],flush=True)
    (a.output/'summary.json').write_text(json.dumps(dict(passed=True,result=logs[-1]['stdout']),indent=2),encoding='utf-8')
if __name__=='__main__':main()
