"""Channel-hashed SP scratch mapping; Dense token vectors stay conflict-bounded.

Rotating the physical bank by channel mod4 also permits four channels of a
row pair to be read together. Compact tails avoid allocating 104 rows for N99.
"""
import math
from .competitive_tile16 import Scratch,Tensor
from .competitive_tile16_pipeline import PipelinedTile16


class HashedTensor(Tensor):
    def word(self,row,col,plane=0):
        if not self.valid:raise RuntimeError('scratch use after free')
        if not 0<=row<self.rows or not 0<=col<self.cols or not 0<=plane<self.bits//8:raise ValueError('tensor bounds')
        logical=(row%8)//2;physical=(logical+col%4)%4
        full=self.rows//8;pairs=(self.rows%8+1)//2
        if row//8<full:offset=(row//8)*self.cols+col
        else:
            rank=sum(((physical-ci)%4)<pairs for ci in range(col%4))
            offset=full*self.cols+(col//4)*pairs+rank
        return f'S{physical}',self.bases[physical]+plane*self.strides[physical]+offset


class HashedScratch(Scratch):
    def allocate(self,name,rows,cols,bits=8,signed=True):
        assert bits in [8,16,32]
        full=rows//8;pairs=(rows%8+1)//2
        strides=[full*cols+(cols//4)*pairs+sum(((bank-ci)%4)<pairs for ci in range(cols%4)) for bank in range(4)]
        sizes=[stride*(bits//8) for stride in strides];bases=[]
        for bank,size in enumerate(sizes):
            found=next(((a,b) for a,b in self.free[bank] if b-a>=size),None)
            if found is None:raise MemoryError(f'hashed scratch cannot allocate {name}')
            bases.append(found[0])
        for bank,(base,size) in enumerate(zip(bases,sizes)):
            if not size:continue
            interval=next((a,b) for a,b in self.free[bank] if a==base and b-a>=size)
            self.free[bank].remove(interval)
            if base+size<interval[1]:self.free[bank].append((base+size,interval[1]))
        tensor=HashedTensor(self,name,rows,cols,bits,signed,0,bases,[0]*4,sizes);tensor.strides=strides
        self.live.append(tensor)
        active=[sum(t.sizes[b] for t in self.live)*2 for b in range(4)]
        self.peak=max(self.peak,sum(active));self.bank_peak=[max(a,b) for a,b in zip(self.bank_peak,active)]
        return tensor


class HashedPipelinedTile16(PipelinedTile16):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.lanes>8:raise ValueError('4 SP scratch banks accept at most 8 S8 results/cycle')
        self.s=HashedScratch(self.b)
    def run(self,*args,**kwargs):
        values,report=super().run(*args,**kwargs)
        report['scratch_mapping']='token pair + channel mod4 bank hash, compact N99 tail'
        return values,report
