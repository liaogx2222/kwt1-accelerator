"""Single-port SRAM clock; records requests, compresses idle spans implicitly."""
import collections
import gzip
import json
import numpy as np


class NullWriter:
    def write(self,x):pass
    def close(self):pass


class ExecutionBanks:
    def __init__(self,path=None):
        self.mem={**{f'W{i}':np.full(8192,0xA5A5,np.uint16) for i in range(4)},
            **{f'{g}{i}':np.full(4096,0xA5A5,np.uint16) for g,n in [('A',4),('B',4),('C',2),('E',2)] for i in range(n)}}
        self.cycle=0;self.stage='init';self.counts=collections.Counter();self.stage_cycles=collections.Counter();self.max_bytes=0
        self.trace=gzip.open(path,'wt',encoding='utf-8',compresslevel=2) if path else NullWriter()
        self.enabled=bool(path);self.a_swap=False
    def physical_address(self,bank,address):
        if self.a_swap and bank.startswith('A') and address<1664:
            return address+832 if address<832 else address-832
        return address
    def peek_word(self,bank,address):return int(self.mem[bank][self.physical_address(bank,address)])
    def tick(self,ops=(),tag='',issue=None):
        used=set();read=[]
        for bank,address,mode,value in ops:
            address=self.physical_address(bank,address)
            if bank in used:raise ValueError('single-port conflict')
            used.add(bank)
            if bank not in self.mem or not 0<=address<len(self.mem[bank]):raise ValueError('out-of-bounds SRAM')
            if mode=='r':read.append(int(self.mem[bank][address]))
            elif mode=='w':
                if not 0<=int(value)<65536:raise OverflowError('16-bit SRAM word')
                self.mem[bank][address]=value
            else:raise ValueError(mode)
            self.counts[(bank,mode)]+=1
        if self.enabled and ops:self.trace.write(json.dumps({'cycle':self.cycle,'stage':self.stage,'tag':tag,'A_slot_swap':self.a_swap,'ports':ops,'physical_ports':[(b,self.physical_address(b,a),m,v) for b,a,m,v in ops],'read_next':read},separators=(',',':'))+'\n')
        self.max_bytes=max(self.max_bytes,2*len(ops));self.stage_cycles[(self.stage,tag)]+=1;self.cycle+=1
        return read
    def idle(self,n,tag='idle'):
        if n<0:raise ValueError(n)
        self.stage_cycles[(self.stage,tag)]+=n;self.cycle+=n
