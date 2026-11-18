"""Actual-value vector residual/LN, Softmax and GELU on hashed SP banks.

Standalone kernel contracts. Integer arithmetic retires before consumption;
golden code is not imported. Full-task transport/overlap is a later layer.
"""
import math
import numpy as np
from .competitive_hashed_banks import HashedPipelinedTile16
from .competitive_tile16_pipeline import ShiftedVectorEngine
from .event_arithmetic import signed_shift


class NonlinearEngine(ShiftedVectorEngine):
    def __init_extra(self):pass
    def issue(self,*args,**kwargs):
        unit=kwargs.get('unit',args[4] if len(args)>4 else 'alu')
        if unit in ['div','sqrt']:
            until=getattr(self,'iterative_until',0)
            if until>self.now:self.step(until-self.now,'shared_iterative')
        result=super().issue(*args,**kwargs)
        if unit in ['div','sqrt']:self.iterative_until=result.ready
        return result
    def compute(self,op,a):
        if op=='vadd':return a[0]+a[1]
        if op=='vsub':return a[0]-a[1]
        if op=='vgt':return (a[0]>a[1]).astype(np.int64)
        if op=='vcondsub':return a[0]-np.asarray(a[2],np.int64)*a[1]
        if op=='vcenter':return (a[0]<<6)-a[1]
        if op in ['vrne8','vrne16','vrne32']:
            values=np.asarray(a[0]).reshape(-1);shifts=np.broadcast_to(np.asarray(a[1]),values.shape)
            result=np.array([signed_shift(int(v),int(s)) for v,s in zip(values,shifts)],np.int64)
            return np.clip(result,-127,127) if op=='vrne8' else np.clip(result,-32767,32767) if op=='vrne16' else result
        if op=='vexpindex':return np.maximum(0,np.minimum(4096,-a[0]))
        if op=='vprobq':return np.array([((int(u)<<16)-int(u))>>47 for u in np.asarray(a[0]).reshape(-1)],np.int64)
        if op=='vprobnum':return (a[0]<<16)-a[0]
        if op=='vroundqr':
            return a[0]+((a[1]>a[2]-a[1])|((a[1]==a[2]-a[1])&((a[0]&1)!=0))).astype(np.int64)
        if op=='reduce_sum':return sum(map(int,np.asarray(a[0]).reshape(-1)))
        if op=='reduce_max':return max(map(int,np.asarray(a[0]).reshape(-1)))
        if op=='ln_var':return (int(a[0])<<6)-int(a[1])
        if op=='ln_h':return (int(a[0])<<16)+int(a[1])
        return super().compute(op,a)


class Node:
    def __init__(self,op,args,bits=64,signed=True,unit='valu',shape=()):
        self.op,self.args,self.bits,self.signed,self.unit,self.shape=op,args,bits,signed,unit,shape
        self.cell=None;self.users=0
        for a in args:
            if isinstance(a,Node):a.users+=1


class VectorNonlinear(HashedPipelinedTile16):
    def __init__(self,exp_table,lanes=4,beat_cycles=1):
        super().__init__(exp_table,lanes,beat_cycles)
        self.e.__class__=NonlinearEngine;self.e.lat.update(valu=1,reduce=2);self.e.II.update(valu=1,reduce=1)
    def graph(self,outputs):
        e=self.e;seen=set();nodes=[]
        def visit(n):
            if not isinstance(n,Node) or id(n) in seen:return
            seen.add(id(n))
            for a in n.args:visit(a)
            nodes.append(n)
        for n in outputs:visit(n);n.users+=1
        pending=list(nodes)
        while pending:
            issued=[];units=set()
            for n in pending:
                if n.unit in units or e.next_issue.get(n.unit,0)>e.now:continue
                args=[];ready=True
                for a in n.args:
                    if isinstance(a,Node):a=a.cell
                    if a is None:ready=False;break
                    root=a.parent if hasattr(a,'parent') else a
                    if hasattr(root,'ready') and root.ready>e.now:ready=False;break
                    args.append(a)
                if not ready:continue
                n.cell=e.issue(n.op,args,n.bits,n.signed,n.unit,n.shape,(),False)
                for a in n.args:
                    if isinstance(a,Node):
                        a.users-=1
                        if a.users==0:e.drop(a.cell)
                issued.append(n);units.add(n.unit)
            if issued:
                ids={id(n) for n in issued};pending=[n for n in pending if id(n) not in ids]
            e.step(1,'vector_graph')
        return [n.cell for n in outputs]
    def join(self,cells,bits,signed,name):
        values=np.concatenate([np.asarray(self.e.consume(c,name)).reshape(-1) for c in cells])
        for c in cells:self.e.drop(c)
        return self.e.source(values,bits,signed,name=name)
    def parameter(self,a,name,bits=32):
        a=np.asarray(a);allocation=self.e.allocate(name,max(1,a.size)*((bits+7)//8))
        self.e.step(max(1,a.nbytes//4)*self.beat_cycles,'parameter_32bit_load')
        return self.e.source(a.astype(np.int64),bits,name=name,allocation=allocation)
    def read_pair(self,t,row):
        count=min(2,t.rows-row);allocation=self.e.allocate('row_pair_buffer',count*t.cols*(t.bits//8))
        requests=[]
        for plane in range(t.bits//8):
            for col in range(t.cols):
                bank,address=t.word(row,col,plane);requests.append((bank,address,'r',0))
        words=self.b.batches(requests,'hashed_row_pair_read');values=np.zeros((count,t.cols),np.int64)
        for plane in range(t.bits//8):
            for col in range(t.cols):
                word=words[plane*t.cols+col]
                for r in range(count):values[r,col]|=((word>>(8*r))&255)<<(8*plane)
        if t.signed:values=np.where(values>=(1<<(t.bits-1)),values-(1<<t.bits),values)
        return self.e.source(values,t.bits,t.signed,name='row_pair',allocation=allocation)
    def write_pair(self,t,row,cells):
        values=np.stack([np.asarray(self.e.consume(c,'row_pair_output')).reshape(-1) for c in cells])
        for plane in range(t.bits//8):
            requests=[]
            for col in range(t.cols):
                bank,address=t.word(row,col,plane);word=(int(values[0,col])>>(8*plane))&255
                if len(cells)>1:word|=((int(values[1,col])>>(8*plane))&255)<<8
                requests.append((bank,address,'w',word))
            self.b.batches(requests,'hashed_row_pair_write')
        for c in cells:self.e.drop(c)
    def reduction(self,source,op,bits=64,signed=True):
        current=source;owned=False
        while max(1,math.prod(current.shape))>1:
            size=math.prod(current.shape);results=[]
            for start in range(0,size,4):
                results.append(self.e.issue(op,[current.view(slice(start,min(start+4,size)))],bits,signed,'reduce'))
            nxt=self.e.pack(results,(len(results),),bits,signed,'reduction_level')
            if owned:self.e.drop(current)
            current=nxt;owned=True
        value=int(np.asarray(self.e.consume(current,'reduced_scalar')).reshape(-1)[0])
        if owned:self.e.drop(current)
        return self.e.source(value,bits,signed,name='reduced_scalar')
    def norm_row(self,a,b,rc,gamma,beta,eps,m,s):
        e=self.e;parts=[]
        for start in range(0,64,self.lanes):
            sl=slice(start,min(start+self.lanes,64));shape=(sl.stop-sl.start,)
            ap=Node('vmul',[a.view(sl),rc.view(0)],unit='vmul',shape=shape)
            bp=Node('vmul',[b.view(sl),rc.view(1)],unit='vmul',shape=shape)
            add=Node('vadd',[ap,bp],shape=shape)
            parts.append(Node('vrne16',[add,rc.view(2)],16,True,'vrne',shape))
        residual=self.join(self.graph(parts),16,True,'residual_S16')
        sum_r=self.reduction(residual,'reduce_sum',32)
        square_nodes=[Node('vmul',[residual.view(slice(i,min(i+self.lanes,64))),residual.view(slice(i,min(i+self.lanes,64)))],32,False,'vmul',(min(self.lanes,64-i),)) for i in range(0,64,self.lanes)]
        squares=self.join(self.graph(square_nodes),32,False,'squares')
        sum_sq=self.reduction(squares,'reduce_sum',64,False);e.drop(squares)
        sq=e.issue('vmul',[sum_r,sum_r],64,True,'vmul')
        var=e.issue('ln_var',[sum_sq,sq],64,False,'valu',release=[sum_sq,sq])
        h=e.issue('ln_h',[var,eps],64,False,'valu',release=[var])
        root=e.issue('sqrt',[h],32,False,'sqrt',release=[h])
        div=e.issue('divmod',[1<<40,root],64,False,'div',(2,))
        reciprocal=e.issue('round_qr',[div.view(0),div.view(1),root],32,False,'valu',release=[div,root])
        nodes=[]
        for i in range(0,64,self.lanes):
            sl=slice(i,min(i+self.lanes,64));shape=(sl.stop-sl.start,)
            centered=Node('vcenter',[residual.view(sl),sum_r],32,True,'valu',shape)
            prod=Node('vmul',[centered,reciprocal],64,True,'vmul',shape)
            normalized=Node('vrne32',[prod,18],32,True,'vrne',shape)
            product=Node('vmul',[normalized,gamma.view(sl)],64,True,'vmul',shape)
            rounded=Node('vrne32',[product,14],32,True,'vrne',shape)
            affine=Node('vadd',[rounded,beta.view(sl)],32,True,'valu',shape)
            product=Node('vmul',[affine,m],64,True,'vmul',shape)
            nodes.append(Node('vrne8',[product,s],8,True,'vrne',shape))
        result=self.join(self.graph(nodes),8,True,'LN_codes')
        for c in [residual,sum_r,reciprocal]:e.drop(c)
        return result
    def softmax_row(self,score,m,s):
        e=self.e;maximum=self.reduction(score,'reduce_max',32);indices=[]
        for begin in range(0,99,16):
            nodes=[]
            for i in range(begin,min(begin+16,99),self.lanes):
                sl=slice(i,min(i+self.lanes,99));shape=(sl.stop-sl.start,)
                diff=Node('vsub',[score.view(sl),maximum],32,True,'valu',shape)
                product=Node('vmul',[diff,m],64,True,'vmul',shape)
                rounded=Node('vrne32',[product,s],32,True,'vrne',shape)
                nodes.append(Node('vexpindex',[rounded],16,False,'valu',shape))
            indices.extend(self.graph(nodes))
        index=self.join(indices,16,False,'Softmax_index');e.drop(maximum)
        ix=np.asarray(e.consume(index),np.int64);exps=[]
        allocation=e.allocate('Softmax_exp_values',99*4)
        for begin in range(0,99,self.lanes):
            locations=[];meta=[]
            for value in ix[begin:begin+self.lanes]:
                value=int(value)
                if value in [0,4096]:meta.append(('constant',1<<20 if value==0 else 0));continue
                width=self.widths[value//256]
                if not width:meta.append(('constant',0));continue
                bit=self.offsets[value//256]+(value%256)*width;word=bit//16;shift=bit%16
                keys=[]
                for part in range((shift+width+15)//16):
                    j=word+part;key=(f'A{j%8}',self.LUT_BASE+j//8);keys.append(key)
                    if key not in locations:locations.append(key)
                meta.append(('packed',keys,shift,width))
            words=self.b.batches([(bank,address,'r',0) for bank,address in locations],'exact_exp_cache_read')
            cache=dict(zip(locations,words))
            for item in meta:
                if item[0]=='constant':exps.append(item[1])
                else:
                    value=sum(cache[key]<<(16*j) for j,key in enumerate(item[1]));exps.append((value>>item[2])&((1<<item[3])-1))
            e.step(1,'exp_bit_unpack')
        exponent=e.source(np.array(exps,np.int64),32,False,name='Softmax_exps',allocation=allocation);e.drop(index)
        denominator=self.reduction(exponent,'reduce_sum',32,False)
        div=e.issue('divmod',[1<<47,denominator],64,False,'div',(2,))
        reciprocal=e.issue('ceil_qr',[div.view(0),div.view(1)],32,False,'valu',release=[div]);results=[]
        for begin in range(0,99,16):
            nodes=[]
            for i in range(begin,min(begin+16,99),self.lanes):
                sl=slice(i,min(i+self.lanes,99));shape=(sl.stop-sl.start,)
                er=Node('vmul',[exponent.view(sl),reciprocal],64,False,'vmul',shape)
                q=Node('vprobq',[er],32,False,'valu',shape)
                numerator=Node('vprobnum',[exponent.view(sl)],64,False,'valu',shape)
                qd=Node('vmul',[q,denominator],64,False,'vmul',shape)
                over=Node('vgt',[qd,numerator],1,False,'valu',shape)
                cq=Node('vsub',[q,over],32,False,'valu',shape)
                product=Node('vcondsub',[qd,denominator,over],64,False,'valu',shape)
                remainder=Node('vsub',[numerator,product],64,False,'valu',shape)
                nodes.append(Node('vroundqr',[cq,remainder,denominator],16,False,'valu',shape))
            results.extend(self.graph(nodes))
        result=self.join(results,16,False,'probabilities')
        for c in [exponent,denominator,reciprocal]:e.drop(c)
        return result
    def summary(self):
        live=self.e.close();assert not self.s.live
        peak=live['peak_bytes']+554
        return dict(cycles=self.b.cycle,kernel_cycles_excluding_common=self.b.cycle-self.common_cycles,
            common_load_cycles=self.common_cycles,operations=live['operations'],peak_live_allocations=live['peak_live_allocations'],
            scratch_peak_bytes=self.s.peak,scratch_bank_peak_bytes=self.s.bank_peak,
            register_data_and_pipeline_peak=live['peak_bytes'],total_register_peak_bytes=peak,
            register_4KiB_pass=peak<=4096,private_SRAM_bytes=65536,new_RTL_implemented=False,
            full_task_executed=False,complete_IO_model=False,all_targets_met=False)
    def run_norm(self,a,b,params,key,j):
        n,k=a.shape;assert (n,k)==(99,64) and b.dtype==np.int8
        self.b.stage='LN_input';aa=self.s.allocate('branch_A',n,k,a.dtype.itemsize*8);bb=self.s.allocate('branch_B',n,k,8);dest=self.s.allocate('norm',n,k,8)
        aa.write_host(a,self.beat_cycles);bb.write_host(b,self.beat_cycles)
        rc=self.parameter(params[key+f'_r{j}_coeff'],'residual_coeff',32)
        prefix=key+f'_ln{j}'
        gamma=self.parameter(params[prefix+'_g'],'gamma');beta=self.parameter(params[prefix+'_b'],'beta')
        eps=self.parameter(params[prefix+'_eps'],'epsilon',64);m=self.parameter(params[prefix+'_m'],'LN_m');s=self.parameter(params[prefix+'_s'],'LN_s')
        self.b.stage='residual_LN'
        for row in range(0,n,2):
            pa=self.read_pair(aa,row);pb=self.read_pair(bb,row);values=[]
            for r in range(min(2,n-row)):
                av=self.e.source(self.e.consume(pa)[r].copy(),aa.bits,name='LN_A_row')
                bv=self.e.source(self.e.consume(pb)[r].copy(),8,name='LN_B_row')
                values.append(self.norm_row(av,bv,rc,gamma,beta,eps,m,s));self.e.drop(av);self.e.drop(bv)
            self.write_pair(dest,row,values);self.e.drop(pa);self.e.drop(pb)
        result=dest.debug_numpy()
        for c in [rc,gamma,beta,eps,m,s]:self.e.drop(c)
        for t in [aa,bb,dest]:self.s.release(t)
        return result,self.summary()
    def run_softmax(self,scores,params,key):
        assert scores.shape==(99,99) and scores.dtype==np.int32
        m=self.parameter(params[key+'_score_m'],'score_m');s=self.parameter(params[key+'_score_s'],'score_s')
        result=np.empty((99,99),np.uint16)
        for start in range(0,99,16):
            count=min(16,99-start);source=self.s.allocate('scores',count,99,32);dest=self.s.allocate('probability',count,99,16,False)
            self.b.stage='score_tile_input';source.write_host(scores[start:start+count],self.beat_cycles);self.b.stage='Softmax'
            for row in range(0,count,2):
                pair=self.read_pair(source,row);outputs=[]
                for r in range(min(2,count-row)):
                    a=self.e.source(self.e.consume(pair)[r].copy(),32,name='Softmax_score_row')
                    outputs.append(self.softmax_row(a,m,s));self.e.drop(a)
                self.write_pair(dest,row,outputs);self.e.drop(pair)
            result[start:start+count]=dest.debug_numpy().astype(np.uint16);self.s.release(source);self.s.release(dest)
        self.e.drop(m);self.e.drop(s)
        return result,self.summary()
    def run_gelu(self,x,table):
        assert x.dtype==np.int8 and x.shape==(99,256)
        self.b.stage='GELU_input';t=self.s.allocate('hidden',99,256,8);t.write_host(x,self.beat_cycles)
        self.b.stage='GELU_cache';words=np.frombuffer(table.tobytes(),dtype='<u2')
        for address,word in enumerate(words):self.b.tick([(f'B{bank}',address,'w',int(word)) for bank in range(8)],'GELU_eight_copy_fill')
        self.b.stage='GELU'
        for row in range(0,99,2):
            for start in range(0,256,4):
                loc=[t.word(row,col) for col in range(start,start+4)]
                words=self.b.tick([(bank,address,'r',0) for bank,address in loc],'GELU_input_read')
                codes=np.array([((word>>(8*r))&255) for word in words for r in range(2)],np.int64);codes=np.where(codes>=128,codes-256,codes)
                source=self.e.source(codes,8,name='GELU_input_latch')
                indexes=codes+128
                look=self.b.tick([(f'B{i}',int(index)//2,'r',0) for i,index in enumerate(indexes)],'GELU_cache_lookup')
                values=np.array([(look[i]>>(8*(int(index)%2)))&255 for i,index in enumerate(indexes)],np.int64)
                values=np.where(values>=128,values-256,values);cell=self.e.source(values,8,name='GELU_output_latch')
                ops=[]
                for i,(bank,address) in enumerate(loc):
                    value=int(values[2*i])&255
                    if row+1<99:value|=(int(values[2*i+1])&255)<<8
                    ops.append((bank,address,'w',value))
                self.b.tick(ops,'GELU_inplace_write');self.e.drop(source);self.e.drop(cell)
        result=t.debug_numpy();self.s.release(t)
        return result,self.summary()
