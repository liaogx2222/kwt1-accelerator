"""Four-state actual production max function versus independent integer max."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    source=ROOT/'rtl/softmax_stream/kwt_layer_banked.sv';s=source.read_text();start=s.index(' function automatic signed[31:0] score_max_step');end=s.index(' endfunction',start)+len(' endfunction');fn=s[start:end]
    edge=[-(1<<31),-(1<<31)+1,-65536,-1,0,1,65535,(1<<31)-2,(1<<31)-1];rng=random.Random(20261115);vectors=[]
    for old in edge:
        for value in edge:
            for first in [0,1]:vectors.append((old,value,first,max(-(1<<31)+1 if first else old,value)))
    for i in range(8192):
        old=rng.randrange(-(1<<31),1<<31);value=rng.randrange(-(1<<31),1<<31);first=i%17==0
        vectors.append((old,value,first,max(-(1<<31)+1 if first else old,value)))
    payload=''.join('%026x\n'%(((old&0xffffffff)<<72)|((value&0xffffffff)<<40)|(int(first)<<32)|(expected&0xffffffff)) for old,value,first,expected in vectors)
    (out/'vectors.hex').write_text(payload)
    tb='''module tb_max;
FUNCTION
 reg[103:0]vectors[0:COUNT-1];reg signed[31:0]old_max,value;reg first;integer i;
 initial begin
  $readmemh("vectors.hex",vectors);
  for(i=0;i<COUNT;i=i+1)begin
   old_max=vectors[i][103:72];value=vectors[i][71:40];first=vectors[i][32];#1;
   if(score_max_step(old_max,value,first)!==vectors[i][31:0])$fatal(1,"MAX_MISMATCH index=%0d",i);
  end
  old_max='x;value=-1;first=1;#1;if(score_max_step(old_max,value,first)!==-32'sd1)$fatal(1,"MAX_FIRST_UNKNOWN_OLD");
  value=-32'sd2147483648;#1;if(score_max_step(old_max,value,first)!==-32'sd2147483647)$fatal(1,"MAX_SENTINEL");
  $display("PASS STREAM_MAX cases=COUNT unknown_old_first=2");$finish;
 end
endmodule
'''.replace('FUNCTION',fn).replace('COUNT',str(len(vectors)))
    (out/'tb_max.sv').write_text(tb);iv=Path('C:/iverilog/bin/iverilog.exe');vv=iv.with_name('vvp.exe')
    cmds=[[iv,'-g2012','-s','tb_max','-o',out/'sim.vvp',out/'tb_max.sv'],[vv,out/'sim.vvp']]
    for cmd,name in zip(cmds,['compile.log','run.log']):
        q=subprocess.run(list(map(str,cmd)),cwd=out,capture_output=True,text=True);(out/name).write_text('returncode='+str(q.returncode)+'\n'+q.stdout+q.stderr);assert q.returncode==0,str(out/name)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    r=dict(passed=True,four_state=True,integer_max_vectors=len(vectors),unknown_old_first_tests=2,source_SHA256=sha(source),function_SHA256=hashlib.sha256(fn.encode()).hexdigest(),
        files={n:sha(out/n) for n in ['vectors.hex','tb_max.sv','compile.log','run.log']},tools={str(p):sha(p) for p in [iv,vv]},commands=[[str(x) for x in cmd] for cmd in cmds],scope='actual max function, not full-SoC/vendor/gate four-state')
    (out/'summary.json').write_text(json.dumps(r,indent=2)+'\n');print((out/'run.log').read_text())
