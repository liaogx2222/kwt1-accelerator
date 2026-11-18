"""Executable 16x16 Dense/RQ candidate on 16 small + 4 large SP banks.

Kernel qualification only: no full-task/SoC throughput or PPA claim. Actual
bank reads feed MAC retirements, then actual mul/RNE results feed bank writes.
Original v1 Engine/runtime/RTL are never modified.
"""
import collections
import math
import numpy as np
from .event_arithmetic import Engine,signed_shift


class MacroClock:
    def __init__(self):
        self.mem={**{f'{g}{i}':np.full(1024,0xa5a5,np.uint16) for g in ['A','B'] for i in range(8)},
                  **{f'S{i}':np.full(4096,0xa5a5,np.uint16) for i in range(4)}}
        self.cycle=0;self.stage='init';self.counts=collections.Counter();self.stage_cycles=collections.Counter()
        self.max_ports=0;self.engine=None
    def tick(self,ops=(),tag='memory'):
        used=set()
        for bank,address,mode,value in ops:
            if bank in used:raise ValueError('single-port conflict '+bank)
            used.add(bank)
            if bank not in self.mem or not 0<=address<len(self.mem[bank]):raise ValueError('SRAM bounds')
            if mode not in ['r','w']:raise ValueError(mode)
            if mode=='w' and not 0<=int(value)<=65535:raise OverflowError('SRAM word')
        values=[]
        for bank,address,mode,value in ops:
            if mode=='r':values.append(int(self.mem[bank][address]))
            else:self.mem[bank][address]=value
            self.counts[(bank,mode)]+=1
        self.max_ports=max(self.max_ports,len(ops));self.cycle+=1;self.stage_cycles[(self.stage,tag)]+=1
        if self.engine:self.engine.retire()
        return values
    def idle(self,n,tag='idle'):
        assert n>=0;self.cycle+=n;self.stage_cycles[(self.stage,tag)]+=n
    def batches(self,requests,tag='serialized'):
        pending=list(enumerate(requests));results={}
        while pending:
            batch=[];ids=[];used=set();rest=[]
            for ident,op in pending:
                if op[0] in used:rest.append((ident,op))
                else:used.add(op[0]);ids.append(ident);batch.append(op)
            returned=self.tick(batch,tag);it=iter(returned)
            for ident,op in zip(ids,batch):
                if op[2]=='r':results[ident]=next(it)
            pending=rest
        return [results[i] for i,op in enumerate(requests) if op[2]=='r']


class Scratch:
    def __init__(self,clock):
        self.clock=clock;self.free=[[(0,4096)] for _ in range(4)];self.live=[];self.peak=0;self.bank_peak=[0]*4
    def allocate(self,name,rows,cols,bits=8,signed=True):
        assert bits in [8,16,32];planes=bits//8
        pairs=[sum(1 for r in range(rows) if (r%8)//2==b) for b in range(4)]
        groups=[(n+1)//2 for n in pairs]
        for rotation in range(4):
            bases=[];sizes=[];fits=True
            for logical in range(4):
                physical=(logical+rotation)%4;size=groups[logical]*cols*planes
                found=next(((start,end) for start,end in self.free[physical] if end-start>=size),None)
                if found is None:fits=False;break
                bases.append(found[0]);sizes.append(size)
            if fits:break
        if not fits:raise MemoryError(f'32KiB scratch cannot allocate {name}: rows={rows}, cols={cols}, bits={bits}')
        for logical,(base,size) in enumerate(zip(bases,sizes)):
            bank=(logical+rotation)%4
            if size:
                interval=next((a,b) for a,b in self.free[bank] if a==base and b-a>=size)
                self.free[bank].remove(interval)
                if base+size<interval[1]:self.free[bank].append((base+size,interval[1]))
        t=Tensor(self,name,rows,cols,bits,signed,rotation,bases,groups,sizes);self.live.append(t)
        active=[sum(x.sizes[(b-x.rotation)%4] for x in self.live)*2 for b in range(4)]
        self.peak=max(self.peak,sum(active));self.bank_peak=[max(a,b) for a,b in zip(self.bank_peak,active)]
        return t
    def release(self,t):
        if t not in self.live:raise RuntimeError('scratch double free')
        self.live.remove(t);t.valid=False
        for logical,(base,size) in enumerate(zip(t.bases,t.sizes)):
            if not size:continue
            bank=(logical+t.rotation)%4;intervals=sorted(self.free[bank]+[(base,base+size)]);merged=[]
            for a,b in intervals:
                if merged and merged[-1][1]==a:merged[-1]=(merged[-1][0],b)
                else:merged.append((a,b))
            self.free[bank]=merged


class Tensor:
    def __init__(self,pool,name,rows,cols,bits,signed,rotation,bases,groups,sizes):
        self.pool,self.name,self.rows,self.cols,self.bits,self.signed=pool,name,rows,cols,bits,signed
        self.rotation,self.bases,self.groups,self.sizes=rotation,bases,groups,sizes;self.valid=True
    def word(self,row,col,plane=0):
        if not self.valid:raise RuntimeError('scratch use after free')
        if not 0<=row<self.rows or not 0<=col<self.cols or not 0<=plane<self.bits//8:raise ValueError('tensor bounds')
        logical=(row%8)//2
        return f'S{(logical+self.rotation)%4}',self.bases[logical]+(plane*self.groups[logical]+row//8)*self.cols+col
    def write_host(self,values,beat_cycles=1):
        a=np.asarray(values);assert a.shape==(self.rows,self.cols)
        low=-(1<<(self.bits-1)) if self.signed else 0;high=(1<<(self.bits-int(self.signed)))-1
        if int(a.min())<low or int(a.max())>high:raise OverflowError('tensor input range')
        for plane in range(self.bits//8):
            for group in range(math.ceil(self.rows/8)):
                for col in range(self.cols):
                    ops=[]
                    for logical in range(4):
                        row=group*8+logical*2
                        if row>=self.rows:continue
                        bank,address=self.word(row,col,plane)
                        v=(int(a[row,col])>>(8*plane))&255
                        if row+1<self.rows:v|=((int(a[row+1,col])>>(8*plane))&255)<<8
                        ops.append((bank,address,'w',v))
                    for start in range(0,len(ops),2):
                        self.pool.clock.tick(ops[start:start+2],'host_tensor_32bit_beat')
                        self.pool.clock.idle(beat_cycles-1,'host_beat_interval')
    def debug_numpy(self):
        # Verification-only readback; execution never feeds this into MAC/RQ.
        result=np.empty((self.rows,self.cols),np.int64)
        for row in range(self.rows):
            for col in range(self.cols):
                value=0
                for plane in range(self.bits//8):
                    bank,address=self.word(row,col,plane);word=int(self.pool.clock.mem[bank][address])
                    value|=((word>>(8*(row%2)))&255)<<(8*plane)
                if self.signed and value&(1<<(self.bits-1)):value-=1<<self.bits
                result[row,col]=value
        return result.astype(np.int8 if self.bits==8 else np.int16 if self.bits==16 else np.int32)


def pack_exp_blocks(table):
    values=list(map(int,table));assert len(values)==4097 and values[0]==1<<20 and values[-1]==0
    widths=[];offsets=[];stream=0;position=0
    for block in range(16):
        chunk=values[block*256:(block+1)*256];chunk[0]=0 if block==0 else chunk[0]
        width=max(chunk).bit_length();widths.append(width);offsets.append(position)
        for value in chunk:
            stream|=value<<position;position+=width
    packed=stream.to_bytes((position+7)//8,'little')
    return packed,widths,offsets


class VectorEngine(Engine):
    def __init__(self,clock,lanes=4,inject=False):
        super().__init__(clock);self.lanes=lanes;self.inject=inject;self.injected=False
        self.lat.update(vmul=3,vrne=1);self.II.update(vmul=1,vrne=1)
    def compute(self,op,args):
        if op=='vmul':return np.asarray(args[0],np.int64)*np.asarray(args[1],np.int64)
        if op=='vrne8':
            result=np.array([max(-127,min(127,signed_shift(int(n),int(s)))) for n,s in zip(args[0],args[1])],np.int64)
            if self.inject and not self.injected:
                result[0]+=1 if result[0]<127 else -1;self.injected=True
            return result
        if op=='combine_s16':return (args[0]<<8)+args[1]
        return super().compute(op,args)


class Tile16Dense:
    LUT_BASE=710 # 314 words/bank reserved for exact block-packed exp cache.
    def __init__(self,exp_table,lanes=4,beat_cycles=1,inject=False):
        if lanes not in [2,4,8,16]:raise ValueError('supported vector widths')
        self.b=MacroClock();self.s=Scratch(self.b);self.e=VectorEngine(self.b,lanes,inject);self.b.engine=self.e
        self.beat_cycles=beat_cycles;self.lanes=lanes;self.max_A_address=-1;self.coefficient_words=0
        self.common,self.widths,self.offsets=pack_exp_blocks(exp_table)
        assert len(self.common)==5024
        self.b.stage='common_exp_cache'
        words=np.frombuffer(self.common,dtype='<u2')
        for start in range(0,len(words),2):
            ops=[(f'A{j%8}',self.LUT_BASE+j//8,'w',int(words[j])) for j in range(start,min(start+2,len(words)))]
            self.b.tick(ops,'compressed_exp_32bit_beat');self.b.idle(beat_cycles-1,'source_interval')
        self.common_cycles=self.b.cycle
        assert all(self.lookup_exp_debug(i)==int(exp_table[i]) for i in range(4097))
    def lookup_exp_debug(self,index):
        if index==0:return 1<<20
        if index==4096:return 0
        width=self.widths[index//256]
        if not width:return 0
        bit=self.offsets[index//256]+(index%256)*width;word=bit//16;shift=bit%16
        value=0
        for part in range((shift+width+15)//16):
            j=word+part;value|=int(self.b.mem[f'A{j%8}'][self.LUT_BASE+j//8])<<(16*part)
        return (value>>shift)&((1<<width)-1)
    def load_weights(self,w):
        k,o=w.shape;assert w.dtype==np.int8 and o%16==0 and k*(o//16)<=1024
        self.b.stage='weight_cache_load'
        for tile in range(o//16):
            for red in range(k):
                for pair in range(0,8,2):
                    ops=[]
                    for bank in [pair,pair+1]:
                        col=tile*16+2*bank;value=(int(w[red,col])&255)|((int(w[red,col+1])&255)<<8)
                        ops.append((f'B{bank}',tile*k+red,'w',value))
                    self.b.tick(ops,'weight_32bit_beat');self.b.idle(self.beat_cycles-1,'weight_source_interval')
    def load_A(self,tensor,start,count,local):
        self.b.stage='operand_copy'
        for plane in range(tensor.bits//8):
            for red in range(tensor.cols):
                requests=[];dest=[]
                for pair in range(8):
                    row=start+pair*2
                    if row<start+count:
                        bank,address=tensor.word(row,red,plane);requests.append((bank,address,'r',0));dest.append(pair)
                values=self.b.batches(requests,'scratch_operand_read')
                data=dict(zip(dest,values));ops=[]
                for pair in range(8):
                    address=plane*tensor.cols+(0 if local else start//16*tensor.cols)+red
                    if address>=self.LUT_BASE:raise MemoryError('A operand overwrites compressed LUT')
                    self.max_A_address=max(self.max_A_address,address)
                    ops.append((f'A{pair}',address,'w',data.get(pair,0)))
                self.b.tick(ops,'operand_A_write')
    def fetch_coeff(self,multiplier,shift,bias,offset):
        self.b.stage='coefficient_fetch';result=[]
        for name,a in [('multiplier',multiplier),('shift',shift),('bias',bias)]:
            value=np.asarray(a[offset:offset+16],np.int64)
            for _ in value:self.e.step(self.beat_cycles,'shared_coefficient_32bit_word');self.coefficient_words+=1
            result.append(self.e.source(value,32,name=name))
        return result
    def mac(self,tensor,start,count,tile,coeff,local):
        k=tensor.cols;bias=np.asarray(self.e.consume(coeff[2],'PE_bias_broadcast'),np.int64)
        low=self.e.source(np.broadcast_to(bias,(16,16)).copy(),32,name='PE_accumulator_with_bias')
        high=None
        self.b.stage='MAC'
        for plane in range(tensor.bits//8):
            acc=low if plane==0 else self.e.source(np.zeros((16,16),np.int64),32,name='PE_S16_high_pass')
            for red in range(k):
                addr=plane*k+(0 if local else start//16*k)+red
                ops=[(f'A{bank}',addr,'r',0) for bank in range(8)]+[(f'B{bank}',tile*k+red,'r',0) for bank in range(8)]
                words=self.b.tick(ops,'MAC_operand_issue')
                aa=np.array([(words[j//2]>>(8*(j%2)))&255 for j in range(16)],np.int64)
                bb=np.array([(words[8+j//2]>>(8*(j%2)))&255 for j in range(16)],np.int64)
                unsigned=tensor.bits==16 and plane==0
                if not unsigned:aa=np.where(aa>=128,aa-256,aa)
                bb=np.where(bb>=128,bb-256,bb)
                a=self.e.source(aa,8,signed=not unsigned,name='SRAM_A_operand_latch')
                b=self.e.source(bb,8,name='SRAM_B_operand_latch')
                acc=self.e.issue('mac',[a,b,acc],32,True,'mac',(16,16),[a,b,acc],False)
            if plane==0:low=acc
            else:high=acc
        if high is not None:
            low=self.e.issue('combine_s16',[high,low],32,True,'mac',(16,16),[high,low],False)
        return low
    def rq_write(self,acc,coeff,out,start,count,col):
        self.b.stage='vector_RQ';e=self.e
        values=np.asarray(e.consume(acc,'RQ_input_after_MAC'),np.int64)
        m=np.asarray(e.consume(coeff[0],'RQ_multiplier'),np.int64);s=np.asarray(e.consume(coeff[1],'RQ_shift'),np.int64)
        batches=[(c,list(range(r,min(r+self.lanes,count)))) for c in range(16) for r in range(0,count,self.lanes)]
        pending=[];outputs=[];index=0
        while index<len(batches) or pending or outputs:
            write=[]
            if outputs and outputs[0][0].ready<=e.now:
                cell,c,rows=outputs.pop(0);codes=e.consume(cell,'SRAM_RQ_write');e.drop(cell)
                for j in range(0,len(rows),2):
                    row=start+rows[j];bank,address=out.word(row,col+c)
                    value=int(codes[j])&255
                    if j+1<len(rows):value|=(int(codes[j+1])&255)<<8
                    write.append((bank,address,'w',value))
            if pending and pending[0][0].ready<=e.now:
                product,c,rows=pending.pop(0)
                sh=e.source(np.full(len(rows),int(s[c]),np.int64),32,name='vector_shift_latch')
                code=e.issue('vrne8',[product,sh],8,True,'vrne',(len(rows),),[product,sh],False)
                outputs.append((code,c,rows))
            if index<len(batches):
                c,rows=batches[index];index+=1
                a=e.source(values[rows,c].copy(),32,name='accumulator_vector_read')
                mm=e.source(np.full(len(rows),int(m[c]),np.int64),32,name='multiplier_vector_broadcast')
                product=e.issue('vmul',[a,mm],64,True,'vmul',(len(rows),),[a,mm],False)
                pending.append((product,c,rows))
            if write:self.b.batches(write,'RQ_packed_write')
            else:e.step(1,'vector_pipeline')
        e.drop(acc)
    def run(self,x,w,bias,multiplier,shift):
        x=np.asarray(x);assert x.dtype in [np.int8,np.int16] and x.shape[0]==99
        n,k=x.shape;assert w.shape[0]==k and w.shape[1]%16==0
        self.b.stage='cold_input';source=self.s.allocate('input',n,k,x.dtype.itemsize*8);source.write_host(x,self.beat_cycles)
        dest=self.s.allocate('output',n,w.shape[1],8)
        self.load_weights(w);local=x.dtype==np.int16 or math.ceil(n/16)*k>self.LUT_BASE
        if not local:
            for start in range(0,n,16):self.load_A(source,start,min(16,n-start),False)
        if local:
            for start in range(0,n,16):
                count=min(16,n-start);self.load_A(source,start,count,True)
                for tile in range(w.shape[1]//16):
                    coeff=self.fetch_coeff(multiplier,shift,bias,tile*16)
                    acc=self.mac(source,start,count,tile,coeff,True);self.rq_write(acc,coeff,dest,start,count,tile*16)
                    for c in coeff:self.e.drop(c)
        else:
            for tile in range(w.shape[1]//16):
                coeff=self.fetch_coeff(multiplier,shift,bias,tile*16)
                for start in range(0,n,16):
                    count=min(16,n-start);acc=self.mac(source,start,count,tile,coeff,False)
                    self.rq_write(acc,coeff,dest,start,count,tile*16)
                for c in coeff:self.e.drop(c)
        result=dest.debug_numpy();self.s.release(source);self.s.release(dest)
        live=self.e.close();assert not self.s.live
        peak=live['peak_bytes']+512+42 # declared controller/holding + LUT metadata.
        return result,dict(cycles=self.b.cycle,common_load_cycles=self.common_cycles,
            kernel_cycles_excluding_common=self.b.cycle-self.common_cycles,
            phase_cycles={f'{a}/{b}':v for (a,b),v in self.b.stage_cycles.items()},
            SRAM_reads=sum(v for (b,mode),v in self.b.counts.items() if mode=='r'),
            SRAM_writes=sum(v for (b,mode),v in self.b.counts.items() if mode=='w'),
            scratch_peak_bytes=self.s.peak,scratch_bank_peak_bytes=self.s.bank_peak,
            private_SRAM_bytes=65536,macro_count=20,compressed_exp_bytes=len(self.common),
            compressed_exp_exact_entries=4097,LUT_reserved_A_word_base=self.LUT_BASE,max_operand_A_address=self.max_A_address,
            vector_lanes=self.lanes,register_data_and_pipeline_peak=live['peak_bytes'],
            declared_static_controller_and_LUT_metadata_bytes=554,total_register_peak_bytes=peak,
            register_4KiB_pass=peak<=4096,coefficient_32bit_words=self.coefficient_words,
            operations=live['operations'],MAC_unit='16x16 byte products, signed/unsigned first input passes',
            scope='standalone executable Dense/RQ kernel; serial resource schedule, no task-level overlap or complete IO/CRC/CPU model',
            all_targets_met=False,new_RTL_implemented=False)
