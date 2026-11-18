"""Whole twelve-layer value-driven core on ONE guarded 20-macro memory.

Explicit SRAM compaction, no external intermediate activations. Parameters
still use the ideal word source, not the thirteen-package CPU/CRC protocol.
"""
import numpy as np
from .competitive_resident_ffn import ResidentFFN
from .competitive_softmax_pipeline import SoftmaxPipelinedAttention
from .competitive_norm_pipeline import PipelinedNorm


class ResidentCore(ResidentFFN,SoftmaxPipelinedAttention,PipelinedNorm):
    def __init__(self,exp_table,lanes=4,beat_cycles=1):
        self.config=(np.asarray(exp_table).copy(),lanes,beat_cycles)
        super().__init__(exp_table,lanes,beat_cycles)
        self.used=False;self.layer=0;self.compactions=[];self.phases=[]
    def reset(self):
        # Explicit MODEL cold reset. SRAM poison is never consumed; initialized
        # flags/queues are discarded and common-cache writes are charged again.
        config=self.config;self.__init__(*config)
    def clean_operands(self):
        assert not (self.jobs or self.products or self.outputs)
        for bank in range(8):
            self.b.readonly.pop(f'B{bank}',None)
            self.b.readonly[f'A{bank}']=[(self.LUT_BASE,1024)]
            self.b.initialized.difference_update((f'B{bank}',a) for a in range(1024))
            self.b.initialized.difference_update((f'A{bank}',a) for a in range(self.LUT_BASE))
    def dense_into(self,source,dest,p,key):
        self.clean_operands();self.load_weights(p[key+'_w'])
        length=source.cols*(dest.cols//16);self.b.lock([f'B{b}' for b in range(8)],0,length)
        local=source.bits==16 or ((source.rows+15)//16)*source.cols>self.LUT_BASE
        if local:
            for start in range(0,99,16):
                count=min(16,99-start);self.load_A(source,start,count,True)
                for tile in range(dest.cols//16):
                    coeff=self.fetch_coeff(p[key+'_m'],p[key+'_s'],p[key+'_b'],tile*16)
                    acc=self.mac(source,start,count,tile,coeff,True);self.rq_write(acc,coeff,dest,start,count,tile*16)
                    for c in coeff:self.e.drop(c)
        else:
            for start in range(0,99,16):self.load_A(source,start,min(16,99-start),False)
            self.b.lock([f'A{b}' for b in range(8)],0,448)
            for tile in range(dest.cols//16):
                coeff=self.fetch_coeff(p[key+'_m'],p[key+'_s'],p[key+'_b'],tile*16)
                for start in range(0,99,16):
                    count=min(16,99-start);acc=self.mac(source,start,count,tile,coeff,False);self.rq_write(acc,coeff,dest,start,count,tile*16)
                for c in coeff:self.e.drop(c)
        while self.jobs or self.products or self.outputs:self.e.step(1,'core_RQ_drain')
        for bank in range(8):
            self.b.readonly.pop(f'B{bank}',None)
            self.b.readonly[f'A{bank}']=[(self.LUT_BASE,1024)]
    def norm_into(self,a,b,p,key,j):
        dest=self.s.allocate(f'LN{j}',99,64,8);prefix=key+f'_ln{j}'
        rc=self.parameter(p[key+f'_r{j}_coeff'],'residual_coeff')
        g=self.parameter(p[prefix+'_g'],'gamma');beta=self.parameter(p[prefix+'_b'],'beta')
        eps=self.parameter(p[prefix+'_eps'],'epsilon',64);m=self.parameter(p[prefix+'_m'],'LN_m');s=self.parameter(p[prefix+'_s'],'LN_s')
        self.b.stage=f'resident_LN{j}'
        for row in range(0,99,2):
            pa=self.read_pair(a,row);pb=self.read_pair(b,row);outputs=[]
            for r in range(min(2,99-row)):
                av=self.e.source(self.e.consume(pa)[r].copy(),a.bits,name='resident_LN_A_row')
                bv=self.e.source(self.e.consume(pb)[r].copy(),b.bits,name='resident_LN_B_row')
                outputs.append(self.norm_row(av,bv,rc,g,beta,eps,m,s));self.e.drop(av);self.e.drop(bv)
            self.write_pair(dest,row,outputs);self.e.drop(pa);self.e.drop(pb)
        for c in [rc,g,beta,eps,m,s]:self.e.drop(c)
        return dest
    def release_tensor(self,t):
        for bank,(base,size) in enumerate(zip(t.bases,t.sizes)):
            key=f'S{bank}';self.b.readonly[key]=[x for x in self.b.readonly.get(key,[]) if x!=(base,base+size)]
        self.s.release(t)
    def compact(self,t):
        if t.bases==[0]*4:return t
        before=self.b.cycle;dest=self.s.allocate('compacted_LN1',99,64,8)
        assert dest.bases==[0]*4,'Explicit compactor requires a free prefix'
        self.b.stage='SRAM_compaction'
        # Four synchronous halfword reads, followed by four writes: each
        # bank remains single-ported. Latch lifetime covers the copy cycle.
        for offset in range(800):
            words=self.b.tick([(f'S{b}',t.bases[b]+offset,'r',0) for b in range(4)],'compaction_read')
            latch=self.e.source(np.array(words,np.int64),16,False,name='compaction_word_latch')
            self.b.tick([(f'S{b}',dest.bases[b]+offset,'w',words[b]) for b in range(4)],'compaction_write');self.e.drop(latch)
        old=t.bases.copy();self.release_tensor(t)
        self.compactions.append(dict(layer=self.layer,cycles=self.b.cycle-before,halfwords=3200,source_bases=old,dest_bases=dest.bases.copy()))
        self.snapshot('after_compaction');return dest
    def output_alias(self,hidden):
        assert not self.b.unconsumed;self.b.consumed_words=0
        return super().output_alias(hidden)
    def snapshot(self,label):super().snapshot(f'layer{self.layer:02d}/{label}')
    def mark(self,operation,start):self.phases.append(dict(layer=self.layer,operation=operation,start=start,end=self.b.cycle,cycles=self.b.cycle-start))
    def run(self,x,p,observe=None):
        if self.used:raise RuntimeError('call explicit model reset before next cold task')
        self.used=True;assert x.shape==(99,64) and x.dtype==np.int16
        descriptor=self.e.allocate('core_live_tensor_descriptors',64)
        self.b.stage='task_input';current=self.s.allocate('input_S16',99,64,16);current.write_host(x,self.beat_cycles)
        for layer in range(12):
            self.layer=layer;key=f'l{layer:02d}';projections=[]
            for kind in ['q','k','v']:
                before=self.b.cycle;dest=self.s.allocate(kind,99,64,8);self.dense_into(current,dest,p,key+'_'+kind);projections.append(dest)
                if observe:observe(layer,kind,dest.debug_numpy())
                self.mark(kind,before)
            before=self.b.cycle;self.clean_operands()
            def tap(name,offset,values):
                if observe:observe(layer,name,values,offset)
            context=self.attention(*projections,p,key,tap);self.mark('attention',before)
            before=self.b.cycle;projected=self.s.allocate('O',99,64,8);self.dense_into(context,projected,p,key+'_o')
            if observe:observe(layer,'o',projected.debug_numpy())
            self.release_tensor(context);self.mark('o',before)
            before=self.b.cycle;norm=self.norm_into(current,projected,p,key,1)
            if observe:observe(layer,'ln1',norm.debug_numpy())
            self.release_tensor(current);self.release_tensor(projected);self.mark('ln1',before)
            before=self.b.cycle;norm=self.compact(norm);self.mark('compact',before)
            before=self.b.cycle
            def ffn_tap(name,values):
                if observe:observe(layer,name,values)
            output=self.ffn(norm,p,key,ffn_tap);self.mark('ffn',before)
            before=self.b.cycle;next_tensor=self.norm_into(norm,output,p,key,2)
            if observe:observe(layer,'ln2',next_tensor.debug_numpy())
            self.release_tensor(norm);self.release_tensor(output);current=next_tensor;self.mark('ln2',before)
        actual=self.external_read(current,'final_task_writeback');assert np.array_equal(actual,current.debug_numpy())
        self.release_tensor(current);self.snapshot('all_released');self.e.release(descriptor)
        metrics=self.summary()
        metrics.update(scope='whole 12-layer value-driven resident CORE model, ideal parameter word source; not CPU/packet/RTL signoff',
            core_12layer_resident=True,full_SoC_executed=False,complete_IO_model=False,packet_protocol=False,new_RTL=False,
            common_load_count=1,intermediate_external_activation_bytes=0,compactions=self.compactions,phases=self.phases,
            allocation_log=self.allocation_log,transfers=self.transfers,model_cold_reset=True,RTL_reset_validated=False,
            SRAM_reads=sum(v for (b,m),v in self.b.counts.items() if m=='r'),SRAM_writes=sum(v for (b,m),v in self.b.counts.items() if m=='w'),
            phase_cycles={f'{a}/{b}':v for (a,b),v in self.b.stage_cycles.items()},guard_tests=self.guard_tests+self.rejected,
            core_frame_descriptor_bytes=64,controller_RTL_proved=False)
        assert sum(metrics['phase_cycles'].values())==metrics['cycles']
        return actual,metrics
