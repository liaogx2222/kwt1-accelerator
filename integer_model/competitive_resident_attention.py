"""Query-tiled QK -> Softmax -> PV on the SAME guarded 20 SP macros.

No score/probability external backing in resident mode. A paired reference
round-trips each intermediate with actual 32-bit-beat reads/writes. No CPU,
packet protocol, RTL timing or full-encoder residency claim.
"""
import numpy as np
from .competitive_attention import Attention16
from .competitive_hashed_banks import HashedScratch
from .competitive_tile16 import MacroClock
from .competitive_tile16_pipeline import ElasticClock


class GuardedClock(ElasticClock):
    def tick(self,ops=(),tag='memory'):
        extra=self.sidecar(ops) if getattr(self,'sidecar',None) else []
        all_ops=[*ops,*extra]
        for bank,address,mode,value in all_ops:
            if mode=='r' and (bank,address) not in self.initialized:raise ValueError('uninitialized SRAM read')
            if mode=='w' and any(a<=address<b for a,b in self.readonly.get(bank,[])):raise ValueError('readonly cache overwrite')
        values=MacroClock.tick(self,all_ops,tag)
        for bank,address,mode,value in all_ops:
            if mode=='w':self.initialized.add((bank,address))
        return values
    def lock(self,banks,start,end):
        for bank in banks:self.readonly.setdefault(bank,[]).append((start,end))


class GuardedScratch(HashedScratch):
    def invalidate(self,t):
        for bank,(base,size) in enumerate(zip(t.bases,t.sizes)):
            self.clock.initialized.difference_update((f'S{bank}',addr) for addr in range(base,base+size))
    def allocate(self,*a,**k):
        t=super().allocate(*a,**k);self.invalidate(t);return t
    def release(self,t):
        if t not in self.live:raise RuntimeError('scratch double free')
        self.invalidate(t);super().release(t)


class ResidentAttention(Attention16):
    Q_END=448
    P_BASE=448
    K_END=448
    V_BASE=448
    V_END=844
    def __init__(self,*args,materialize=False,**kwargs):
        super().__init__(*args,**kwargs);self.materialize=materialize
        self.b.__class__=GuardedClock
        self.b.initialized={(f'A{bank}',addr) for bank in range(8) for addr in range(self.LUT_BASE,1024)}
        self.b.readonly={};self.b.lock([f'A{b}' for b in range(8)],self.LUT_BASE,1024)
        self.s=GuardedScratch(self.b);self.transfers=[];self.query_blocks=[];self.guard_tests=[]
    def cache_values(self,t):
        self.b.stage='V_copy_resident'
        for tile in range(4):
            for row in range(0,99,2):
                words=self.b.batches([(*t.word(row,tile*16+c),'r',0) for c in range(16)],'V_SRAM_read')
                latch=self.e.source(np.array(words,np.int64),16,False,name='resident_V_copy_latch')
                for parity in range(min(2,99-row)):
                    ops=[]
                    for bank in range(8):
                        lo=(words[bank*2]>>(8*parity))&255;hi=(words[bank*2+1]>>(8*parity))&255
                        ops.append((f'B{bank}',self.V_BASE+tile*99+row+parity,'w',lo|(hi<<8)))
                    self.b.tick(ops,'resident_V_B_cache_write')
                self.e.drop(latch)
    def probability_cache(self,t):
        assert self.P_BASE+2*99<=self.LUT_BASE
        self.b.stage='probability_A_copy'
        for plane in range(2):
            for col in range(99):
                pairs=list(range(0,t.rows,2))
                words=self.b.batches([(*t.word(r,col,plane),'r',0) for r in pairs],'probability_SRAM_read')
                latch=self.e.source(np.array(words,np.int64),16,False,name='probability_copy_latch')
                data=dict(zip([r//2 for r in pairs],words))
                self.b.tick([(f'A{bank}',self.P_BASE+plane*99+col,'w',data.get(bank,0)) for bank in range(8)],'probability_A_cache_write')
                self.e.drop(latch)
    def external_read(self,t,label):
        self.b.stage=label;cache={};begin=self.b.cycle;words_count=0
        for plane in range(t.bits//8):
            for group in range((t.rows+7)//8):
                for col in range(t.cols):
                    loc=[t.word(row,col,plane) for row in range(group*8,min(group*8+8,t.rows),2)]
                    for start in range(0,len(loc),2):
                        batch=loc[start:start+2];allocation=self.e.allocate('external_halfword_latch',len(batch)*2)
                        words=self.b.tick([(bank,addr,'r',0) for bank,addr in batch],'external_32bit_read')
                        cache.update(zip(batch,words));words_count+=len(batch);self.e.release(allocation)
                        self.b.idle(self.beat_cycles-1,'external_sink_interval')
        result=np.empty((t.rows,t.cols),np.int64)
        for row in range(t.rows):
            for col in range(t.cols):
                value=sum(((cache[t.word(row,col,plane)]>>(8*(row%2)))&255)<<(8*plane) for plane in range(t.bits//8))
                if t.signed and value>=(1<<(t.bits-1)):value-=1<<t.bits
                result[row,col]=value
        dtype={(8,True):np.int8,(16,True):np.int16,(16,False):np.uint16,(32,True):np.int32}[(t.bits,t.signed)]
        self.transfers.append(dict(label=label,cycles=self.b.cycle-begin,halfwords=words_count,logical_bytes=result.size*t.bits//8))
        return result.astype(dtype)
    def roundtrip(self,t,label):
        values=self.external_read(t,label+'_read');before=self.b.cycle;self.b.stage=label+'_reload'
        t.write_host(values,self.beat_cycles)
        self.transfers.append(dict(label=label+'_reload',cycles=self.b.cycle-before,logical_bytes=values.nbytes))
    def negative_guards(self):
        for name,op in [('Q_cache_overwrite',('A0',0,'w',0)),('K_cache_overwrite',('B0',0,'w',0)),('V_cache_overwrite',('B0',self.V_BASE,'w',0)),('exp_cache_overwrite',('A0',self.LUT_BASE,'w',0)),('uninitialized_read',('B0',1023,'r',0))]:
            now=self.b.cycle
            try:self.b.tick([op],'negative_guard')
            except ValueError:self.guard_tests.append(name)
            else:raise AssertionError(name)
            assert self.b.cycle==now
    def attention(self,qt,kt,vt,params,key,observe=None):
        for start in range(0,99,16):self.load_A(qt,start,min(16,99-start),False)
        self.cache_keys(kt);self.cache_values(vt)
        self.b.lock([f'A{b}' for b in range(8)],0,self.Q_END)
        self.b.lock([f'B{b}' for b in range(8)],0,self.V_END)
        self.negative_guards()
        for t in [qt,kt,vt]:self.s.release(t)
        context=self.s.allocate('context',99,64,8)
        m=self.parameter(params[key+'_score_m'],'score_m');s=self.parameter(params[key+'_score_s'],'score_s')
        cm=self.parameter(params[key+'_ctx_m'],'context_m');cs=self.parameter(params[key+'_ctx_s'],'context_s')
        for start in range(0,99,16):
            count=min(16,99-start);begin=self.b.cycle
            score=self.s.allocate('score_tile',count,99,32);prob=self.s.allocate('probability_tile',count,99,16,False)
            for tile in range(7):
                acc=self.raw_mac(64,(start//16)*64,tile*64)
                values=np.asarray(self.e.consume(acc,'resident_score_write'),np.int64);self.b.stage='resident_QK_write'
                for plane in range(4):
                    ops=[]
                    for row in range(0,count,2):
                        for col in range(min(16,99-tile*16)):
                            value=(int(values[row,col])>>(8*plane))&255
                            if row+1<count:value|=((int(values[row+1,col])>>(8*plane))&255)<<8
                            ops.append((*score.word(row,tile*16+col,plane),'w',value))
                    self.b.batches(ops,'resident_score_word_write')
                self.e.drop(acc)
            if observe:observe('qk',start,score.debug_numpy())
            if self.materialize:self.roundtrip(score,'score_roundtrip')
            self.b.stage='resident_Softmax'
            for row in range(0,count,2):
                pair=self.read_pair(score,row);outputs=[]
                for r in range(min(2,count-row)):
                    a=self.e.source(self.e.consume(pair)[r].copy(),32,name='resident_Softmax_row')
                    outputs.append(self.softmax_row(a,m,s));self.e.drop(a)
                self.write_pair(prob,row,outputs);self.e.drop(pair)
            if observe:observe('softmax',start,prob.debug_numpy().astype(np.uint16))
            if self.materialize:self.roundtrip(prob,'probability_roundtrip')
            self.s.release(score);self.probability_cache(prob)
            for tile in range(4):
                while len(self.jobs)>=2:self.credit_stalls+=1;self.e.step(1,'resident_accumulator_credit')
                acc=self.raw_mac(99,self.P_BASE,self.V_BASE+tile*99,True,2)
                mm=self.e.source(np.full(16,int(self.e.consume(cm)),np.int64),32,name='resident_context_m_broadcast')
                ss=self.e.source(np.full(16,int(self.e.consume(cs)),np.int64),32,name='resident_context_s_broadcast')
                self.rq_write(acc,[mm,ss],context,start,count,tile*16);self.e.drop(mm);self.e.drop(ss)
            while self.jobs or self.products or self.outputs:self.e.step(1,'resident_query_RQ_drain')
            self.s.release(prob);self.query_blocks.append(dict(start=start,count=count,cycles=self.b.cycle-begin))
        for c in [m,s,cm,cs]:self.e.drop(c)
        if observe:observe('pv',0,context.debug_numpy())
        return context
    def run(self,q,k,v,branch,params,key,observe=None):
        assert q.shape==k.shape==v.shape==branch.shape==(99,64)
        assert q.dtype==k.dtype==v.dtype==np.int8 and branch.dtype in [np.int8,np.int16]
        self.b.stage='attention_cold_input'
        residual=self.s.allocate('retained_residual',99,64,branch.dtype.itemsize*8)
        qt=self.s.allocate('Q',99,64,8);kt=self.s.allocate('K',99,64,8);vt=self.s.allocate('V',99,64,8)
        for tensor,values in [(residual,branch),(qt,q),(kt,k),(vt,v)]:tensor.write_host(values,self.beat_cycles)
        context=self.attention(qt,kt,vt,params,key,observe)
        assert np.array_equal(residual.debug_numpy(),branch),'retained residual was overwritten'
        actual=self.external_read(context,'final_context_writeback')
        assert np.array_equal(actual,context.debug_numpy())
        self.s.release(context);self.s.release(residual);metrics=self.summary()
        metrics.update(scope='resident attention subgraph, retained residual; not resident encoder/CPU/packet/RTL proof',
            query_tiled_resident=True,intermediate_external_materialization=self.materialize,
            intermediate_external_logical_bytes=sum(x['logical_bytes'] for x in self.transfers if 'roundtrip' in x['label']),
            transfers=self.transfers,query_blocks=self.query_blocks,guard_tests=self.guard_tests,
            SRAM_reads=sum(v for (b,mode),v in self.b.counts.items() if mode=='r'),
            SRAM_writes=sum(v for (b,mode),v in self.b.counts.items() if mode=='w'),
            phase_cycles={f'{a}/{b}':v for (a,b),v in self.b.stage_cycles.items()},
            retained_residual_bits=branch.dtype.itemsize*8,retained_residual_unchanged=True,
            cache_regions=dict(A_Q=[0,self.Q_END],A_probability=[self.P_BASE,self.P_BASE+198],A_exp=[self.LUT_BASE,1024],B_K=[0,self.K_END],B_V=[self.V_BASE,self.V_END]))
        assert metrics['cycles']==sum(metrics['phase_cycles'].values())
        return actual,metrics
