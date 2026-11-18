"""Serialized, parameterized system window: host -> CPU -> device and return.

All three links use 32-bit beats at 150MHz; external endpoints and CPU are
latency models, device-side data/CRC/SRAM handshakes are executable. No overlap
is credited. Input and output follow exactly the same three-link path as params.
"""
class SystemIO:
    def __init__(self,stream,MBps=100):
        if MBps not in (25,50,100,200,600):raise ValueError('unsupported bandwidth')
        self.s=stream;self.b=stream.b;self.interval=600//MBps;self.MBps=MBps
        self.ledger=[];self.origin=self.b.cycle
        self.epoch=stream.epoch
    def check(self):
        if self.epoch!=self.s.epoch:raise RuntimeError('system I/O aborted by task reset')
    def external(self,kind,nbytes):
        self.check()
        assert nbytes%4==0
        segments=[('host_cpu_link',nbytes//4*self.interval),('CPU_copy',nbytes//4*4+500),('cpu_device_link',nbytes//4*self.interval)]
        if kind=='output':segments.reverse()
        for segment,cycles in segments:
            start=self.b.cycle;self.b.idle(cycles,kind+'_'+segment)
            self.check()
            self.ledger.append(dict(kind=kind,segment=segment,bytes=nbytes,start=start,end=self.b.cycle,cycles=cycles,modeled=True))
    def local(self,kind,nbytes,fn):
        self.check();start=self.b.cycle;result=fn();self.check()
        self.ledger.append(dict(kind=kind,segment='device_stream',bytes=nbytes,start=start,end=self.b.cycle,cycles=self.b.cycle-start,modeled=False))
        return result
    def packet(self,name):
        n=len(self.s.packets[name]);self.external(name,n)
        return self.local(name,n,lambda:self.s.transfer(name,write_gap=11,beat_interval=self.interval))
    def input(self,array):
        self.external('input',array.nbytes)
        return self.local('input',array.nbytes,lambda:self.s.load_input(array,sink_gap=7,beat_interval=self.interval))
    def output(self):
        result=self.local('output',6336,lambda:self.s.writeback(sink_gap=7,beat_interval=self.interval))
        self.external('output',len(result[0]))
        self.check();start=self.b.cycle;self.b.idle(1,'final_host_write_ack');self.check()
        self.ledger.append(dict(kind='output',segment='final_write_ack',bytes=0,start=start,end=self.b.cycle,cycles=1,modeled=True))
        return result
    def summary(self):
        return dict(MBps=self.MBps,clock_MHz_assumed=150,io_path='host <-> CPU staging <-> device staging <-> SRAM stream; serialized',
                    CPU_cycles_per_word=4,CPU_cycles_per_frame=500,ledger=self.ledger,
                    io_cycles=sum(r['cycles'] for r in self.ledger),window_cycles=self.b.cycle-self.origin,
                    external_is_model=True,final_ack_included=bool(self.ledger and self.ledger[-1]['segment']=='final_write_ack'))
