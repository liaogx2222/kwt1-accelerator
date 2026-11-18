"""Cycle-exact elastic slots shared with RTL tests; one lane, separate resources.

Clock t is the edge BEFORE capture: req accepted at t is available at t+L.
mul L=3 II=1; RNE L=1 II=1; their chained RQ L=4 II=1. Backpressure
propagates through vacant slots. Reset flushes all slots; canceled tags never
respond. Divider64/sqrt32 are independent iterative resources, not II=1.
"""
MASK=(1<<64)-1
def signed(x):return x-(1<<64) if x&(1<<63) else x
def multiply(a,b,is_signed):
    aa,bb=(signed(a),signed(b)) if is_signed else (a,b)
    low,high=(-(1<<31),(1<<31)-1) if is_signed else (0,(1<<32)-1)
    if not low<=aa<=high or not low<=bb<=high:return 0,True
    return aa*bb&MASK,False
def rounding(a,shift,sat,error=False):
    x=signed(a);mag=abs(x)
    if error or x==-(1<<63) or sat not in (0,8,16):return 0,True
    if shift<0:q=mag<<-shift
    elif shift==0:q=mag
    else:
        q,r=divmod(mag,1<<shift);q+=int(r>(1<<shift)-r or (r==(1<<shift)-r and q&1))
    if shift<0 and q>(1<<63)-1:return 0,True
    if sat:q=min(q,(1<<(sat-1))-1)
    return (-q if x<0 else q)&MASK,False

class ElasticPipeline:
    def __init__(self,mode='rq'):
        self.mode=mode;self.depth={'mul':3,'rne':1,'rq':4}[mode];self.slots=[None]*self.depth
    def cycle(self,reset,request,ready):
        if reset:self.slots=[None]*self.depth;return False,None
        can=[False]*self.depth;can[-1]=self.slots[-1] is None or ready
        for i in range(self.depth-2,-1,-1):can[i]=self.slots[i] is None or can[i+1]
        output=self.slots[-1]
        old=self.slots[:]
        for i in range(self.depth-1,-1,-1):
            if can[i]:self.slots[i]=request if i==0 else old[i-1]
        return can[0],output

# Register reservation includes every physical slot, including vacancies.
# mul: 4 partial products + combined + result + 3*(tag14+sign/error/valid);
# RNE: result+tag+error+valid. Shifts/saturation metadata included in tag14.
PIPELINE_STORAGE_BITS=128+64+64+3*(16+14+3)+64+16+2
PIPELINE_STORAGE_BYTES=(PIPELINE_STORAGE_BITS+7)//8
# Conservatively reserve ALL legacy iterative datapath/response registers,
# even though only div/sqrt operations are connected by the layer controller.
ITERATIVE_STORAGE_BITS=64+128+(3*64+65)+(2*64+66)+7+2+2
ITERATIVE_STORAGE_BYTES=(ITERATIVE_STORAGE_BITS+7)//8
