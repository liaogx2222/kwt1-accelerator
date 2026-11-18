"""Two-row Softmax staging with unchanged arithmetic resources and formulas.

Prepare both rows before completing either: the shared 64-cycle divider can
retire while the other row's frontend or correction arithmetic executes.
Each pending row holds explicit exponent/denominator/div-result Cells.
"""
import numpy as np
from .competitive_fused_rows import FusedRowsCore
from .competitive_nonlinear import Node


class PendingRow:
    def __init__(self,exponent,denominator,division):
        self.exponent,self.denominator,self.division=exponent,denominator,division


class WindowRowsCore(FusedRowsCore):
    def __init__(self,*a,window=16,**k):
        assert window in [16,32,64,128];self.window=window
        super().__init__(*a,**k);self.pending_rows=0;self.max_pending_rows=0;self.finish_div_wait=0
    def softmax_row(self,score,m,s):
        assert self.pending_rows<2,'bounded two-row context capacity'
        e=self.e;maximum=self.reduction(score,'reduce_max',32);indices=[]
        for begin in range(0,99,self.window):
            nodes=[]
            for i in range(begin,min(begin+self.window,99),self.lanes):
                sl=slice(i,min(i+self.lanes,99));shape=(sl.stop-sl.start,)
                diff=Node('vsub',[score.view(sl),maximum],32,True,'valu',shape)
                product=Node('vmul',[diff,m],64,True,'vmul',shape)
                rounded=Node('vrne32',[product,s],32,True,'vrne',shape)
                nodes.append(Node('vexpindex',[rounded],16,False,'valu',shape))
            indices.extend(self.graph(nodes))
        index=self.join(indices,16,False,'pipelined_Softmax_index');e.drop(maximum)
        ix=np.asarray(e.consume(index),np.int64);exps=[]
        allocation=e.allocate('pipelined_Softmax_exponents',99*4)
        for begin in range(0,99,self.lanes):
            locations=[];meta=[]
            for value in ix[begin:begin+self.lanes]:
                value=int(value)
                if value in [0,4096]:meta.append(('constant',1<<20 if value==0 else 0));continue
                width=self.widths[value//256]
                if not width:meta.append(('constant',0));continue
                bit=self.offsets[value//256]+(value%256)*width;word=bit//16;shift=bit%16;keys=[]
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
        exponent=e.source(np.array(exps,np.int64),32,False,name='pipelined_Softmax_exps',allocation=allocation);e.drop(index)
        denominator=self.reduction(exponent,'reduce_sum',32,False)
        division=e.issue('divmod',[1<<47,denominator],64,False,'div',(2,))
        self.pending_rows+=1;self.max_pending_rows=max(self.max_pending_rows,self.pending_rows)
        return PendingRow(exponent,denominator,division)
    def finish_row(self,pending):
        e=self.e;exponent,denominator,div=pending.exponent,pending.denominator,pending.division
        self.finish_div_wait+=max(0,div.ready-e.now)
        reciprocal=e.issue('ceil_qr',[div.view(0),div.view(1)],32,False,'valu',release=[div]);results=[]
        for begin in range(0,99,self.window):
            nodes=[]
            for i in range(begin,min(begin+self.window,99),self.lanes):
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
        result=self.join(results,16,False,'pipelined_probabilities')
        for c in [exponent,denominator,reciprocal]:e.drop(c)
        self.pending_rows-=1;return result
    def write_pair(self,t,row,cells):
        if cells and isinstance(cells[0],PendingRow):cells=[self.finish_row(p) for p in cells]
        super().write_pair(t,row,cells)
    def summary(self):
        assert self.pending_rows==0
        r=super().summary();r.update(Softmax_pending_rows_max=self.max_pending_rows,
            Softmax_finish_div_wait_cycles=self.finish_div_wait,arithmetic_latencies=self.e.lat,
            arithmetic_initiation_intervals=self.e.II,extra_arithmetic_units=0)
        r["Softmax_graph_window"]=self.window
        return r

    def reset(self):
        config=self.config;buffers=self.accumulator_buffers;fusion=self.fusion;window=self.window
        self.__init__(*config,accumulator_buffers=buffers,fusion=fusion,window=window)
