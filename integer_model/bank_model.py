"""P4b conservative single-port 8x8 schedule with real integer SRAM data.

No overlap is credited: operand fetch/MAC, shared RQ, and packed writes are
separate. Every SRAM request appears in a per-cycle trace. 1-cycle read,
32x32 multiplier II=1/latency=3 plus RNE=1, divider=64, isqrt=32 are declared
architectural assumptions, not measured macro/standard-cell properties.
"""
import collections
import gzip
import json
import math
import numpy as np
from .runtime import Encoder,rq,shift_rne,sat
from .hw_abi import bank_weights


class Banks:
    def __init__(self,path):
        # Poison initial SRAM: padding/unused storage must never be assumed zero.
        self.mem={**{f'W{i}':np.full(8192,0xA5A5,np.uint16) for i in range(4)},
                  **{f'{g}{i}':np.full(4096,0xA5A5,np.uint16) for g,n in [('A',4),('B',4),('C',2),('E',2)] for i in range(n)}}
        self.cycle=0;self.stage='load';self.kind='';self.counts=collections.Counter();self.stage_cycles=collections.Counter()
        self.resource_calls=collections.Counter();self.trace=gzip.open(path,'wt',encoding='utf-8',compresslevel=3)
        self.max_bytes=0
    def tick(self,ops=(),tag='',issue=None):
        seen=set();values=[]
        for bank,address,mode,value in ops:
            if bank in seen:raise ValueError('Unscheduled single-port conflict '+bank)
            seen.add(bank)
            if bank not in self.mem or not 0<=address<len(self.mem[bank]):raise ValueError('SRAM address outside macro')
            if mode=='r':values.append(int(self.mem[bank][address]))
            elif mode=='w':
                if not 0<=int(value)<=65535:raise ValueError('Not a 16-bit word')
                self.mem[bank][address]=value
            else:raise ValueError('Invalid memory opcode')
            self.counts[(bank,mode)]+=1
        row={'cycle':self.cycle,'stage':self.stage,'tag':tag,'ports':ops}
        if values:row['read_data_available_next_cycle']=values
        if issue:row['arithmetic']=issue
        self.trace.write(json.dumps(row,separators=(',',':'))+'\n')
        self.max_bytes=max(self.max_bytes,2*len(ops));self.stage_cycles[(self.stage,tag)]+=1
        self.cycle+=1
        return values
    def idle(self,n,tag):
        for _ in range(n):self.tick(tag=tag)
    def wide(self,n,operation):
        self.resource_calls[operation]+=n
        for i in range(n):self.tick(tag='wide_issue',issue={'unit':'mul32','op':operation,'index':i,'retire_at':self.cycle+4})
        self.idle(4,'wide_drain')
    def divide(self,n,op):
        self.resource_calls[op]+=n
        self.idle(64*n,'divider64_'+op)
    def sqrt(self,n):
        self.resource_calls['isqrt64']+=n
        self.idle(32*n,'isqrt64')


def address(layout,base,token,ch,width):
    if layout=='token':return (token%8)//2,base+(token//8)*width+ch,token%2
    if layout=='channel':return (ch%8)//2,base+token*(width//8)+ch//8,ch%2
    raise ValueError(layout)


class LayerModel:
    def __init__(self,p,trace,layer=0):
        self.p=p;self.layer=layer;self.key=f'l{layer:02d}';self.b=Banks(trace);self.ref=Encoder(p)
        self.wbase={};self.cbase={};self.layouts={};self.register_bytes_peak=4096
    def rd(self,group,base,layout,tokens,ch,width):
        ops=[];loc=[]
        # All requests refer to the same reduction channel; gather packed pairs.
        for token in tokens:
            bank,addr,byte=address(layout,base,token,ch,width)
            found=next((i for i,(bb,aa,mm,v) in enumerate(ops) if bb==group+str(bank) and aa==addr),None)
            if found is None:
                found=len(ops);ops.append((group+str(bank),addr,'r',0))
            loc.append((found,byte))
        # A different address in the same bank is serialized, never silently free.
        pending=list(enumerate(ops));result=[0]*len(ops)
        while pending:
            batch=[];ids=[];used=set();rest=[]
            for idx,op in pending:
                if op[0] in used:rest.append((idx,op))
                else:used.add(op[0]);batch.append(op);ids.append(idx)
            values=self.b.tick(batch,tag='operand_read')
            for idx,v in zip(ids,values):result[idx]=v
            pending=rest
        return np.array([((result[i]>>(8*byte))&255) for i,byte in loc],np.uint8).view(np.int8)
    def write_tensor(self,x,group,base,layout,t0=0):
        requests={}
        for row in range(len(x)):
            token=t0+row
            for ch in range(x.shape[-1]):
                bank,addr,byte=address(layout,base,token,ch,x.shape[-1])
                key=(group+str(bank),addr)
                requests[key]=requests.get(key,0)|((int(x[row,ch])&255)<<(8*byte))
        pending=[(bank,addr,'w',v) for (bank,addr),v in sorted(requests.items(),key=lambda a:(a[0][1],a[0][0]))]
        while pending:
            batch=[];used=set();rest=[]
            for op in pending:
                if op[0] in used:rest.append(op)
                else:used.add(op[0]);batch.append(op)
            self.b.tick(batch,tag='packed_write');pending=rest
    def peek(self,group,base,layout,width):
        x=np.empty((99,width),np.int8)
        for token in range(99):
            for ch in range(width):
                bank,addr,byte=address(layout,base,token,ch,width)
                v=(int(self.b.mem[group+str(bank)][addr])>>(byte*8))&255
                x[token,ch]=v if v<128 else v-256
        return x
    def coeff(self,name,indices=None):
        a=self.p[name]
        indices=list(range(a.size)) if indices is None else list(indices)
        size=a.dtype.itemsize
        values=bytearray()
        for index in indices:
            for j in range(size//4):
                addr=self.cbase[name]+index*(size//4)+j
                lo,hi=self.b.tick([('C0',addr,'r',0),('C1',addr,'r',0)],tag='coefficient_read')
                values.extend(int(lo|(hi<<16)).to_bytes(4,'little'))
        out=np.frombuffer(values,dtype=a.dtype).copy()
        return out.reshape(a.shape) if indices==list(range(a.size)) else out
    def load(self,x):
        self.b.stage='cold_local_load'
        offset=0
        for name in ['q','k','v','o','fc1','fc2']:
            key=self.key+'_'+name;w=self.p[key+'_w'];data=np.frombuffer(bank_weights(w),np.uint16).reshape(4,-1)
            self.wbase[key]=offset
            for bank in range(4):
                for j,v in enumerate(data[bank]):self.b.tick([(f'W{bank}',offset+j,'w',int(v))],tag='weight_load_16bit')
            offset+=data.shape[1]
        assert offset==6144
        payload=bytearray()
        for name in sorted(self.p):
            if not name.startswith(self.key+'_') or name.endswith(('_w','_gelu_lut','_q_b','_k_b','_v_b')):continue
            a=self.p[name];assert a.dtype.itemsize>=4
            self.cbase[name]=len(payload)//4;payload.extend(a.tobytes())
        words=np.frombuffer(payload,np.uint32);assert len(words)<=1880
        for i,w in enumerate(words):self.b.tick([('C0',i,'w',int(w)&65535),('C1',i,'w',int(w)>>16)],tag='coefficient_load')
        gelu=np.frombuffer(self.p[self.key+'_gelu_lut'].tobytes(),np.uint16)
        for i,w in enumerate(gelu):self.b.tick([('C0',1880+i,'w',int(w))],tag='gelu_load')
        for i,w in enumerate(self.p['exp_lut'][:4096]):self.b.tick([('E0',i,'w',int(w)&65535),('E1',i,'w',int(w)>>16)],tag='exp_load')
        self.write_tensor(x,'A',0,'token')
        self.local_load_cycles=self.b.cycle
    def dense(self,name,source,dest,tokens=range(99)):
        key=self.key+'_'+name;w=self.p[key+'_w'];k,n=w.shape;group,base,layout=source
        target_group,target_base,target_layout=dest;self.b.stage=name
        tokens=list(tokens)
        for start in range(0,len(tokens),8):
            valid=tokens[start:start+8];padded=valid+[valid[-1]+j+1 for j in range(8-len(valid))]
            for ot in range(n//8):
                m=self.coeff(key+'_m',range(ot*8,ot*8+8));s=self.coeff(key+'_s',range(ot*8,ot*8+8))
                bias=np.zeros(8,np.int32) if name in ['q','k','v'] else self.coeff(key+'_b',range(ot*8,ot*8+8))
                xx=np.empty((8,k),np.int32);ww=np.empty((k,8),np.int32)
                for red in range(k):
                    # Known layouts guarantee one word/bank for eight rows.
                    assert layout=='token'
                    aops=[(group+str(bank),base+(padded[0]//8)*k+red,'r',0) for bank in range(4)]
                    wops=[(f'W{bank}',self.wbase[key]+ot*k+red,'r',0) for bank in range(4)]
                    vals=self.b.tick(aops+wops,tag='dense_mac_operand_issue')
                    xx[:,red]=np.frombuffer(np.array(vals[:4],np.uint16).tobytes(),np.int8).astype(np.int32)
                    ww[red]=np.frombuffer(np.array(vals[4:],np.uint16).tobytes(),np.int8).astype(np.int32)
                self.b.idle(1,'last_mac_retire')
                acc=xx@ww+bias
                out=sat(rq(acc,m,s),8)[:len(valid)]
                self.b.wide(8*len(valid),'dense_RQ')
                # write_tensor expects complete channels, so explicit tile address packing.
                ops={}
                for row,token in enumerate(valid):
                    for col in range(8):
                        bank,addr,byte=address(target_layout,target_base,token,ot*8+col,n)
                        kk=(target_group+str(bank),addr);ops[kk]=ops.get(kk,0)|((int(out[row,col])&255)<<(8*byte))
                self.write_requests(ops)
    def write_requests(self,requests):
        queue=[(b,a,'w',v) for (b,a),v in sorted(requests.items(),key=lambda a:(a[0][1],a[0][0]))]
        while queue:
            seen=set();batch=[];rest=[]
            for op in queue:
                if op[0] in seen:rest.append(op)
                else:seen.add(op[0]);batch.append(op)
            self.b.tick(batch,tag='packed_write');queue=rest
    def attention(self,expected):
        for start in range(0,99,8):
            count=min(8,99-start);score=np.zeros((count,99),np.int32);self.b.stage='qk'
            for kt in range(13):
                qq=np.empty((8,64),np.int32);kk=np.empty((8,64),np.int32)
                for red in range(64):
                    ops=[(f'A{bank}',832+(start//8)*64+red,'r',0) for bank in range(4)]
                    ops +=[(f'B{bank}',kt*64+red,'r',0) for bank in range(4)]
                    vals=self.b.tick(ops,tag='qk_mac_operand_issue')
                    qq[:,red]=np.frombuffer(np.array(vals[:4],np.uint16).tobytes(),np.int8)
                    kk[:,red]=np.frombuffer(np.array(vals[4:],np.uint16).tobytes(),np.int8)
                self.b.idle(1,'last_mac_retire');tile=qq@kk.T
                for r in range(count):
                    for col in range(min(8,99-kt*8)):
                        value=int(tile[r,col]);j=kt*8+col;score[r,j]=value
                        addr=2048+r*99+j
                        self.b.tick([('C0',addr,'w',value&65535),('C1',addr,'w',(value>>16)&65535)],tag='score_write32')
            assert np.array_equal(score,expected['attention_score_raw'][start:start+count])
            self.b.stage='softmax';sm=self.coeff(self.key+'_score_m');ss=self.coeff(self.key+'_score_s')
            probabilities=np.zeros((8,99),np.uint16)
            for r in range(count):
                restored=[]
                for j in range(99):
                    lo,hi=self.b.tick([('C0',2048+r*99+j,'r',0),('C1',2048+r*99+j,'r',0)],tag='score_read_max')
                    v=lo|(hi<<16);restored.append(v if v<(1 << 31) else v-(1 << 32))
                arr=np.array(restored,np.int64);idx=-np.clip(rq(arr-arr.max(),sm,ss),-4096,0)
                self.b.wide(99,'score_RQ')
                for index in idx:
                    if index==4096:self.b.tick(tag='exp_hardwired_zero')
                    else:
                        lo,hi=self.b.tick([('E0',int(index),'r',0),('E1',int(index),'r',0)],tag='exp_read_sum')
                        assert (lo|(hi<<16))==int(self.p['exp_lut'][index])
                self.b.divide(1,'softmax_reciprocal')
                self.b.wide(99,'softmax_e_times_R');self.b.wide(99,'softmax_q_times_D')
                probabilities[r]=self.ref.softmax(np.array(restored,np.int32)[None,None,:],self.key+'_score','dummy')[0,0]
                # Keep two rows, then pack both probability byte planes without RMW.
                if r%2 or r==count-1:
                    bank=r//2;rr=r if r%2==0 else r-1
                    for j in range(99):
                        a=int(probabilities[rr,j]);b=int(probabilities[rr+1,j])
                        self.b.tick([(f'A{bank}',1664+j,'w',(a&255)|((b&255)<<8))],tag='probability_low_write')
                        self.b.tick([(f'A{bank}',1664+99+j,'w',(a>>8)|((b>>8)<<8))],tag='probability_high_write')
            assert np.array_equal(probabilities[:count],expected['attention_softmax'][start:start+count])
            # Unused query banks must contain zero P instead of prior query data.
            for bank in range((count+1)//2,4):
                for j in range(198):self.b.tick([(f'A{bank}',1664+j,'w',0)],tag='query_tail_clear')
            self.b.stage='pv';cm=self.coeff(self.key+'_ctx_m');cs=self.coeff(self.key+'_ctx_s')
            for ot in range(8):
                accum=np.zeros((8,8),np.int64)
                for plane in range(2):
                    pp=np.empty((8,99),np.int32);vv=np.empty((99,8),np.int32)
                    for j in range(99):
                        ops=[(f'A{bank}',1664+plane*99+j,'r',0) for bank in range(4)]
                        ops +=[(f'B{bank}',832+j*8+ot,'r',0) for bank in range(4)]
                        vals=self.b.tick(ops,tag='pv_u8_s8_mac_operand_issue')
                        pp[:,j]=np.frombuffer(np.array(vals[:4],np.uint16).tobytes(),np.uint8)
                        vv[j]=np.frombuffer(np.array(vals[4:],np.uint16).tobytes(),np.int8)
                    self.b.idle(1,'last_mac_retire');accum+=(pp@vv).astype(np.int64)<<(8*plane)
                self.b.wide(count*8,'context_RQ');out=sat(rq(accum,cm,cs),8)[:count]
                requests={}
                for row in range(count):
                    for col in range(8):
                        bank,addr,byte=address('token',2496,start+row,ot*8+col,64)
                        k=(f'A{bank}',addr);requests[k]=requests.get(k,0)|((int(out[row,col])&255)<<(8*byte))
                self.write_requests(requests)
            assert np.array_equal(self.peek('A',2496,'token',64)[start:start+count],expected['attention_context'][start:start+count])
            self.dense('o',('A',2496,'token'),('A',1664,'token'),range(start,start+count))
            assert np.array_equal(self.peek('A',1664,'token',64)[start:start+count],expected['attention_output_projection'][start:start+count])
            self.norm(1,start,count,0)
    def norm(self,j,start,count,destbase):
        self.b.stage=f'residual_ln{j}'
        aa=np.empty((count,64),np.int8);bb=np.empty_like(aa);tokens=list(range(start,start+count))
        for ch in range(64):
            aa[:,ch]=self.rd('A',0,'token',tokens,ch,64)
            bb[:,ch]=self.rd('A',1664,'token',tokens,ch,64)
        p=dict(self.p);rk=self.key+f'_r{j}';lk=self.key+f'_ln{j}'
        p[rk+'_coeff']=self.coeff(rk+'_coeff')
        for suffix in ['g','b','eps','m','s']:p[lk+'_'+suffix]=self.coeff(lk+'_'+suffix)
        r=Encoder(p).residual(aa,bb,rk,'dummy')
        self.b.wide(r.size*2,'residual_alignment')
        for idx,v in enumerate(r.ravel()):self.b.tick([('C0',2880+idx,'w',int(v)&65535)],tag='residual16_write')
        # LN statistics read the materialized residual, preserving original branch.
        reloaded=[]
        for idx in range(r.size):
            value=self.b.tick([('C0',2880+idx,'r',0)],tag='ln_stats_read')[0]
            reloaded.append(value if value<32768 else value-65536)
        r=np.array(reloaded,np.int16).reshape(r.shape)
        self.b.wide(r.size,'ln_T_square');self.b.wide(count,'ln_S_square')
        self.b.sqrt(count);self.b.divide(count,'ln_reciprocal')
        self.b.wide(r.size,'ln_center_times_R');self.b.wide(r.size,'ln_affine');self.b.wide(r.size,'ln_output_RQ')
        out=Encoder(p).layernorm(r,lk,'dummy')
        self.write_tensor(out,'A',destbase,'token',start)
    def gelu(self):
        self.b.stage='gelu'
        for block in range(13):
            valid=min(8,99-block*8)
            for ch in range(256):
                ops=[(f'B{bank}',block*256+ch,'r',0) for bank in range((valid+1)//2)]
                words=self.b.tick(ops,tag='hidden_read');out=np.zeros(8,np.int8)
                codes=np.frombuffer(np.array(words,np.uint16).tobytes(),np.int8)
                for row in range(valid):
                    idx=int(codes[row])+128
                    word=self.b.tick([('C0',1880+idx//2,'r',0)],tag='gelu_single_port_lookup')[0]
                    byte=(word>>(8*(idx%2)))&255;out[row]=byte if byte<128 else byte-256
                packed=np.frombuffer(out.tobytes(),np.uint16)
                self.b.tick([(f'B{bank}',block*256+ch,'w',int(packed[bank])) for bank in range((valid+1)//2)],tag='hidden_gelu_write')
    def run(self,x,expected):
        self.load(x)
        self.dense('q',('A',0,'token'),('A',832,'token'))
        assert np.array_equal(self.peek('A',832,'token',64),expected['q_projection'])
        self.dense('k',('A',0,'token'),('B',0,'token'))
        assert np.array_equal(self.peek('B',0,'token',64),expected['k_projection'])
        self.dense('v',('A',0,'token'),('B',832,'channel'))
        assert np.array_equal(self.peek('B',832,'channel',64),expected['v_projection'])
        self.attention(expected)
        assert np.array_equal(self.peek('A',0,'token',64),expected['layernorm1_output'])
        self.dense('fc1',('A',0,'token'),('B',0,'token'))
        assert np.array_equal(self.peek('B',0,'token',256),expected['ffn_dense1_output'])
        self.gelu()
        assert np.array_equal(self.peek('B',0,'token',256),expected['gelu_output'])
        self.dense('fc2',('B',0,'token'),('A',1664,'token'))
        assert np.array_equal(self.peek('A',1664,'token',64),expected['ffn_dense2_output'])
        for start in range(0,99,8):self.norm(2,start,min(8,99-start),832)
        out=self.peek('A',832,'token',64)
        assert np.array_equal(out,expected['layernorm2_output'])
        # The conservative controller always starts the next layer at A[0].
        # Charge this copy explicitly; a future proven ping-pong controller may
        # remove it. Never credit a free handoff between different base slots.
        self.b.stage='handoff_copy';begin=self.b.cycle
        for word in range(832):
            values=self.b.tick([(f'A{bank}',832+word,'r',0) for bank in range(4)],tag='handoff_read')
            self.b.tick([(f'A{bank}',word,'w',v) for bank,v in enumerate(values)],tag='handoff_write')
        self.handoff_cycles=self.b.cycle-begin
        assert np.array_equal(self.peek('A',0,'token',64),out)
        self.b.trace.close()
        return out
