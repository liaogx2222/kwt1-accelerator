"""R1 value-driven layer on real SRAM, reusing only historical address helpers.

No Encoder/quantization-oracle calls in the execution path. PE, wide multiply,
division, isqrt, ALU and RNE event results drive every computed tensor.
"""
import numpy as np
from .bank_model import LayerModel,address
from .event_arithmetic import Engine
from .execution_banks import ExecutionBanks


class ExecutableLayer(LayerModel):
    def __init__(self,p,trace,layer=0,event_trace=None,lifetimes=None,coefficient_cache=False,gelu_ports=1,pingpong=False,corrupt=None,banks=None,preloaded=False):
        super().__init__(p,trace,layer)
        self.b.trace.close();self.b=banks if banks is not None else ExecutionBanks(trace)
        self.ref=None
        self.e=Engine(self.b,event_trace,lifetimes,corrupt=corrupt)
        self.cache_enabled=coefficient_cache;self.gelu_ports=gelu_ports;self.pingpong=pingpong
        self.measured=None;self.coefficient_reads=0
        self.preloaded=preloaded
    def load(self,x):
        if not self.preloaded:return super().load(x)
        offset=0
        for name in ['q','k','v','o','fc1','fc2']:
            key=self.key+'_'+name;k,n=self.p[key+'_w'].shape;self.wbase[key]=offset;offset+=k*(n//8)
        offset=0
        for name in sorted(self.p):
            if not name.startswith(self.key+'_') or name.endswith(('_w','_gelu_lut','_q_b','_k_b','_v_b')):continue
            self.cbase[name]=offset;offset+=self.p[name].nbytes//4
        self.local_load_cycles=0
    def phase(self,name):self.b.stage=name;self.e.phase=name
    def peek(self,group,base,layout,width):
        out=np.empty((99,width),np.int8)
        for t in range(99):
            for ch in range(width):
                bank,addr,byte=address(layout,base,t,ch,width)
                value=(self.b.peek_word(group+str(bank),addr)>>(8*byte))&255
                out[t,ch]=value if value<128 else value-256
        return out
    def fetch(self,name,indices=None):
        a=self.p[name];n=a.size if indices is None else len(indices)
        allocation=self.e.allocate('coefficient_'+name,n*a.dtype.itemsize)
        data=super().coeff(name,indices);self.coefficient_reads+=n*a.dtype.itemsize
        return self.e.source(data,a.dtype.itemsize*8,True,name='coefficient_'+name,allocation=allocation)
    def unpack_scalar(self,c):
        value=int(self.e.consume(c));self.e.drop(c);return value
    def op(self,name,args,bits=64,signed=True,unit='alu',release=(),advance=True,shape=()):
        return self.e.issue(name,args,bits,signed,unit,shape,release,advance)
    def finish_codes(self,products,shifts,bits=8,name='RQ',shape=None):
        cells=[]
        for i,c in enumerate(products):
            s=shifts[i] if isinstance(shifts,list) else shifts
            cells.append(self.op('rne_sat'+str(bits),[c,s],bits,True,'rne',release=[c]))
        return self.e.pack(cells,shape or (len(cells),),bits,True,name)
    def requant(self,acc,m,s,bias=None,column_offset=0):
        e=self.e;nrow,ncol=acc.shape
        added=[]
        for row in range(nrow):
            for col in range(ncol):
                bb=0 if bias is None else bias.view(column_offset+col)
                added.append(self.op('add',[acc.view((row,col)),bb],32))
        e.drop(acc)
        products=[]
        for i,a in enumerate(added):products.append(self.op('mul',[a,m.view(column_offset+i%ncol)],64,True,'mul',release=[a]))
        shifts=[s.view(column_offset+i%ncol) for i in range(len(products))]
        return self.finish_codes(products,shifts,shape=(nrow,ncol))
    def initial_accumulator(self,bias,offset):
        return self.e.source(np.zeros((8,8),np.int64),32,name='PE_accumulator')
    def dense(self,name,source,dest,tokens=range(99)):
        self.phase(name);key=self.key+'_'+name;k,n=self.p[key+'_w'].shape;group,base,layout=source
        target_group,target_base,target_layout=dest;tokens=list(tokens)
        cache=None
        if self.cache_enabled:
            cache=(self.fetch(key+'_m'),self.fetch(key+'_s'),None if name in ['q','k','v'] else self.fetch(key+'_b'))
        for start in range(0,len(tokens),8):
            valid=tokens[start:start+8]
            for ot in range(n//8):
                if cache:m,s,bias=cache;off=ot*8
                else:
                    m=self.fetch(key+'_m',range(ot*8,ot*8+8));s=self.fetch(key+'_s',range(ot*8,ot*8+8))
                    bias=None if name in ['q','k','v'] else self.fetch(key+'_b',range(ot*8,ot*8+8));off=0
                acc=self.initial_accumulator(bias,off)
                for red in range(k):
                    assert layout=='token'
                    ops=[(group+str(bank),base+(valid[0]//8)*k+red,'r',0) for bank in range(4)]
                    ops +=[(f'W{bank}',self.wbase[key]+ot*k+red,'r',0) for bank in range(4)]
                    vals=self.b.tick(ops,tag='dense_mac_operand_issue')
                    aa=self.e.source(np.frombuffer(np.array(vals[:4],np.uint16).tobytes(),np.int8).astype(np.int64),8,storage='memory',name='SRAM_A_lanes')
                    bb=self.e.source(np.frombuffer(np.array(vals[4:],np.uint16).tobytes(),np.int8).astype(np.int64),8,storage='memory',name='SRAM_W_lanes')
                    acc=self.op('mac',[aa,bb,acc],32,True,'mac',(aa,bb,acc),False,(8,8))
                # Mask invalid query lanes in the output; they never enter SRAM.
                if len(valid)<8:
                    value=self.e.consume(acc)[:len(valid)].copy();self.e.drop(acc)
                    acc=self.e.source(value,32,name='tail_valid_accumulator')
                out=self.requant(acc,m,s,bias,off)
                arr=self.e.consume(out,'packed_SRAM_write');requests={}
                for row,token in enumerate(valid):
                    for col in range(8):
                        bank,addr,byte=address(target_layout,target_base,token,ot*8+col,n)
                        kk=(target_group+str(bank),addr);requests[kk]=requests.get(kk,0)|((int(arr[row,col])&255)<<(8*byte))
                self.write_requests(requests);self.e.drop(out)
                if not cache:
                    for c in [m,s,bias]:
                        if c is not None:self.e.drop(c)
        if cache:
            for c in cache:
                if c is not None:self.e.drop(c)
    def score_row(self,values,m,s,score_allocation=None):
        e=self.e;score=e.source(np.array(values,np.int64),32,name='softmax_scores',allocation=score_allocation)
        maximum=e.source(int(values[0]),32,name='softmax_max')
        for j in range(1,99):maximum=self.op('max',[maximum,score.view(j)],32,release=[maximum])
        diffs=[self.op('sub',[score.view(j),maximum],32) for j in range(99)]
        e.drop(maximum);e.drop(score)
        prod=[self.op('mul',[d,m.view(0)],64,True,'mul',release=[d]) for d in diffs]
        index_allocation=e.allocate('softmax_index_buffer',99*2);indexes=[]
        for c in prod:
            rounded=self.op('rne',[c,s.view(0)],32,True,'rne',release=[c])
            # Clamp/index routing is explicit, dependent on completed RNE.
            value=max(0,min(4096,-int(e.consume(rounded,'exp_index'))));e.drop(rounded)
            indexes.append(value)
        exp_alloc=e.allocate('softmax_exponents',99*4);exps=[]
        for index in indexes:
            if index==4096:self.b.tick(tag='exp_hardwired_zero');value=0
            else:
                lo,hi=self.b.tick([('E0',index,'r',0),('E1',index,'r',0)],tag='exp_read')
                value=lo|(hi<<16)
            exps.append(value)
        ex=e.source(np.array(exps,np.int64),32,False,name='softmax_exponents',allocation=exp_alloc)
        e.release(index_allocation)
        den=e.source(0,32,False,name='softmax_denominator')
        for j in range(99):den=self.op('add',[den,ex.view(j)],32,False,release=[den])
        qr=self.op('divmod',[1<<47,den],64,False,'div',shape=(2,))
        recip=self.op('ceil_qr',[qr.view(0),qr.view(1)],32,False,release=[qr])
        probabilities=[]
        for j in range(99):
            er=self.op('mul',[ex.view(j),recip],64,False,'mul')
            shifted=self.op('shl',[er,16],64,False)
            product=self.op('sub',[shifted,er],64,False,release=[shifted,er])
            q=self.op('shr',[product,47],32,False,release=[product])
            # Correction/remainder uses N=65535*e, not the N*R product.
            eshift=self.op('shl',[ex.view(j),16],64,False)
            numerator=self.op('sub',[eshift,ex.view(j)],64,False,release=[eshift])
            qd=self.op('mul',[q,den],64,False,'mul')
            pair=self.op('correct_qr',[numerator,q,qd,den],64,False,release=[numerator,q,qd],shape=(2,))
            result=self.op('round_qr',[pair.view(0),pair.view(1),den],16,False,release=[pair])
            probabilities.append(result)
        for c in [den,recip,ex]:e.drop(c)
        return e.pack(probabilities,(99,),16,False,'probability_row')
    def attention(self,expected):
        e=self.e
        for start in range(0,99,8):
            count=min(8,99-start);self.phase('qk')
            for kt in range(13):
                acc=e.source(np.zeros((8,8),np.int64),32,name='QK_PE_accumulator')
                for red in range(64):
                    ops=[(f'A{bank}',832+(start//8)*64+red,'r',0) for bank in range(4)]
                    ops +=[(f'B{bank}',kt*64+red,'r',0) for bank in range(4)]
                    vals=self.b.tick(ops,tag='qk_mac_operand_issue')
                    aa=e.source(np.frombuffer(np.array(vals[:4],np.uint16).tobytes(),np.int8).astype(np.int64),8,storage='memory',name='Q_lanes')
                    bb=e.source(np.frombuffer(np.array(vals[4:],np.uint16).tobytes(),np.int8).astype(np.int64),8,storage='memory',name='K_lanes')
                    acc=self.op('mac',[aa,bb,acc],32,True,'mac',(aa,bb,acc),False,(8,8))
                tile=e.consume(acc,'score_SRAM_write')
                for r in range(count):
                    for col in range(min(8,99-kt*8)):
                        value=int(tile[r,col]);addr=2048+r*99+kt*8+col
                        self.b.tick([('C0',addr,'w',value&65535),('C1',addr,'w',(value>>16)&65535)],tag='score_write32')
                e.drop(acc)
            self.phase('softmax');sm=self.fetch(self.key+'_score_m');ss=self.fetch(self.key+'_score_s');previous=None
            for r in range(count):
                score_allocation=e.allocate('softmax_scores',99*4);values=[]
                for j in range(99):
                    lo,hi=self.b.tick([('C0',2048+r*99+j,'r',0),('C1',2048+r*99+j,'r',0)],tag='score_read')
                    value=lo|(hi<<16);values.append(value if value<(1<<31) else value-(1<<32))
                row=self.score_row(values,sm,ss,score_allocation)
                assert np.array_equal(e.consume(row,'oracle_compare_only'),expected['attention_softmax'][start+r]),'scheduled Softmax differs'
                if r%2==0 and r!=count-1:previous=row
                else:
                    av=e.consume(previous if previous is not None else row,'P_pack')
                    bv=e.consume(row,'P_pack') if previous is not None else np.zeros(99,np.int64)
                    bank=r//2
                    for j in range(99):
                        a,b=int(av[j]),int(bv[j]);self.b.tick([(f'A{bank}',1664+j,'w',(a&255)|((b&255)<<8))],tag='P_low_write')
                        self.b.tick([(f'A{bank}',1763+j,'w',(a>>8)|((b>>8)<<8))],tag='P_high_write')
                    if previous is not None:e.drop(previous)
                    e.drop(row);previous=None
            e.drop(sm);e.drop(ss)
            for bank in range((count+1)//2,4):
                for j in range(198):self.b.tick([(f'A{bank}',1664+j,'w',0)],tag='tail_P_clear')
            self.phase('pv');cm=self.fetch(self.key+'_ctx_m');cs=self.fetch(self.key+'_ctx_s')
            for ot in range(8):
                passes=[]
                for plane in range(2):
                    acc=e.source(np.zeros((8,8),np.int64),32,name='PV_accumulator_pass'+str(plane))
                    for j in range(99):
                        ops=[(f'A{bank}',1664+plane*99+j,'r',0) for bank in range(4)]
                        ops +=[(f'B{bank}',832+j*8+ot,'r',0) for bank in range(4)]
                        vals=self.b.tick(ops,tag='pv_mac_operand_issue')
                        aa=e.source(np.frombuffer(np.array(vals[:4],np.uint16).tobytes(),np.uint8).astype(np.int64),8,False,'memory',name='P_U8_lanes')
                        bb=e.source(np.frombuffer(np.array(vals[4:],np.uint16).tobytes(),np.int8).astype(np.int64),8,True,'memory',name='V_S8_lanes')
                        acc=self.op('mac',[aa,bb,acc],32,True,'mac',(aa,bb,acc),False,(8,8))
                    e.read(acc);passes.append(acc)
                combined=[]
                for r in range(count):
                    for c in range(8):
                        hi=self.op('shl',[passes[1].view((r,c)),8],32)
                        combined.append(self.op('add',[passes[0].view((r,c)),hi],32,release=[hi]))
                for c in passes:e.drop(c)
                out=self.context_codes(combined,cm,cs,count);arr=e.consume(out,'context_write');requests={}
                for r in range(count):
                    for c in range(8):
                        bank,addr,byte=address('token',2496,start+r,ot*8+c,64);key=(f'A{bank}',addr)
                        requests[key]=requests.get(key,0)|((int(arr[r,c])&255)<<(8*byte))
                self.write_requests(requests);e.drop(out)
            e.drop(cm);e.drop(cs)
            assert np.array_equal(self.peek('A',2496,'token',64)[start:start+count],expected['attention_context'][start:start+count]),'scheduled PV differs'
            self.dense('o',('A',2496,'token'),('A',1664,'token'),range(start,start+count))
            assert np.array_equal(self.peek('A',1664,'token',64)[start:start+count],expected['attention_output_projection'][start:start+count]),'scheduled O differs'
            self.norm(1,start,count,0)
            assert np.array_equal(self.peek('A',0,'token',64)[start:start+count],expected['layernorm1_output'][start:start+count]),'scheduled LN1 differs'
    def context_codes(self,combined,cm,cs,count):
        products=[self.op('mul',[c,cm.view(0)],64,True,'mul',release=[c]) for c in combined]
        return self.finish_codes(products,cs.view(0),shape=(count,8))
    def norm(self,j,start,count,destbase):
        self.phase('residual_ln'+str(j));e=self.e;rk=self.key+f'_r{j}';lk=self.key+f'_ln{j}'
        a_alloc=e.allocate('residual_branch_A',count*64);b_alloc=e.allocate('residual_branch_B',count*64)
        aa=np.empty((count,64),np.int64);bb=np.empty_like(aa)
        for ch in range(64):
            aa[:,ch]=self.rd('A',0,'token',range(start,start+count),ch,64)
            bb[:,ch]=self.rd('A',1664,'token',range(start,start+count),ch,64)
        a=e.source(aa,8,name='residual_A',allocation=a_alloc);b=e.source(bb,8,name='residual_B',allocation=b_alloc)
        coeff=self.fetch(rk+'_coeff')
        for row in range(count):
            ap=[self.op('mul',[a.view((row,ch)),coeff.view(0)],64,True,'mul') for ch in range(64)]
            bp=[self.op('mul',[b.view((row,ch)),coeff.view(1)],64,True,'mul') for ch in range(64)]
            sums=[self.op('add',[x,y],64,release=[x,y]) for x,y in zip(ap,bp)]
            r=self.finish_codes(sums,coeff.view(2),16,'residual_row',(64,));values=e.consume(r,'residual_write')
            for ch,value in enumerate(values):self.b.tick([('C0',2880+row*64+ch,'w',int(value)&65535)],tag='residual16_write')
            e.drop(r)
        for c in [a,b,coeff]:e.drop(c)
        self.ln_rows(j,start,count,destbase)
    def ln_rows(self,j,start,count,destbase):
        e=self.e;lk=self.key+f'_ln{j}'
        gamma=self.fetch(lk+'_g');beta=self.fetch(lk+'_b');eps=self.fetch(lk+'_eps');m=self.fetch(lk+'_m');s=self.fetch(lk+'_s')
        output_alloc=e.allocate('LN_output_pack',count*64);out=np.empty((count,64),np.int8)
        for row in range(count):
            alloc=e.allocate('LN_S16_row',128);values=[]
            for ch in range(64):
                value=self.b.tick([('C0',2880+row*64+ch,'r',0)],tag='LN_read')[0];values.append(value if value<32768 else value-65536)
            rr=e.source(np.array(values,np.int64),16,name='LN_S16_row',allocation=alloc)
            su=e.source(0,32,name='LN_S');total=e.source(0,64,False,name='LN_T')
            for ch in range(64):su=self.op('add',[su,rr.view(ch)],32,release=[su])
            squares=[self.op('mul',[rr.view(ch),rr.view(ch)],64,True,'mul') for ch in range(64)]
            for square in squares:total=self.op('add',[total,square],64,False,release=[total,square])
            sq=self.op('mul',[su,su],64,True,'mul');t64=self.op('shl',[total,6],64,False,release=[total])
            variance=self.op('sub',[t64,sq],64,False,release=[t64,sq]);v16=self.op('shl',[variance,16],64,False,release=[variance])
            h=self.op('add',[v16,eps.view(())],64,False,release=[v16]);den=self.op('sqrt',[h],32,False,'sqrt',release=[h])
            pair=self.op('divmod',[1<<40,den],64,False,'div',shape=(2,))
            inv=self.op('round_qr',[pair.view(0),pair.view(1),den],32,False,release=[pair,den])
            centered=[]
            for ch in range(64):
                shifted=self.op('shl',[rr.view(ch),6],32)
                centered.append(self.op('sub',[shifted,su],32,release=[shifted]))
            e.drop(su);e.drop(rr)
            products=[self.op('mul',[c,inv],64,True,'mul',release=[c]) for c in centered];e.drop(inv)
            normal=[self.op('rne',[c,18],32,True,'rne',release=[c]) for c in products]
            affine_prod=[self.op('mul',[c,gamma.view(ch)],64,True,'mul',release=[c]) for ch,c in enumerate(normal)]
            affine_round=[self.op('rne',[c,14],32,True,'rne',release=[c]) for c in affine_prod]
            affine=[self.op('add',[c,beta.view(ch)],32,release=[c]) for ch,c in enumerate(affine_round)]
            final=[self.op('mul',[c,m.view(())],64,True,'mul',release=[c]) for c in affine]
            code=self.finish_codes(final,s.view(()),8,'LN_output_row',(64,));out[row]=e.consume(code,'LN_pack_store');e.drop(code)
        self.write_tensor(out,'A',destbase,'token',start);e.release(output_alloc)
        for c in [gamma,beta,eps,m,s]:e.drop(c)
    def gelu(self):
        # Explicitly model a second C1 copy or a 256B register LUT variant.
        self.phase('gelu');e=self.e;table=None
        if self.gelu_ports==8:
            allocation=e.allocate('GELU_register_LUT',256);values=[]
            for i in range(128):
                word=self.b.tick([('C0',1880+i,'r',0)],tag='GELU_register_fill')[0]
                for byte in [word&255,word>>8]:values.append(byte if byte<128 else byte-256)
            table=e.source(np.array(values,np.int64),8,name='GELU_register_LUT',allocation=allocation)
        elif self.gelu_ports==2:
            for i in range(128):
                word=self.b.tick([('C0',1880+i,'r',0)],tag='GELU_replica_read')[0]
                self.b.tick([('C1',1880+i,'w',word)],tag='GELU_replica_write')
        for block in range(13):
            valid=min(8,99-block*8)
            for ch in range(256):
                ops=[(f'B{bank}',block*256+ch,'r',0) for bank in range((valid+1)//2)]
                words=self.b.tick(ops,tag='hidden_read');codes=np.frombuffer(np.array(words,np.uint16).tobytes(),np.int8)
                alloc=e.allocate('GELU_lanes_and_pack',16);out=np.zeros(8,np.int8)
                if table is not None:
                    for row in range(valid):out[row]=e.consume(table.view(int(codes[row])+128),'GELU_register_lookup')
                    self.b.tick(tag='GELU_8read_register_ports')
                else:
                    for pos in range(0,valid,self.gelu_ports):
                        ops=[('C'+str(row-pos),1880+(int(codes[row])+128)//2,'r',0) for row in range(pos,min(valid,pos+self.gelu_ports))]
                        vals=self.b.tick(ops,tag='GELU_lookup')
                        for row,v in zip(range(pos,min(valid,pos+self.gelu_ports)),vals):
                            byte=(v>>(8*((int(codes[row])+128)%2)))&255;out[row]=byte if byte<128 else byte-256
                packed=np.frombuffer(out.tobytes(),np.uint16)
                self.b.tick([(f'B{bank}',block*256+ch,'w',int(packed[bank])) for bank in range((valid+1)//2)],tag='hidden_write');e.release(alloc)
        if table is not None:e.drop(table)
    def run(self,x,expected):
        self.load(x)
        for kind,dest in [('q',('A',832,'token')),('k',('B',0,'token')),('v',('B',832,'channel'))]:
            self.dense(kind,('A',0,'token'),dest)
            assert np.array_equal(self.peek(*dest,64),expected[kind+'_projection'])
        self.attention(expected)
        assert np.array_equal(self.peek('A',0,'token',64),expected['layernorm1_output'])
        self.dense('fc1',('A',0,'token'),('B',0,'token'))
        assert np.array_equal(self.peek('B',0,'token',256),expected['ffn_dense1_output'])
        self.gelu();assert np.array_equal(self.peek('B',0,'token',256),expected['gelu_output'])
        self.dense('fc2',('B',0,'token'),('A',1664,'token'))
        assert np.array_equal(self.peek('A',1664,'token',64),expected['ffn_dense2_output'])
        for start in range(0,99,8):self.norm(2,start,min(8,99-start),832)
        out=self.peek('A',832,'token',64);assert np.array_equal(out,expected['layernorm2_output'])
        begin=self.b.cycle;self.phase('handoff')
        if self.layer<11 and not self.pingpong:
            for word in range(832):
                values=self.b.tick([(f'A{bank}',832+word,'r',0) for bank in range(4)],tag='handoff_read')
                self.b.tick([(f'A{bank}',word,'w',v) for bank,v in enumerate(values)],tag='handoff_write')
            assert np.array_equal(self.peek('A',0,'token',64),out)
        elif self.layer<11:self.b.idle(1,'address_switch_control')
        self.handoff_cycles=self.b.cycle-begin
        if not self.preloaded:self.b.trace.close()
        self.measured=self.e.close();return out
