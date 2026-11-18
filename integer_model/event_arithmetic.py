"""Value-driven integer events and explicit register lifetimes (R1).

An event stores operands at issue, computes its result ONLY at retirement, and
exposes that result only after ready. No Encoder calls. Arrays denote physical
PE lanes/buffers, not floating point emulation. Clock may be the SRAM scheduler.
"""
import collections
import gzip
import heapq
import json
import math
import numpy as np


def native(x):
    return x.tolist() if isinstance(x,np.ndarray) else int(x)


def round_even(n,d):
    if d<=0:raise ValueError('nonpositive divisor')
    q,r=divmod(abs(int(n)),int(d))
    q+=int(r>d-r or (r==d-r and q%2))
    return -q if n<0 else q


def signed_shift(n,s):
    n,s=int(n),int(s)
    if n==-(1<<63):raise OverflowError('INT64_MIN outside fixed RNE domain')
    if s>=0:return round_even(n,1<<s)
    result=n<<(-s)
    if abs(result)>(1<<63)-1:raise OverflowError('left shift outside symmetric signed64 domain')
    return result


class Cell:
    def __init__(self,engine,ident,bits,signed,shape,ready,value=None,storage='register'):
        self.e,self.id,self.bits,self.signed,self.shape=engine,ident,bits,signed,tuple(shape)
        self.ready,self.value,self.storage,self.freed=ready,value,storage,False
    def view(self,index):return View(self,index)


class View:
    def __init__(self,parent,index):self.parent,self.index=parent,index


class Engine:
    def __init__(self,clock=None,trace=None,lifetimes=None,mul_latency=3,div_latency=64,sqrt_latency=32,corrupt=None):
        self.clock=clock;self.cycle=0;self.seq=0;self.queue=[];self.cells={};self.next_issue={}
        self.lat={'mul':mul_latency,'mac':1,'div':div_latency,'sqrt':sqrt_latency,'alu':1,'rne':1}
        self.II={'mul':1,'mac':1,'div':div_latency,'sqrt':sqrt_latency,'alu':1,'rne':1}
        self.trace=gzip.open(trace,'wt',encoding='utf-8',compresslevel=2) if trace else None
        self.life=gzip.open(lifetimes,'wt',encoding='utf-8',compresslevel=2) if lifetimes else None
        self.allocs={};self.intervals=[];self.serial=0;self.counts=collections.Counter();self.corrupt=corrupt;self.stalls=0
        self.phase='init';self.unit_state={}
    @property
    def now(self):return self.clock.cycle if self.clock is not None else self.cycle
    def log(self,row):
        if self.trace:self.trace.write(json.dumps(row,separators=(',',':'))+'\n')
    def allocate(self,name,nbytes,start=None):
        self.serial+=1;key=self.serial;self.allocs[key]=(self.now if start is None else start,int(nbytes),name,self.phase)
        return key
    def release(self,key,end=None):
        if key is None:return
        start,size,name,phase=self.allocs.pop(key);finish=self.now if end is None else end
        assert finish>=start
        row=(start,finish,size,name,phase);self.intervals.append(row)
        if self.life:self.life.write(json.dumps(row,separators=(',',':'))+'\n')
    def source(self,value,bits=32,signed=True,storage='register',name='source',allocation=None):
        arr=np.asarray(value) if not isinstance(value,int) else value
        if isinstance(arr,np.ndarray) and arr.ndim==0:arr=int(arr)
        self.validate(arr,bits,signed)
        self.seq+=1;c=Cell(self,self.seq,bits,signed,np.shape(arr),self.now,arr,storage)
        c.alloc=allocation if allocation is not None else (self.allocate(name,self.bytes(c)) if storage=='register' else None)
        self.cells[c.id]=c
        self.log({'type':'source','id':c.id,'time':self.now,'bits':bits,'signed':signed,'storage':storage,'value':native(arr),'name':name})
        return c
    @staticmethod
    def bytes(c):return max(1,math.prod(c.shape))*((c.bits+7)//8)
    @staticmethod
    def validate(v,bits,signed):
        lo=-(1<<(bits-1)) if signed else 0;hi=(1<<(bits-int(signed)))-1
        a=np.asarray(v) if isinstance(v,np.ndarray) else None
        minimum=int(a.min()) if a is not None else int(v);maximum=int(a.max()) if a is not None else int(v)
        if minimum<lo or maximum>hi:raise OverflowError(f'{minimum}..{maximum} outside {bits}-bit signed={signed}')
    def step(self,n,reason='arithmetic_wait'):
        if n<0:raise ValueError(n)
        if self.clock is None:self.cycle+=n
        elif n:self.clock.idle(n,reason)
        self.retire()
    def retire(self):
        while self.queue and self.queue[0][0]<=self.now:
            ready,ident,c,op,args,meta=heapq.heappop(self.queue)
            value=self.compute(op,args)
            if self.corrupt and self.corrupt(meta):value=value+1
            self.validate(value,c.bits,c.signed);c.value=value
            self.release(meta['inflight_alloc'],ready)
            if meta['unit_state_alloc'] is not None:self.release(meta['unit_state_alloc'],ready)
            self.log({'type':'complete','id':ident,'issue':meta['issue'],'ready':ready,'observed_at':self.now,
                'phase':meta['phase'],'op':op,'unit':meta['unit'],'bits':c.bits,'signed':c.signed,
                'operands':meta['operands'],'result':native(value)})
    def read(self,c,wait=True,consumer='host_store'):
        if self.clock is not None and hasattr(self.clock,'check'):self.clock.check()
        view=c if isinstance(c,View) else None;c=view.parent if view else c
        if c.freed:raise RuntimeError('use after free')
        if c.ready>self.now:
            if not wait:raise RuntimeError('early use')
            self.stalls+=c.ready-self.now;self.step(c.ready-self.now,'dependency_stall')
        self.retire()
        if c.value is None:raise RuntimeError('unretired result')
        value=c.value[view.index] if view and c.shape else c.value
        if isinstance(value,np.generic):value=int(value)
        return value
    def consume(self,c,name='store'):
        value=self.read(c);root=c.parent if isinstance(c,View) else c
        self.log({'type':'consume','id':root.id,'index':native_index(c.index) if isinstance(c,View) else None,'at':self.now,'consumer':name,'value':native(value)})
        return value
    def drop(self,c):
        if c is None:return
        if c.freed:raise RuntimeError('double free')
        self.retire();self.release(c.alloc);c.freed=True;self.cells.pop(c.id,None)
    def operand(self,arg):
        if isinstance(arg,(Cell,View)):
            root=arg.parent if isinstance(arg,View) else arg
            val=self.read(arg)
            return val,{'id':root.id,'index':native_index(arg.index) if isinstance(arg,View) else None,
                'bits':root.bits,'signed':root.signed,'value':native(val)}
        value=int(arg)
        return value,{'id':None,'bits':64 if value<0 or value>0x7fffffff else 32,'signed':value<0,'value':value}
    def issue(self,op,args,bits=64,signed=True,unit='alu',shape=(),release=(),advance=True):
        operands=[self.operand(a) for a in args]
        if unit=='mul':
            for v,r in operands:
                self.validate(v,32,r['signed']);r['input_port_bits']=32
        start=max(self.now,self.next_issue.get(unit,self.now))
        if start>self.now:self.step(start-self.now,'resource_stall')
        self.seq+=1;ident=self.seq;ready=start+self.lat[unit]
        for c in release:self.drop(c)
        c=Cell(self,ident,bits,signed,shape,ready)
        c.alloc=self.allocate(op+'_result',self.bytes(c));self.cells[ident]=c
        inbits=sum((np.size(v) if isinstance(v,np.ndarray) else 1)*r.get('input_port_bits',r['bits']) for v,r in operands)
        extra=max(0,(inbits+7)//8-self.bytes(c))
        inflight=self.allocate(op+'_pipeline_inputs',extra)
        state=self.allocate(unit+'_iterative_state',40 if unit=='div' else 32) if unit in ['div','sqrt'] else None
        meta={'issue':start,'unit':unit,'phase':self.phase,'operands':[r for v,r in operands],
              'inflight_alloc':inflight,'unit_state_alloc':state,'id':ident,'op':op}
        heapq.heappush(self.queue,(ready,ident,c,op,[v for v,r in operands],meta))
        self.next_issue[unit]=start+self.II[unit];self.counts[op]+=max(1,math.prod(shape))
        self.log({'type':'issue','id':ident,'at':start,'ready':ready,'op':op,'unit':unit,'phase':self.phase,
                  'operands':meta['operands'],'bits':bits,'signed':signed,'shape':shape})
        if advance:self.step(1,'issue_'+unit)
        return c
    @staticmethod
    def compute(op,a):
        if op=='mul':return a[0]*a[1]
        if op=='mac':return a[2]+np.asarray(a[0],np.int64)[:,None]*np.asarray(a[1],np.int64)[None,:]
        if op=='add':return a[0]+a[1]
        if op=='sub':return a[0]-a[1]
        if op=='max':return max(a[0],a[1])
        if op=='shl':return a[0]<<int(a[1])
        if op=='shr':return a[0]>>int(a[1])
        if op=='rne':return signed_shift(a[0],a[1])
        if op in ['rne_sat8','rne_sat16']:
            qmax=127 if op.endswith('8') else 32767
            return max(-qmax,min(qmax,signed_shift(a[0],a[1])))
        if op=='divmod':
            if a[1]<=0:raise ValueError('division by zero')
            return np.array(divmod(int(a[0]),int(a[1])),np.uint64)
        if op=='sqrt':return math.isqrt(int(a[0]))
        if op=='round_qr':
            q,r,d=map(int,a);return q+int(r>d-r or (r==d-r and q%2))
        if op=='ceil_qr':return int(a[0])+int(a[1]!=0)
        if op=='correct_qr':
            n,q,qd,d=map(int,a)
            if qd>n:q-=1;qd-=d
            return np.array([q,n-qd],np.uint64)
        raise ValueError(op)
    def pack(self,cells,shape,bits=32,signed=True,name='pack'):
        values=[self.consume(c,name) for c in cells]
        for c in cells:self.drop(c)
        return self.source(np.array(values,np.int64).reshape(shape),bits,signed,name=name)
    def close(self,allow=()):
        if self.queue:self.step(max(x[0] for x in self.queue)-self.now,'final_drain')
        remaining=[c for c in self.cells.values() if c.storage=='register' and c not in allow]
        if remaining:raise RuntimeError('register leaks '+str([(c.id,c.shape) for c in remaining[:10]]))
        events=[]
        for start,end,size,name,phase in self.intervals:
            if end>start:events.extend([(start,size,name,phase),(end,-size,name,phase)])
        events.sort(key=lambda x:(x[0],x[1]));live=peak=0;peak_time=0;by_phase=collections.defaultdict(int)
        for t,size,name,phase in events:
            live+=size;assert live>=0
            by_phase[phase]=max(by_phase[phase],live)
            if live>peak:peak,peak_time=live,t
        assert live==0 and not self.allocs
        at_peak=[{'name':name,'bytes':size,'phase':phase,'start':start,'end':end} for start,end,size,name,phase in self.intervals if start<=peak_time<end]
        if self.trace:self.trace.close()
        if self.life:self.life.close()
        return {'peak_bytes':peak,'peak_cycle':peak_time,'peak_live_allocations':at_peak,'phase_peak_bytes':dict(by_phase),
                'operations':dict(self.counts),'dependency_wait_cycles':self.stalls,'cycles':self.now,'allocations':len(self.intervals)}


def native_index(i):return list(i) if isinstance(i,tuple) else i
