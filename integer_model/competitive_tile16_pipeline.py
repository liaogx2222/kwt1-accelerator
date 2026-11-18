"""Bounded two-accumulator MAC/RQ overlap on the qualified SP bank model."""
import numpy as np
from .competitive_tile16 import Tile16Dense,MacroClock,VectorEngine


class ElasticClock(MacroClock):
    def tick(self,ops=(),tag='memory'):
        extra=self.sidecar(ops) if getattr(self,'sidecar',None) else []
        return super().tick([*ops,*extra],tag)
    def idle(self,n,tag='idle'):
        assert n>=0
        for _ in range(n):self.tick((),tag)


class ShiftedVectorEngine(VectorEngine):
    def compute(self,op,args):
        if op=='mac_shift8':
            return args[2]+((np.asarray(args[0],np.int64)[:,None]*np.asarray(args[1],np.int64)[None,:])<<8)
        return super().compute(op,args)


class PipelinedTile16(Tile16Dense):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.jobs=[];self.products=[];self.outputs=[];self.overlap_cycles=0;self.output_stalls=0;self.credit_stalls=0
        self.max_jobs=0;self.max_products=0;self.max_outputs=0
        self.b.__class__=ElasticClock;self.b.sidecar=self.background
        self.e.__class__=ShiftedVectorEngine
    def background(self,main):
        e=self.e;write=[];busy={op[0] for op in main}
        if self.outputs and self.outputs[0][0].ready<=e.now:
            cell,c,rows,dest,start,col=self.outputs[0]
            locations=[dest.word(start+rows[j],col+c) for j in range(0,len(rows),2)]
            if not any(bank in busy for bank,address in locations):
                self.outputs.pop(0);values=e.consume(cell,'elastic_RQ_SRAM_write');e.drop(cell)
                for j,(bank,address) in enumerate(locations):
                    at=2*j;value=int(values[at])&255
                    if at+1<len(rows):value|=(int(values[at+1])&255)<<8
                    write.append((bank,address,'w',value))
                if len(main)==16 and all(op[2]=='r' for op in main):self.overlap_cycles+=1
            else:self.output_stalls+=1
        if self.products and self.products[0][0].ready<=e.now and len(self.outputs)<2:
            product,shift,c,rows,dest,start,col=self.products.pop(0)
            result=e.issue('vrne8',[product,shift],8,True,'vrne',(len(rows),),[product,shift],False)
            self.outputs.append((result,c,rows,dest,start,col))
        if self.jobs and len(self.products)<3:
            job=self.jobs[0]
            if job['acc'].ready<=e.now:
                c,rows=job['batches'][job['index']];job['index']+=1
                actual=np.asarray(e.consume(job['acc'],'elastic_accumulator_read'),np.int64)
                multiplier=int(e.consume(job['m'],'elastic_multiplier')[c]);shift=int(e.consume(job['s'],'elastic_shift')[c])
                a=e.source(actual[rows,c].copy(),32,name='elastic_accumulator_vector')
                m=e.source(np.full(len(rows),multiplier,np.int64),32,name='elastic_multiplier_vector')
                s=e.source(np.full(len(rows),shift,np.int64),32,name='elastic_shift_tag')
                product=e.issue('vmul',[a,m],64,True,'vmul',(len(rows),),[a,m],False)
                self.products.append((product,s,c,rows,job['dest'],job['start'],job['col']))
                if job['index']==len(job['batches']):
                    for cell in [job['acc'],job['m'],job['s']]:e.drop(cell)
                    self.jobs.pop(0)
        self.max_jobs=max(self.max_jobs,len(self.jobs));self.max_products=max(self.max_products,len(self.products));self.max_outputs=max(self.max_outputs,len(self.outputs))
        return write
    def mac(self,tensor,start,count,tile,coeff,local):
        # Two matrix registers are the entire accumulator capacity. When both
        # are awaiting RQ reads, MAC waits instead of allocating a third matrix.
        while len(self.jobs)>=2:self.credit_stalls+=1;self.e.step(1,'accumulator_credit_stall')
        k=tensor.cols;bias=np.asarray(self.e.consume(coeff[2],'PE_bias_once'),np.int64)
        acc=self.e.source(np.broadcast_to(bias,(16,16)).copy(),32,name='double_buffered_PE_accumulator')
        self.b.stage='MAC'
        for plane in range(tensor.bits//8):
            for red in range(k):
                addr=plane*k+(0 if local else start//16*k)+red
                ops=[(f'A{bank}',addr,'r',0) for bank in range(8)]+[(f'B{bank}',tile*k+red,'r',0) for bank in range(8)]
                values=self.b.tick(ops,'overlapped_MAC_operand_issue')
                aa=np.array([(values[j//2]>>(8*(j%2)))&255 for j in range(16)],np.int64)
                bb=np.array([(values[8+j//2]>>(8*(j%2)))&255 for j in range(16)],np.int64)
                unsigned=tensor.bits==16 and plane==0
                if not unsigned:aa=np.where(aa>=128,aa-256,aa)
                bb=np.where(bb>=128,bb-256,bb)
                a=self.e.source(aa,8,signed=not unsigned,name='PE_A_latch');b=self.e.source(bb,8,name='PE_B_latch')
                acc=self.e.issue('mac_shift8' if plane else 'mac',[a,b,acc],32,True,'mac',(16,16),[a,b,acc],False)
        return acc
    def rq_write(self,acc,coeff,dest,start,count,col):
        # Snapshot only 16 multipliers/shifts, not an uncounted matrix copy.
        m=self.e.source(np.asarray(self.e.consume(coeff[0]),np.int64).copy(),32,name='elastic_job_multiplier')
        s=self.e.source(np.asarray(self.e.consume(coeff[1]),np.int64).copy(),32,name='elastic_job_shift')
        batches=[(c,list(range(r,min(r+self.lanes,count)))) for c in range(16) for r in range(0,count,self.lanes)]
        self.jobs.append(dict(acc=acc,m=m,s=s,batches=batches,index=0,dest=dest,start=start,col=col))
    def run(self,x,w,bias,multiplier,shift):
        x=np.asarray(x);assert x.dtype in [np.int8,np.int16] and x.shape[0]==99
        n,k=x.shape;assert w.shape[0]==k and w.shape[1]%16==0
        self.b.stage='cold_input';source=self.s.allocate('input',n,k,x.dtype.itemsize*8);source.write_host(x,self.beat_cycles)
        dest=self.s.allocate('output',n,w.shape[1],8);self.load_weights(w)
        local=x.dtype==np.int16 or ((n+15)//16)*k>self.LUT_BASE
        if not local:
            for start in range(0,n,16):self.load_A(source,start,min(16,n-start),False)
        if local:
            for start in range(0,n,16):
                count=min(16,n-start);self.load_A(source,start,count,True)
                for tile in range(w.shape[1]//16):
                    coeff=self.fetch_coeff(multiplier,shift,bias,tile*16)
                    acc=self.mac(source,start,count,tile,coeff,True);self.rq_write(acc,coeff,dest,start,count,tile*16)
                    for cell in coeff:self.e.drop(cell)
        else:
            for tile in range(w.shape[1]//16):
                coeff=self.fetch_coeff(multiplier,shift,bias,tile*16)
                for start in range(0,n,16):
                    count=min(16,n-start);acc=self.mac(source,start,count,tile,coeff,False)
                    self.rq_write(acc,coeff,dest,start,count,tile*16)
                for cell in coeff:self.e.drop(cell)
        self.b.stage='elastic_drain'
        while self.jobs or self.products or self.outputs:self.e.step(1,'elastic_RQ_drain')
        result=dest.debug_numpy();self.s.release(source);self.s.release(dest);live=self.e.close()
        peak=live['peak_bytes']+554
        return result,dict(cycles=self.b.cycle,common_load_cycles=self.common_cycles,kernel_cycles_excluding_common=self.b.cycle-self.common_cycles,
            phase_cycles={f'{a}/{b}':v for (a,b),v in self.b.stage_cycles.items()},
            SRAM_reads=sum(v for (bank,mode),v in self.b.counts.items() if mode=='r'),
            SRAM_writes=sum(v for (bank,mode),v in self.b.counts.items() if mode=='w'),
            scratch_peak_bytes=self.s.peak,scratch_bank_peak_bytes=self.s.bank_peak,private_SRAM_bytes=65536,macro_count=20,
            compressed_exp_bytes=len(self.common),compressed_exp_exact_entries=4097,LUT_reserved_A_word_base=self.LUT_BASE,
            max_operand_A_address=self.max_A_address,vector_lanes=self.lanes,
            register_data_and_pipeline_peak=live['peak_bytes'],declared_static_controller_and_LUT_metadata_bytes=554,
            total_register_peak_bytes=peak,register_4KiB_pass=peak<=4096,coefficient_32bit_words=self.coefficient_words,
            operations=live['operations'],MAC_RQ_overlap_implemented=True,MAC_RQ_overlap_cycles=self.overlap_cycles,
            RQ_output_bank_stall_cycles=self.output_stalls,accumulator_credit_stall_cycles=self.credit_stalls,
            bounded_accumulator_jobs=2,max_queued_jobs=self.max_jobs,max_product_queue=self.max_products,max_output_queue=self.max_outputs,
            first_S16_high_product_shift_wiring=True,all_targets_met=False,new_RTL_implemented=False,
            scope='standalone bounded MAC/RQ overlap model; no full task/Softmax/LN/transport or physical timing claim')
