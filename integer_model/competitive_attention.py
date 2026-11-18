"""Value-driven QK and unsigned-U16 PV kernels on the 20 SP banks.

No full-task claim: input Q/K/P/V are independently provided kernel operands.
QK returns tiled score readback; a task must consume each tile before reuse.
"""
import numpy as np
from .competitive_nonlinear import VectorNonlinear


class Attention16(VectorNonlinear):
    def cache_keys(self,t):
        self.b.stage='K_transpose_copy'
        for tile in range(7):
            for red in range(64):
                locations=[];pairs=[]
                for bank in range(8):
                    row=tile*16+bank*2
                    if row<99:locations.append((*t.word(row,red),'r',0));pairs.append(bank)
                words=self.b.batches(locations,'K_SRAM_read');data=dict(zip(pairs,words))
                latch=self.e.source(np.array(words,np.int64),16,False,name='K_copy_word_latch')
                self.b.tick([(f'B{bank}',tile*64+red,'w',data.get(bank,0)) for bank in range(8)],'K_B_cache_write')
                self.e.drop(latch)
    def cache_values(self,t):
        self.b.stage='V_copy'
        for tile in range(4):
            for row in range(0,99,2):
                words=self.b.batches([(*t.word(row,tile*16+c),'r',0) for c in range(16)],'V_SRAM_read')
                latch=self.e.source(np.array(words,np.int64),16,False,name='V_copy_word_latch')
                for parity in range(min(2,99-row)):
                    ops=[]
                    for bank in range(8):
                        lo=(words[bank*2]>>(8*parity))&255;hi=(words[bank*2+1]>>(8*parity))&255
                        ops.append((f'B{bank}',tile*99+row+parity,'w',lo|(hi<<8)))
                    self.b.tick(ops,'V_B_cache_write')
                self.e.drop(latch)
    def raw_mac(self,red_count,a_base,b_base,unsigned=False,planes=1):
        self.b.stage='QK_MAC' if not unsigned else 'PV_MAC'
        acc=self.e.source(np.zeros((16,16),np.int64),32,name='attention_PE_accumulator')
        for plane in range(planes):
            for red in range(red_count):
                ops=[(f'A{b}',a_base+plane*red_count+red,'r',0) for b in range(8)]+[(f'B{b}',b_base+red,'r',0) for b in range(8)]
                words=self.b.tick(ops,'attention_MAC_operand_issue')
                av=np.array([(words[j//2]>>(8*(j%2)))&255 for j in range(16)],np.int64)
                bv=np.array([(words[8+j//2]>>(8*(j%2)))&255 for j in range(16)],np.int64)
                if not unsigned:av=np.where(av>=128,av-256,av)
                bv=np.where(bv>=128,bv-256,bv)
                aa=self.e.source(av,8,not unsigned,name='attention_A_latch');bb=self.e.source(bv,8,name='attention_B_latch')
                acc=self.e.issue('mac_shift8' if plane else 'mac',[aa,bb,acc],32,True,'mac',(16,16),[aa,bb,acc],False)
        return acc
    def run_qk(self,q,k):
        assert q.shape==k.shape==(99,64) and q.dtype==k.dtype==np.int8
        qt=self.s.allocate('Q',99,64,8);kt=self.s.allocate('K',99,64,8)
        self.b.stage='QK_input';qt.write_host(q,self.beat_cycles);kt.write_host(k,self.beat_cycles)
        for start in range(0,99,16):self.load_A(qt,start,min(16,99-start),False)
        self.cache_keys(kt);self.s.release(kt)
        result=np.empty((99,99),np.int32)
        for start in range(0,99,16):
            count=min(16,99-start);dest=self.s.allocate('score_query_tile',count,99,32)
            for tile in range(7):
                acc=self.raw_mac(64,(start//16)*64,tile*64)
                values=np.asarray(self.e.consume(acc,'score_SRAM_write'),np.int64)
                self.b.stage='QK_score_write'
                for plane in range(4):
                    requests=[]
                    for row in range(0,count,2):
                        for col in range(min(16,99-tile*16)):
                            value=(int(values[row,col])>>(8*plane))&255
                            if row+1<count:value|=((int(values[row+1,col])>>(8*plane))&255)<<8
                            requests.append((*dest.word(row,tile*16+col,plane),'w',value))
                    self.b.batches(requests,'QK_score_word_write')
                self.e.drop(acc)
            result[start:start+count]=dest.debug_numpy();self.s.release(dest)
        self.s.release(qt)
        metrics=self.summary();metrics['scope']='standalone QK with tiled score SRAM write/readback, not full task'
        return result,metrics
    def run_pv(self,p,v,m,s):
        assert p.shape==(99,99) and p.dtype==np.uint16 and v.shape==(99,64) and v.dtype==np.int8
        self.b.stage='PV_input';pt=self.s.allocate('P_U16',99,99,16,False);vt=self.s.allocate('V',99,64,8)
        pt.write_host(p,self.beat_cycles);vt.write_host(v,self.beat_cycles)
        dest=self.s.allocate('context',99,64,8);self.cache_values(vt)
        # Keep V allocated through this standalone kernel to measure the real
        # conservative P+V+context simultaneous live set, rather than its sum.
        for start in range(0,99,16):
            count=min(16,99-start);self.load_A(pt,start,count,True)
            for tile in range(4):
                while len(self.jobs)>=2:self.credit_stalls+=1;self.e.step(1,'PV_accumulator_credit')
                coeff=self.fetch_coeff(np.full(64,int(m),np.int32),np.full(64,int(s),np.int32),np.zeros(64,np.int32),tile*16)
                acc=self.raw_mac(99,0,tile*99,True,2);self.rq_write(acc,coeff,dest,start,count,tile*16)
                for c in coeff:self.e.drop(c)
        while self.jobs or self.products or self.outputs:self.e.step(1,'PV_RQ_drain')
        result=dest.debug_numpy()
        for t in [pt,vt,dest]:self.s.release(t)
        metrics=self.summary();metrics['scope']='standalone U16 PV, unsigned low/high pass accumulation and exact context RQ; not full task'
        return result,metrics
