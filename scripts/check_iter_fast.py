"""Actual iterative RTL versus Python divmod/isqrt, latency/hold/reset contracts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess

ROOT=Path(__file__).resolve().parents[1];MASK=(1<<64)-1
CONFIGS={'default':(0,0,0,0),'short':(1,0,0,0),'radix4':(1,1,0,0),'fast':(1,1,1,1),'quad_only':(1,1,1,0),'double_only':(1,1,0,1)}
BENCH=r'''`timescale 1ns/1ps
module tb_iter;
 parameter SC=1,R4=1,R16=1,DSQ=1;
 reg clk=0;always #5 clk=~clk;
 reg rst=0,iv=0,ir=0,mode=0;reg[63:0]a=0,b=0;wire ready,valid,error;wire[63:0]q,r;
 kwt_iterative #(.SHORT_CONST_DIV(SC),.RADIX4_CONST(R4),.RADIX16_CONST(R16),.DOUBLE_SQRT(DSQ)) dut(clk,rst,iv,ready,mode,a,b,valid,ir,q,r,error);
 integer fd,rc,n=0,mode_i,err_i,latency,expected_latency,k,z,replacements=0,resets=0;
 reg[63:0]va,vb,vq,vr;reg[4095:0]vectors;
 function integer L(input integer sm,input[63:0]aa,bb);
  begin
   if(sm)L=DSQ?16:32;else if(bb==0)L=1;
   else if(SC&&aa==64'h10000000000)L=R16?11:R4?21:41;
   else if(SC&&aa==64'h800000000000)L=R16?12:R4?24:48;else L=64;
  end
 endfunction
 task reset_unit;
  begin
   @(negedge clk);rst=0;iv=0;ir=0;#1;if(valid||ready)$fatal(1,"ITER_RESET_COMBIN");
   repeat(3)@(negedge clk);rst=1;repeat(70)begin @(negedge clk);if(valid)$fatal(1,"ITER_RESET_GHOST");end
   resets=resets+1;
  end
 endtask
 initial begin
  if(!$value$plusargs("VECTORS=%s",vectors))$fatal(1,"VECTORS");reset_unit();fd=$fopen(vectors,"r");if(!fd)$fatal(1,"OPEN_VECTORS");
  while(!$feof(fd))begin
   rc=$fscanf(fd,"%d %h %h %h %h %d\n",mode_i,va,vb,vq,vr,err_i);
   if(rc==6)begin
    @(negedge clk);mode=mode_i;a=va;b=vb;iv=1;ir=0;expected_latency=L(mode_i,va,vb);
    @(posedge clk);if(!ready)$fatal(1,"ITER_IDLE_NOT_READY");latency=1;
    @(negedge clk);
    if(n%17==0)begin mode=0;a=17;b=5;iv=1;end else begin iv=0;a=~va;b=~vb;mode=!mode_i;end
    while(!valid)begin
     if(ready)$fatal(1,"ITER_BUSY_READY");@(negedge clk);latency=latency+1;if(latency>65)$fatal(1,"ITER_TIMEOUT");
    end
    if(q!==vq||r!==vr||error!==err_i[0]||latency!=expected_latency)
     $fatal(1,"ITER_VECTOR n=%0d A=%h B=%h mode=%0d Q=%h/%h R=%h/%h err=%b/%b L=%0d/%0d",n,va,vb,mode_i,q,vq,r,vr,error,err_i[0],latency,expected_latency);
    repeat(n%5+1)begin @(negedge clk);if(!valid||ready||q!==vq||r!==vr||error!==err_i[0])$fatal(1,"ITER_HELD");end
    ir=1;
    @(posedge clk);if(n%17==0&&!ready)$fatal(1,"ITER_REPLACE_NOT_READY");
    @(negedge clk);ir=0;iv=0;
    if(n%17==0)begin
     latency=1;while(!valid)begin @(negedge clk);latency=latency+1;if(latency>65)$fatal(1,"ITER_REPLACE_TIMEOUT");end
     if(q!==64'd3||r!==64'd2||error||latency!=64)$fatal(1,"ITER_REPLACE_RESULT");
     ir=1;@(negedge clk);ir=0;replacements=replacements+1;
    end
    n=n+1;
   end
  end
  $fclose(fd);
  // In-flight reset of generic div, sqrt and both specialized numerators.
  for(k=0;k<4;k=k+1)for(z=0;z<2;z=z+1)begin
   @(negedge clk);mode=k==1;a=k==2?64'h10000000000:k==3?64'h800000000000:64'hffffffffffffffff;b=17;iv=1;ir=0;
   @(posedge clk);if(!ready)$fatal(1,"ITER_RESET_SETUP");@(negedge clk);iv=0;
   repeat(z==0?1:L(k==1,a,b)-2)@(negedge clk);reset_unit();
  end
  // Reset while a result is held, then reject any late response.
  @(negedge clk);mode=0;a=17;b=5;iv=1;@(negedge clk);iv=0;wait(valid);repeat(3)@(negedge clk);reset_unit();
  $display("PASS ITER_FAST vectors=%0d replacements=%0d resets=%0d SC=%0d R4=%0d R16=%0d DSQ=%0d",n,replacements,resets,SC,R4,R16,DSQ);$finish;
 end
 initial begin #500000000;$fatal(1,"ITER_UNIT_WATCHDOG");end
endmodule
'''
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    source=ROOT/'rtl/iter_fast/kwt_iterative.sv';rng=random.Random(20261115);rows=[]
    for aa in [0,1,2,3,(1<<32)-1,1<<40,1<<47,MASK]:
        ds=set(range(18))|{1<<63,MASK,max(0,aa-1),aa,min(MASK,aa+1)}
        ds|={x for bit in range(1,64) for x in [(1<<bit)-1,1<<bit,(1<<bit)+1]}
        for bb in sorted(ds):
            q,r=divmod(aa,bb) if bb else (0,0);rows.append((0,aa,bb,q,r,int(bb==0)))
    for i in range(4096):
        aa=[1<<40,1<<47,rng.getrandbits(64)][i%3];bb=rng.getrandbits(17 if i%2 else 64)
        q,r=divmod(aa,bb) if bb else (0,0);rows.append((0,aa,bb,q,r,int(bb==0)))
    roots=[0,1,2,3,(1<<32)-1]+[1<<i for i in range(32)]+[rng.getrandbits(32) for _ in range(1024)]
    values={0,MASK}|{r*r+d for r in roots for d in [-1,0,1] if 0<=r*r+d<=MASK}|{rng.getrandbits(64) for _ in range(4096)}
    for aa in sorted(values):q=math.isqrt(aa);rows.append((1,aa,0,q,aa-q*q,0))
    def save(p,records):p.write_text(''.join(f'{m} {aa:016x} {bb:016x} {q:016x} {r:016x} {e}\n' for m,aa,bb,q,r,e in records))
    save(out/'compat.txt',rows);fast_rows=rows+[(1,aa,0,math.isqrt(aa),aa-math.isqrt(aa)**2,0) for aa in range(65536)];save(out/'fast.txt',fast_rows)
    (out/'tb_iter.sv').write_text(BENCH);iv=Path('C:/iverilog/bin/iverilog.exe');vv=iv.with_name('vvp.exe')
    def one(item):
        label,params=item;d=out/label;d.mkdir();exe=d/'sim.vvp';vectors=out/('fast.txt' if label=='fast' else 'compat.txt');count=len(fast_rows) if label=='fast' else len(rows)
        cmds=[[iv,'-g2012','-DKWT_SIM','-s','tb_iter',*[f'-Ptb_iter.{k}={v}' for k,v in zip(['SC','R4','R16','DSQ'],params)],'-o',exe,source,out/'tb_iter.sv'],[vv,exe,'+VECTORS='+str(vectors)]]
        for cmd,name in zip(cmds,['compile.log','run.log']):
            with (d/name).open('w') as log:q=subprocess.run(list(map(str,cmd)),cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
            assert q.returncode==0,str(d/name)
        log=(d/'run.log').read_text();assert f'PASS ITER_FAST vectors={count} replacements={(count+16)//17} resets=10' in log,log[-1000:]
        r=dict(passed=True,params=params,vectors=count,zero_divisor=True,held=True,same_cycle_replacements=(count+16)//17,reset_groups=10,
            vector_file=vectors.name,vector_SHA256=sha(vectors),commands=[[str(x) for x in cmd] for cmd in cmds],log_SHA256=sha(d/'run.log'))
        (d/'summary.json').write_text(json.dumps(r,indent=2)+'\n');print(label,log.strip(),flush=True);return label,r
    with ThreadPoolExecutor(max_workers=3) as pool:cases=dict(pool.map(one,CONFIGS.items()))
    result=dict(passed=True,four_state=True,source_SHA256=sha(source),bench_SHA256=sha(out/'tb_iter.sv'),seed=20261115,exhaustive_sqrt_input0_to65535=True,
        Python_divmod_isqrt_independent_oracle=True,cases=cases,tools={str(p):sha(p) for p in [iv,vv]},vectors_reproducible_from_script=True)
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
