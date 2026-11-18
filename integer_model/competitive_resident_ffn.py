"""Same-bank FC1 -> GELU -> FC2, retained LN1 and checked in-place shrink.

No external hidden backing in resident mode. A paired materialized mode uses
actual 32bit/clock round trips. Consumption sets are assertion-only monitors;
the fixed execution schedule never consults them to choose addresses.
"""
import numpy as np
from .competitive_resident_attention import ResidentAttention,GuardedClock
from .competitive_hashed_banks import HashedTensor
from .competitive_tile16 import MacroClock


class FFNClock(GuardedClock):
    def tick(self,ops=(),tag='memory'):
        extra=self.sidecar(ops) if getattr(self,'sidecar',None) else []
        all_ops=[*ops,*extra]
        for bank,address,mode,value in all_ops:
            if mode=='r' and (bank,address) not in self.initialized:raise ValueError('uninitialized SRAM read')
            if mode=='w' and any(a<=address<b for a,b in self.readonly.get(bank,[])):raise ValueError('readonly cache overwrite')
            if mode=='w' and (bank,address) in self.unconsumed:raise ValueError('FC2 overwrite before consumption')
        values=MacroClock.tick(self,all_ops,tag)
        for bank,address,mode,value in all_ops:
            key=(bank,address)
            if mode=='w':self.initialized.add(key)
            elif tag=='scratch_operand_read' and key in self.unconsumed:
                self.unconsumed.remove(key);self.consumed_words+=1
        return values


class ShrinkView(HashedTensor):
    def word(self,*a,**k):
        if self.owner is not None and not self.owner.valid:raise RuntimeError('in-place owner released')
        return super().word(*a,**k)


class ResidentFFN(ResidentAttention):
    def __init__(self,*a,**k):
        super().__init__(*a,**k);self.b.__class__=FFNClock
        self.b.unconsumed=set();self.b.consumed_words=0;self.allocation_log=[];self.rejected=[]
    def snapshot(self,label):
        live=[dict(name=t.name,bases=t.bases,sizes=t.sizes) for t in self.s.live]
        for bank in range(4):
            spans=sorted([(t.bases[bank],t.bases[bank]+t.sizes[bank]) for t in self.s.live]+self.s.free[bank])
            assert spans[0][0]==0 and spans[-1][1]==4096
            assert all(a[1]==b[0] for a,b in zip(spans,spans[1:])),(bank,spans)
        self.allocation_log.append(dict(label=label,cycle=self.b.cycle,live=live,free=[[list(x) for x in ranges] for ranges in self.s.free]))
    def expect_rejected(self,name,ops):
        now=self.b.cycle
        try:self.b.tick(ops,'negative_guard')
        except ValueError:self.rejected.append(name)
        else:raise AssertionError(name)
        assert self.b.cycle==now
    def dense_into(self,source,dest,p,key):
        self.load_weights(p[key+'_w']);self.b.lock([f'B{b}' for b in range(8)],0,1024)
        local=source.cols==256
        if not local:
            for start in range(0,99,16):self.load_A(source,start,min(16,99-start),False)
            self.b.lock([f'A{b}' for b in range(8)],0,448)
            for tile in range(dest.cols//16):
                coeff=self.fetch_coeff(p[key+'_m'],p[key+'_s'],p[key+'_b'],tile*16)
                for start in range(0,99,16):
                    count=min(16,99-start);acc=self.mac(source,start,count,tile,coeff,False)
                    self.rq_write(acc,coeff,dest,start,count,tile*16)
                for c in coeff:self.e.drop(c)
        else:
            for start in range(0,99,16):
                count=min(16,99-start);self.load_A(source,start,count,True)
                for tile in range(dest.cols//16):
                    coeff=self.fetch_coeff(p[key+'_m'],p[key+'_s'],p[key+'_b'],tile*16)
                    acc=self.mac(source,start,count,tile,coeff,True);self.rq_write(acc,coeff,dest,start,count,tile*16)
                    for c in coeff:self.e.drop(c)
        while self.jobs or self.products or self.outputs:self.e.step(1,'resident_FFN_RQ_drain')
        for bank in range(8):
            self.b.readonly.pop(f'B{bank}',None)
            self.b.readonly[f'A{bank}']=[(self.LUT_BASE,1024)]
    def gelu_into(self,t,table):
        self.b.stage='resident_GELU_cache';words=np.frombuffer(table.tobytes(),dtype='<u2')
        for address,word in enumerate(words):self.b.tick([(f'B{bank}',address,'w',int(word)) for bank in range(8)],'GELU_eight_copy_fill')
        self.b.lock([f'B{b}' for b in range(8)],0,128);self.b.stage='resident_GELU'
        for row in range(0,99,2):
            for start in range(0,256,4):
                loc=[t.word(row,col) for col in range(start,start+4)]
                words=self.b.tick([(bank,address,'r',0) for bank,address in loc],'GELU_input_read')
                codes=np.array([((word>>(8*r))&255) for word in words for r in range(2)],np.int64);codes=np.where(codes>=128,codes-256,codes)
                source=self.e.source(codes,8,name='resident_GELU_input_latch');indexes=codes+128
                look=self.b.tick([(f'B{i}',int(index)//2,'r',0) for i,index in enumerate(indexes)],'GELU_cache_lookup')
                values=np.array([(look[i]>>(8*(int(index)%2)))&255 for i,index in enumerate(indexes)],np.int64)
                values=np.where(values>=128,values-256,values);cell=self.e.source(values,8,name='resident_GELU_output_latch')
                ops=[]
                for i,(bank,address) in enumerate(loc):
                    value=int(values[2*i])&255
                    if row+1<99:value|=(int(values[2*i+1])&255)<<8
                    ops.append((bank,address,'w',value))
                self.b.tick(ops,'GELU_inplace_write');self.e.drop(source);self.e.drop(cell)
        for bank in range(8):self.b.readonly.pop(f'B{bank}',None)
    def output_alias(self,hidden):
        sizes=[800]*4
        view=ShrinkView(self.s,'FC2_output',99,64,8,True,0,hidden.bases.copy(),[0]*4,sizes)
        view.strides=sizes.copy();view.owner=hidden
        self.b.unconsumed={(f'S{bank}',address) for bank,(base,size) in enumerate(zip(hidden.bases,hidden.sizes)) for address in range(base,base+size)}
        self.expect_rejected('write_unconsumed_first',[(*hidden.word(0,0),'w',0)])
        self.expect_rejected('write_unconsumed_tail',[(*hidden.word(98,255),'w',0)])
        return view
    def commit_shrink(self,hidden,view):
        assert not self.b.unconsumed and self.b.consumed_words==12800
        assert all(new<=old for new,old in zip(view.sizes,hidden.sizes))
        for bank,(base,old,new) in enumerate(zip(hidden.bases,hidden.sizes,view.sizes)):
            self.b.initialized.difference_update((f'S{bank}',addr) for addr in range(base+new,base+old))
            ranges=sorted(self.s.free[bank]+[(base+new,base+old)]);merged=[]
            for a,b in ranges:
                if merged and merged[-1][1]==a:merged[-1]=(merged[-1][0],b)
                else:merged.append((a,b))
            self.s.free[bank]=merged
        self.s.live[self.s.live.index(hidden)]=view;hidden.valid=False;view.owner=None
        try:hidden.word(0,0)
        except RuntimeError:self.rejected.append('old_hidden_handle_invalid')
        else:raise AssertionError('old hidden alias remained valid')
        self.snapshot('after_FC2_shrink')
    def ffn(self,residual,p,key,observe=None):
        hidden=self.s.allocate('hidden_256',99,256,8);self.snapshot('residual_plus_hidden')
        for bank,(base,size) in enumerate(zip(residual.bases,residual.sizes)):self.b.lock([f'S{bank}'],base,base+size)
        self.expect_rejected('retained_residual_overwrite',[(*residual.word(0,0),'w',0)])
        self.expect_rejected('exp_cache_overwrite',[('A0',self.LUT_BASE,'w',0)])
        self.expect_rejected('uninitialized_hidden_read',[(*hidden.word(0,0),'r',0)])
        self.dense_into(residual,hidden,p,key+'_fc1')
        if observe:observe('fc1',hidden.debug_numpy())
        if self.materialize:self.roundtrip(hidden,'FC1_roundtrip')
        self.gelu_into(hidden,p[key+'_gelu_lut'])
        if observe:observe('gelu',hidden.debug_numpy())
        if self.materialize:self.roundtrip(hidden,'GELU_roundtrip')
        view=self.output_alias(hidden);descriptor=self.e.allocate('FC2_alias_base_stride_progress',32)
        self.dense_into(hidden,view,p,key+'_fc2');self.commit_shrink(hidden,view);self.e.release(descriptor)
        if observe:observe('fc2',view.debug_numpy())
        return view
    def run(self,x,p,key,observe=None):
        assert x.shape==(99,64) and x.dtype==np.int8
        self.b.stage='FFN_cold_input';residual=self.s.allocate('LN1_residual',99,64,8);residual.write_host(x,self.beat_cycles)
        output=self.ffn(residual,p,key,observe)
        assert np.array_equal(residual.debug_numpy(),x),'retained LN1 corrupted'
        actual=self.external_read(output,'final_FC2_writeback');assert np.array_equal(actual,output.debug_numpy())
        self.s.release(output)
        for bank in range(4):self.b.readonly.pop(f'S{bank}',None)
        self.s.release(residual);self.snapshot('all_released');metrics=self.summary()
        metrics.update(scope='resident FC1/GELU/FC2 with retained LN1 and consumed-prefix shrink; not full encoder/CPU/packet/RTL proof',
            FFN_resident=True,intermediate_external_materialization=self.materialize,
            intermediate_external_logical_bytes=sum(x['logical_bytes'] for x in self.transfers if 'roundtrip' in x['label']),
            transfers=self.transfers,guard_tests=self.rejected,consumed_hidden_halfwords=self.b.consumed_words,
            allocation_log=self.allocation_log,retained_residual_unchanged=True,inplace_shrink_bytes_released=19200,
            SRAM_reads=sum(v for (b,mode),v in self.b.counts.items() if mode=='r'),SRAM_writes=sum(v for (b,mode),v in self.b.counts.items() if mode=='w'),
            phase_cycles={f'{a}/{b}':v for (a,b),v in self.b.stage_cycles.items()},
            max_operand_A_address=self.max_A_address,extra_arithmetic_units=0,alias_descriptor_bytes=32)
        assert metrics['cycles']==sum(metrics['phase_cycles'].values())
        return actual,metrics
