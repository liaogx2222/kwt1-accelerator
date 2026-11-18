"""Same 8x8 array and one wide multiplier/RNE/ALU: dependency-list scheduling.

Each node is a real retired Engine result. Independent units may issue together,
one operation/unit/cycle. Constant shifts fused into ALU wiring, never a second
multiply or a change of RNE/saturation semantics. External oracle only asserts.
"""
import collections
import numpy as np
from .executable_layer import ExecutableLayer
from .event_arithmetic import Engine,Cell,View

class FusedEngine(Engine):
    def issue(self,*args,**kwargs):
        unit=kwargs.get('unit',args[4] if len(args)>4 else 'alu')
        if unit in ('div','sqrt'):
            until=getattr(self,'iterative_ready',0)
            if until>self.now:self.step(until-self.now,'shared_iterative_resource')
        result=super().issue(*args,**kwargs)
        if unit in ('div','sqrt'):self.iterative_ready=result.ready
        return result
    @staticmethod
    def compute(op,a):
        if op=='center64':return (a[0]<<6)-a[1]
        if op=='var64':return (a[0]<<6)-a[1]
        if op=='h16':return (a[0]<<16)+a[1]
        if op=='prob_q':return ((a[0]<<16)-a[0])>>47
        if op=='prob_n':return (a[0]<<16)-a[0]
        return Engine.compute(op,a)

class Node:
    def __init__(self,op,args,bits=64,signed=True,unit='alu',shape=()):
        self.op,self.args,self.bits,self.signed,self.unit,self.shape=op,args,bits,signed,unit,shape
        self.cell=None;self.users=0
        for arg in args:
            if isinstance(arg,Node):arg.users+=1

class FusedLayer(ExecutableLayer):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        # Keep compact instrumentation supplied by unified runner.
        self.e.__class__=FusedEngine
    def graph(self,outputs):
        """Bounded deterministic oldest-ready issue; actual latency/II resources."""
        e=self.e;nodes=[];seen=set()
        def visit(n):
            if not isinstance(n,Node) or id(n) in seen:return
            seen.add(id(n))
            for a in n.args:visit(a)
            nodes.append(n)
        for n in outputs:visit(n);n.users+=1
        pending=list(nodes)
        while pending:
            issued=[];used=set()
            for n in pending:
                if n.unit in used or e.next_issue.get(n.unit,0)>e.now:continue
                args=[];ready=True
                for a in n.args:
                    if isinstance(a,Node):a=a.cell
                    if a is None:ready=False;break
                    if isinstance(a,(Cell,View)) and (a.parent if isinstance(a,View) else a).ready>e.now:ready=False;break
                    args.append(a)
                if not ready:continue
                n.cell=self.op(n.op,args,n.bits,n.signed,n.unit,advance=False,shape=n.shape)
                for arg in n.args:
                    if isinstance(arg,Node):
                        arg.users-=1
                        if arg.users==0:e.drop(arg.cell)
                issued.append(n);used.add(n.unit)
            if issued:
                ids={id(n) for n in issued};pending=[n for n in pending if id(n) not in ids]
                e.step(1,'parallel_unit_issue')
            else:
                ready_times=[a.cell.ready for n in pending for a in n.args if isinstance(a,Node) and a.cell is not None and a.cell.ready>e.now]
                ready_times += [a.ready for n in pending for a in n.args if isinstance(a,Cell) and a.ready>e.now]
                e.step(max(1,min(ready_times)-e.now) if ready_times else 1,'graph_dependency')
        return [n.cell for n in outputs]
    def initial_accumulator(self,bias,offset):
        values=np.zeros((8,8),np.int64)
        if bias is not None:
            for c in range(8):values[:,c]=self.e.consume(bias.view(offset+c),'PE_bias_load')
        return self.e.source(values,32,name='PE_bias_initialized_accumulator')
    def requant(self,acc,m,s,bias=None,column_offset=0):
        nr,nc=acc.shape;nodes=[]
        for r in range(nr):
            for c in range(nc):
                p=Node('mul',[acc.view((r,c)),m.view(column_offset+c)],64,True,'mul')
                nodes.append(Node('rne_sat8',[p,s.view(column_offset+c)],8,True,'rne'))
        cells=self.graph(nodes);self.e.drop(acc)
        return self.e.pack(cells,(nr,nc),8,True,'streamed_RQ')
    def context_codes(self,combined,cm,cs,count):
        nodes=[Node('rne_sat8',[Node('mul',[c,cm.view(0)],64,True,'mul'),cs.view(0)],8,True,'rne') for c in combined]
        cells=self.graph(nodes)
        for c in combined:self.e.drop(c)
        return self.e.pack(cells,(count,8),8,True,'streamed_context_RQ')
    def score_row(self,values,m,s,score_allocation=None):
        e=self.e;score=e.source(np.array(values,np.int64),32,name='softmax_scores',allocation=score_allocation)
        maximum=e.source(int(values[0]),32,name='softmax_max')
        for j in range(1,99):maximum=self.op('max',[maximum,score.view(j)],32,release=[maximum])
        nodes=[]
        for j in range(99):
            d=Node('sub',[score.view(j),maximum],32)
            p=Node('mul',[d,m.view(0)],64,True,'mul')
            nodes.append(Node('rne',[p,s.view(0)],32,True,'rne'))
        rounded=self.graph(nodes);e.drop(score);e.drop(maximum)
        ialloc=e.allocate('softmax_index_buffer',198);indexes=[]
        for c in rounded:indexes.append(max(0,min(4096,-int(e.consume(c,'exp_index')))));e.drop(c)
        allocation=e.allocate('softmax_exponents',396);exps=[]
        for index in indexes:
            if index==4096:self.b.tick(tag='exp_hardwired_zero');v=0
            else:
                lo,hi=self.b.tick([('E0',index,'r',0),('E1',index,'r',0)],tag='exp_read');v=lo|(hi<<16)
            exps.append(v)
        ex=e.source(np.array(exps,np.int64),32,False,name='softmax_exponents',allocation=allocation);e.release(ialloc)
        den=e.source(0,32,False,name='softmax_denominator')
        for j in range(99):den=self.op('add',[den,ex.view(j)],32,False,release=[den])
        qr=self.op('divmod',[1<<47,den],64,False,'div',shape=(2,))
        recip=self.op('ceil_qr',[qr.view(0),qr.view(1)],32,False,release=[qr])
        nodes=[]
        for j in range(99):
            er=Node('mul',[ex.view(j),recip],64,False,'mul');q=Node('prob_q',[er],32,False)
            n=Node('prob_n',[ex.view(j)],64,False);qd=Node('mul',[q,den],64,False,'mul')
            pair=Node('correct_qr',[n,q,qd,den],64,False,shape=(2,))
            # Views of a not-yet-issued vector node need explicit projection.
            # The correction + exact RNE remain two ALU cycles.
            nodes.append((pair,den))
        pairs=self.graph([n for n,d in nodes]);results=[]
        for pair in pairs:results.append(self.op('round_qr',[pair.view(0),pair.view(1),den],16,False,release=[pair]))
        for c in [den,recip,ex]:e.drop(c)
        return e.pack(results,(99,),16,False,'probability_row')
    def norm(self,j,start,count,destbase):
        self.phase('residual_ln'+str(j));e=self.e;rk=self.key+f'_r{j}'
        aa_alloc=e.allocate('residual_branch_A',count*64);bb_alloc=e.allocate('residual_branch_B',count*64)
        aa=np.empty((count,64),np.int64);bb=np.empty_like(aa)
        for ch in range(64):
            aa[:,ch]=self.rd('A',0,'token',range(start,start+count),ch,64)
            bb[:,ch]=self.rd('A',1664,'token',range(start,start+count),ch,64)
        a=e.source(aa,8,name='residual_A',allocation=aa_alloc);b=e.source(bb,8,name='residual_B',allocation=bb_alloc);coeff=self.fetch(rk+'_coeff')
        for row in range(count):
            nodes=[]
            for ch in range(64):
                ap=Node('mul',[a.view((row,ch)),coeff.view(0)],64,True,'mul')
                bp=Node('mul',[b.view((row,ch)),coeff.view(1)],64,True,'mul')
                nodes.append(Node('rne_sat16',[Node('add',[ap,bp],64),coeff.view(2)],16,True,'rne'))
            cells=self.graph(nodes);r=e.pack(cells,(64,),16,True,'residual_row');values=e.consume(r,'residual_write')
            for ch,value in enumerate(values):self.b.tick([('C0',2880+row*64+ch,'w',int(value)&65535)],tag='residual16_write')
            e.drop(r)
        for c in [a,b,coeff]:e.drop(c)
        self.ln_rows(j,start,count,destbase)
    def ln_rows(self,j,start,count,destbase):
        e=self.e;lk=self.key+f'_ln{j}'
        gamma=self.fetch(lk+'_g');beta=self.fetch(lk+'_b');eps=self.fetch(lk+'_eps');m=self.fetch(lk+'_m');s=self.fetch(lk+'_s')
        alloc=e.allocate('LN_output_pack',count*64);out=np.empty((count,64),np.int8)
        for row in range(count):
            ralloc=e.allocate('LN_S16_row',128);values=[]
            for ch in range(64):
                v=self.b.tick([('C0',2880+row*64+ch,'r',0)],tag='LN_read')[0];values.append(v if v<32768 else v-65536)
            rr=e.source(np.array(values,np.int64),16,name='LN_S16_row',allocation=ralloc)
            su=0;total=0
            for ch in range(64):
                su=Node('add',[su,rr.view(ch)],32)
                square=Node('mul',[rr.view(ch),rr.view(ch)],64,True,'mul')
                total=Node('add',[total,square],64,False)
            su,total=self.graph([su,total])
            sq=self.op('mul',[su,su],64,True,'mul')
            variance=self.op('var64',[total,sq],64,False,release=[total,sq])
            h=self.op('h16',[variance,eps.view(())],64,False,release=[variance])
            den=self.op('sqrt',[h],32,False,'sqrt',release=[h])
            pair=self.op('divmod',[1<<40,den],64,False,'div',shape=(2,))
            inv=self.op('round_qr',[pair.view(0),pair.view(1),den],32,False,release=[pair,den])
            nodes=[]
            for ch in range(64):
                center=Node('center64',[rr.view(ch),su],32)
                z=Node('rne',[Node('mul',[center,inv],64,True,'mul'),18],32,True,'rne')
                affine=Node('add',[Node('rne',[Node('mul',[z,gamma.view(ch)],64,True,'mul'),14],32,True,'rne'),beta.view(ch)],32)
                nodes.append(Node('rne_sat8',[Node('mul',[affine,m.view(())],64,True,'mul'),s.view(())],8,True,'rne'))
            cells=self.graph(nodes)
            for c in [su,rr,inv]:e.drop(c)
            code=e.pack(cells,(64,),8,True,'LN_output_row');out[row]=e.consume(code,'LN_pack_store');e.drop(code)
        self.write_tensor(out,'A',destbase,'token',start);e.release(alloc)
        for c in [gamma,beta,eps,m,s]:e.drop(c)
