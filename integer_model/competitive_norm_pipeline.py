"""Two-row residual/LN staging with the SAME shared sqrt/div unit.

An explicit sidecar issues a row's divide after its sqrt completes. All data,
including iterative results and row context tags, have Engine lifetimes.
"""
import numpy as np
from .competitive_nonlinear import VectorNonlinear,Node


class PendingNorm:
    def __init__(self,residual,total,root,gamma,beta,m,s,tag):
        self.residual,self.total,self.root=residual,total,root
        self.gamma,self.beta,self.m,self.s=gamma,beta,m,s
        self.tag=tag;self.division=None


class PipelinedNorm(VectorNonlinear):
    def __init__(self,*a,**k):
        self.norm_rows=[];self.norm_rows_peak=0;self.norm_finish_wait=0
        super().__init__(*a,**k)
    def background(self,main):
        writes=super().background(main)
        e=self.e
        if getattr(e,'iterative_until',0)<=e.now and e.next_issue.get('div',0)<=e.now:
            row=next((r for r in self.norm_rows if r.division is None and r.root.ready<=e.now),None)
            if row is not None:row.division=e.issue('divmod',[1<<40,row.root],64,False,'div',(2,),(),False)
        return writes
    def norm_row(self,a,b,rc,gamma,beta,eps,m,s):
        assert len(self.norm_rows)<2,'two-row LN context capacity'
        e=self.e;parts=[]
        for start in range(0,64,self.lanes):
            sl=slice(start,min(start+self.lanes,64));shape=(sl.stop-sl.start,)
            ap=Node('vmul',[a.view(sl),rc.view(0)],unit='vmul',shape=shape)
            bp=Node('vmul',[b.view(sl),rc.view(1)],unit='vmul',shape=shape)
            add=Node('vadd',[ap,bp],shape=shape)
            parts.append(Node('vrne16',[add,rc.view(2)],16,True,'vrne',shape))
        residual=self.join(self.graph(parts),16,True,'pipelined_residual_S16')
        total=self.reduction(residual,'reduce_sum',32)
        square_nodes=[Node('vmul',[residual.view(slice(i,min(i+self.lanes,64))),residual.view(slice(i,min(i+self.lanes,64)))],32,False,'vmul',(min(self.lanes,64-i),)) for i in range(0,64,self.lanes)]
        squares=self.join(self.graph(square_nodes),32,False,'pipelined_squares')
        sum_sq=self.reduction(squares,'reduce_sum',64,False);e.drop(squares)
        sq=e.issue('vmul',[total,total],64,True,'vmul')
        var=e.issue('ln_var',[sum_sq,sq],64,False,'valu',release=[sum_sq,sq])
        h=e.issue('ln_h',[var,eps],64,False,'valu',release=[var])
        root=e.issue('sqrt',[h],32,False,'sqrt',release=[h],advance=False)
        tag=e.allocate('LN_row_context_tag',8)
        pending=PendingNorm(residual,total,root,gamma,beta,m,s,tag)
        self.norm_rows.append(pending);self.norm_rows_peak=max(self.norm_rows_peak,len(self.norm_rows));e.step(1,'LN_sqrt_issued')
        return pending
    def finish_norm(self,row):
        e=self.e
        while row.division is None:self.norm_finish_wait+=1;e.step(1,'LN_wait_div_issue')
        div=row.division;self.norm_finish_wait+=max(0,div.ready-e.now)
        reciprocal=e.issue('round_qr',[div.view(0),div.view(1),row.root],32,False,'valu',release=[div,row.root])
        nodes=[]
        for i in range(0,64,self.lanes):
            sl=slice(i,min(i+self.lanes,64));shape=(sl.stop-sl.start,)
            centered=Node('vcenter',[row.residual.view(sl),row.total],32,True,'valu',shape)
            prod=Node('vmul',[centered,reciprocal],64,True,'vmul',shape)
            normalized=Node('vrne32',[prod,18],32,True,'vrne',shape)
            product=Node('vmul',[normalized,row.gamma.view(sl)],64,True,'vmul',shape)
            rounded=Node('vrne32',[product,14],32,True,'vrne',shape)
            affine=Node('vadd',[rounded,row.beta.view(sl)],32,True,'valu',shape)
            product=Node('vmul',[affine,row.m],64,True,'vmul',shape)
            nodes.append(Node('vrne8',[product,row.s],8,True,'vrne',shape))
        result=self.join(self.graph(nodes),8,True,'pipelined_LN_codes')
        for c in [row.residual,row.total,reciprocal]:e.drop(c)
        e.release(row.tag);self.norm_rows.remove(row)
        return result
    def write_pair(self,t,row,cells):
        if cells and isinstance(cells[0],PendingNorm):cells=[self.finish_norm(p) for p in cells]
        super().write_pair(t,row,cells)
    def summary(self):
        assert not self.norm_rows
        r=super().summary();r.update(LN_pending_rows_max=self.norm_rows_peak,LN_finish_wait_cycles=self.norm_finish_wait,
            arithmetic_latencies=self.e.lat,arithmetic_initiation_intervals=self.e.II,extra_arithmetic_units=0)
        return r
