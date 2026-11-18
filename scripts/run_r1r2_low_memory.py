"""Same arithmetic/schedule, disk lifetimes and O(cycles) compact sweep.

Optional memory-efficient front end to run_r1r2_evidence.py. The original
reproduction entry remains valid. This adapter changes instrumentation only;
its own hash/source are saved alongside each stage that uses it.
"""
import gzip
import hashlib
import json
import runpy
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from integer_model.event_arithmetic import Engine


class IntervalCount:
    def __init__(self):self.n=0
    def append(self,row):self.n+=1


def sweep(path,start,finish):
    # Two signed32 deltas suffice (<4096B live) but int64 avoids trusting that
    # bound before measuring it. No list of millions of tuples is retained.
    delta=np.zeros(finish-start+1,np.int64);positive=np.zeros(len(delta),np.uint8);negative=positive.copy()
    phases={'idle':0};names=['idle'];intervals=0
    for line in gzip.open(path,'rt',encoding='utf-8'):
        begin,end,size,name,phase=json.loads(line);intervals+=1
        assert start<=begin<=end<=finish and size>=0
        if phase not in phases:phases[phase]=len(names);names.append(phase)
        tag=phases[phase]
        if end>begin:
            delta[begin-start]+=size;delta[end-start]-=size
            if size:positive[begin-start]=tag;negative[end-start]=tag
    live=np.cumsum(delta);assert live.min()>=0 and live[-1]==0
    index=int(live.argmax());peak=int(live[index]);at=index+start
    tags=np.where(positive,positive,negative);phase_max=np.zeros(len(names),np.int64)
    np.maximum.at(phase_max,tags,live)
    allocations=[]
    for line in gzip.open(path,'rt',encoding='utf-8'):
        begin,end,size,name,phase=json.loads(line)
        if begin<=at<end:allocations.append({'name':name,'bytes':size,'phase':phase,'start':begin,'end':end})
    return {'peak_bytes':peak,'peak_cycle':at,'peak_live_allocations':allocations,
            'phase_peak_bytes':{name:int(phase_max[tag]) for name,tag in phases.items() if tag},'allocations':intervals}


original_init=Engine.__init__
def compact_init(self,*args,**kwargs):
    original_init(self,*args,**kwargs);self.intervals=IntervalCount();self.start_cycle=self.now;self.temporary_life=None
    if self.life is None:
        fd,path=tempfile.mkstemp(suffix='_r1_lifetimes.gz')
        import os
        os.close(fd);self.temporary_life=Path(path);self.life=gzip.open(path,'wt',encoding='utf-8',compresslevel=1)


def compact_close(self,allow=()):
    if self.queue:self.step(max(x[0] for x in self.queue)-self.now,'final_drain')
    assert not [c for c in self.cells.values() if c.storage=='register' and c not in allow],'register leaks'
    assert not self.allocs,'unreleased allocation'
    path=Path(self.life.name);self.life.close()
    if self.trace:self.trace.close()
    result=sweep(path,self.start_cycle,self.now);assert result['allocations']==self.intervals.n
    result.update(operations=dict(self.counts),dependency_wait_cycles=self.stalls,cycles=self.now,
                  lifetime_method='disk intervals + dense cycle sweep; arithmetic and schedule unchanged')
    if self.temporary_life:self.temporary_life.unlink()
    return result


def install():Engine.__init__=compact_init;Engine.close=compact_close


def save_adapter(args):
    folder=Path(args[args.index('--output')+1]) if '--output' in args else ROOT/'testdata/r1r2/release'
    folder.mkdir(parents=True,exist_ok=True);source=Path(__file__)
    shutil.copyfile(source,folder/'instrumentation_adapter.py')
    (folder/'instrumentation_adapter.json').write_text(json.dumps({'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'scope':'lifetime instrumentation only; original Engine issue/retire/compute and bank clock unchanged'},indent=2),encoding='utf-8')


def main():
    install()
    if len(sys.argv)>2 and sys.argv[1]=='--worker':
        script=sys.argv[2];args=sys.argv[3:];save_adapter(args);sys.argv=[script,*args]
        runpy.run_path(str(ROOT/script),run_name='__main__');return
    save_adapter(sys.argv[1:]);original_run=subprocess.run
    def child(cmd,*args,**kwargs):
        if len(cmd)>1 and cmd[1] in ['scripts/validate_kwt1_r1.py','scripts/validate_kwt1_r2.py','tests/integer/test_r1_boundaries.py']:
            cmd=[cmd[0],str(Path(__file__)),'--worker',cmd[1],*cmd[2:]]
        return original_run(cmd,*args,**kwargs)
    subprocess.run=child
    from run_r1r2_evidence import main as unified
    unified()


if __name__=='__main__':main()
