"""Bounded two-row graph scheduling, unchanged units/formulas/rounding points."""
from .competitive_core_tradeoff import TradeoffCore
from .competitive_norm_pipeline import PendingNorm
from .competitive_softmax_pipeline import PendingRow
from .competitive_nonlinear import Node,VectorNonlinear


class FusedRowsCore(TradeoffCore):
    def __init__(self,*a,fusion='both',**k):
        if fusion not in ['none','ln','softmax','both']:raise ValueError('fusion mode')
        self.fusion=fusion;self.fused_norm_pairs=0;self.fused_softmax_pairs=0
        super().__init__(*a,**k)
    def reset(self):
        config=self.config;buffers=self.accumulator_buffers;fusion=self.fusion
        self.__init__(*config,accumulator_buffers=buffers,fusion=fusion)
    def finish_norm_batch(self,rows):
        e=self.e
        while any(r.division is None for r in rows):self.norm_finish_wait+=1;e.step(1,'fused_LN_wait_div_issue')
        outputs=[]
        for r in rows:
            reciprocal=Node('round_qr',[r.division.view(0),r.division.view(1),r.root],32,False,'valu')
            for i in range(0,64,self.lanes):
                sl=slice(i,min(i+self.lanes,64));shape=(sl.stop-sl.start,)
                centered=Node('vcenter',[r.residual.view(sl),r.total],32,True,'valu',shape)
                prod=Node('vmul',[centered,reciprocal],64,True,'vmul',shape)
                normalized=Node('vrne32',[prod,18],32,True,'vrne',shape)
                product=Node('vmul',[normalized,r.gamma.view(sl)],64,True,'vmul',shape)
                rounded=Node('vrne32',[product,14],32,True,'vrne',shape)
                affine=Node('vadd',[rounded,r.beta.view(sl)],32,True,'valu',shape)
                product=Node('vmul',[affine,r.m],64,True,'vmul',shape)
                outputs.append(Node('vrne8',[product,r.s],8,True,'vrne',shape))
        cells=self.graph(outputs);n=(64+self.lanes-1)//self.lanes
        results=[self.join(cells[j*n:(j+1)*n],8,True,'fused_LN_codes') for j in range(len(rows))]
        for r in rows:
            for c in [r.residual,r.total,r.division,r.root]:e.drop(c)
            e.release(r.tag);self.norm_rows.remove(r)
        self.fused_norm_pairs+=1;return results
    def softmax_nodes(self,row,reciprocal,begin,end):
        nodes=[]
        for i in range(begin,end,self.lanes):
            sl=slice(i,min(i+self.lanes,end));shape=(sl.stop-sl.start,)
            er=Node('vmul',[row.exponent.view(sl),reciprocal],64,False,'vmul',shape)
            q=Node('vprobq',[er],32,False,'valu',shape)
            numerator=Node('vprobnum',[row.exponent.view(sl)],64,False,'valu',shape)
            qd=Node('vmul',[q,row.denominator],64,False,'vmul',shape)
            over=Node('vgt',[qd,numerator],1,False,'valu',shape)
            cq=Node('vsub',[q,over],32,False,'valu',shape)
            product=Node('vcondsub',[qd,row.denominator,over],64,False,'valu',shape)
            remainder=Node('vsub',[numerator,product],64,False,'valu',shape)
            nodes.append(Node('vroundqr',[cq,remainder,row.denominator],16,False,'valu',shape))
        return nodes
    def finish_softmax_batch(self,rows):
        e=self.e;result=[[] for r in rows]
        reciprocals=[Node('ceil_qr',[r.division.view(0),r.division.view(1)],32,False,'valu') for r in rows]
        for begin in range(0,99,16):
            end=min(begin+16,99);n=(end-begin+self.lanes-1)//self.lanes
            outputs=[]
            for r,rec in zip(rows,reciprocals):outputs.extend(self.softmax_nodes(r,rec,begin,end))
            first=begin==0;cells=self.graph((reciprocals if first else [])+outputs)
            if first:reciprocals=cells[:len(rows)];cells=cells[len(rows):]
            for j in range(len(rows)):result[j].extend(cells[j*n:(j+1)*n])
        results=[self.join(c,16,False,'fused_probabilities') for c in result]
        for r,rec in zip(rows,reciprocals):
            for c in [r.exponent,r.denominator,r.division,rec]:e.drop(c)
            self.pending_rows-=1
        self.fused_softmax_pairs+=1;return results
    def write_pair(self,t,row,cells):
        if len(cells)==2 and isinstance(cells[0],PendingNorm) and self.fusion in ['ln','both']:
            return VectorNonlinear.write_pair(self,t,row,self.finish_norm_batch(cells))
        if len(cells)==2 and isinstance(cells[0],PendingRow) and self.fusion in ['softmax','both']:
            return VectorNonlinear.write_pair(self,t,row,self.finish_softmax_batch(cells))
        return super().write_pair(t,row,cells)
    def summary(self):
        r=super().summary();r.update(fusion=self.fusion,fused_norm_pairs=self.fused_norm_pairs,fused_softmax_pairs=self.fused_softmax_pairs,
            extra_arithmetic_units=0,context_capacity=2,scope='whole-core two-row graph scheduling model; not complete RTL/CPU/packet/PPA')
        return r
