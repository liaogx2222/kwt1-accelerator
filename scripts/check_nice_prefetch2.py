"""Independent four-state block-transfer/negative-contract scoreboard."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    baseline=out/'baseline.sv';baseline.write_bytes(subprocess.check_output(['git','show','595724b88858b142a407f6a5c4761945252d523b:rtl/arch60_block/kwt_nice_block.sv'],cwd=ROOT))
    bench=ROOT/'rtl/nice_prefetch2/tb_nice_prefetch2.sv';iv=Path('C:/iverilog/bin/iverilog.exe');vv=iv.with_name('vvp.exe');rows={}
    for label,source,depth in [('baseline',baseline,1),('prefetch',ROOT/'rtl/nice_prefetch2/kwt_nice_block.sv',2)]:
        exe=out/(label+'.vvp');commands=[[iv,'-g2012','-s','tb_nice_prefetch2','-Ptb_nice_prefetch2.EXPECT_DEPTH='+str(depth),'-o',exe,bench,source],[vv,exe]]
        for cmd,name in zip(commands,['compile','run']):
            result=subprocess.run(list(map(str,cmd)),cwd=ROOT,capture_output=True,text=True,timeout=180)
            log=out/(label+'_'+name+'.log');log.write_text('returncode='+str(result.returncode)+'\n'+result.stdout+result.stderr)
            assert result.returncode==0,str(log)
        log=(out/(label+'_run.log')).read_text();match=re.search(r'PASS NICE_PREFETCH depth=(\d+) successes=(\d+) faults=(\d+) request_deadlines=(\d+) response_deadlines=(\d+) sink_deadlines=(\d+)',log)
        assert match and int(match.group(1))==depth
        rows[label]=dict(passed=True,result=match.group(0),cases=[list(map(int,m)) for m in re.findall(r'NICE_CASE test=(\d+) kind=(\d+) words=(\d+) code=(\d+) cursor=(\d+) issued=(\d+) peak=(\d+) cycles=(\d+)',log)],
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),commands=[[str(x) for x in cmd] for cmd in commands]);print(label,match.group(0),flush=True)
    r=dict(passed=True,four_state=True,TIMEOUT=32,scope='existing NICE read/write instruction contract only; not complete SoC or gate',cases=rows,
        bench_sha256=hashlib.sha256(bench.read_bytes()).hexdigest(),tool_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [iv,vv]})
    (out/'summary.json').write_text(json.dumps(r,indent=2)+'\n')
