"""R2: actual canonical packets -> bounded ready/valid FIFO -> 20 SRAMs.

Online: header/version/profile/order/length, canonical layout fields, fixed
body CRC, rolling header/body CRC. SHA and logical hashes are host-only.
One profile template (38x64 bytes + common64) and 13 CRC32s + profile32
require 2580B trusted metadata ROM; no full packet or descriptor directory
is buffered. Payload can write before CRC succeeds, but START stays invalid.
"""
import collections
import gzip
import json
import math
import struct
import zlib
import numpy as np
from .hw_abi import HEADER,ENTRY


class PacketStream:
    def __init__(self,banks,packets,params,trace=None,capacity=8):
        self.b=banks;self.p=params;self.packets=packets;self.capacity=capacity
        self.trace=gzip.open(trace,'wt',encoding='utf-8',compresslevel=2) if trace else None
        self.busy=False;self.common_valid=False;self.layer_valid=False;self.input_valid=False;self.next_layer=0
        self.fifo=collections.deque();self.high_water=0;self.state='idle';self.error=None;self.stats=[];self.wbase={};off=0
        for name in ['q','k','v','o','fc1','fc2']:
            k,n=params['l00_'+name+'_w'].shape;self.wbase[name]=off;off+=k*(n//8)
        self.cbase={};off=0
        for name in sorted(params):
            if not name.startswith('l00_') or name.endswith(('_w','_gelu_lut','_q_b','_k_b','_v_b')):continue
            self.cbase[name[4:]]=off;off+=params[name].nbytes//4
        self.constant_ROM_bytes=38*64+64+13*4+32
        self.accepted=0;self.rejected=0;self.epoch=-1
        self.reset()
    def log(self,row):
        if self.trace:self.trace.write(json.dumps(row,separators=(',',':'))+'\n')
    def begin(self,name):
        if self.busy:raise RuntimeError('busy: cannot overwrite active parameters')
        if self.state not in ['idle','done','error']:raise RuntimeError('frame still active')
        layer=None if name=='common.bin' else int(name[6:8])
        if layer is not None and layer!=self.next_layer:raise RuntimeError('layer order mismatch')
        if self.task_done:raise RuntimeError('cold task requires reset')
        self.name=name;self.expected=self.packets[name]
        h=HEADER.unpack(self.expected[:64]);self.header_fields=h;self.directory_bytes=h[5]
        self.payload_base=64+h[5];self.layer=None if name=='common.bin' else int(name[6:8])
        if self.layer is None:
            if self.next_layer!=0:raise RuntimeError('common reload out of task order')
            self.common_valid=False
        else:
            if self.layer!=self.next_layer:raise RuntimeError('layer order mismatch')
            self.layer_valid=False
        self.state='header';self.error=None;self.fifo.clear();self.position=0;self.header=bytearray();self.crc=0;self.last_seen=False
        self.descriptors=[]
        for i in range(h[4]):
            fields=ENTRY.unpack(self.expected[64+i*128:64+(i+1)*128]);name0=fields[0].rstrip(b'\0').decode()
            self.descriptors.append({'name':name0,'offset':fields[8],'length':fields[9],'shape':tuple(fields[5:5+fields[2]])})
        self.frame_start=self.b.cycle;self.frame_accept=0;self.frame_stall=0;self.frame_source_idle=0;self.frame_writes=0
    def fail(self,reason):
        self.error=reason;self.state='error';self.layer_valid=False
        if self.layer is None:self.common_valid=False
        self.fifo.clear();self.rejected+=1
    def payload_ops(self,offset,data):
        descriptor=next((r for r in self.descriptors if r['offset']<=offset<r['offset']+r['length']),None)
        if descriptor is None:
            if any(data):self.fail('nonzero alignment padding')
            return []
        pos=offset-descriptor['offset'];name=descriptor['name'];ops=[]
        if pos+4>descriptor['length']:raise RuntimeError('noncanonical array tail')
        if name.endswith('_w'):
            k,n=descriptor['shape'];perbank=k*n//4;bank=pos//perbank
            for j in [0,2]:ops.append((f'W{bank}',self.wbase[name[4:-2]]+(pos%perbank+j)//2,'w',int.from_bytes(data[j:j+2],'little')))
        elif name=='exp_lut':
            word=pos//4;value=int.from_bytes(data,'little');ops=[('E0',word,'w',value&65535),('E1',word,'w',value>>16)]
        elif name.endswith('_gelu_lut'):
            for j in [0,2]:ops.append(('C0',1880+(pos+j)//2,'w',int.from_bytes(data[j:j+2],'little')))
        else:
            word=self.cbase[name[4:]]+pos//4;value=int.from_bytes(data,'little');ops=[('C0',word,'w',value&65535),('C1',word,'w',value>>16)]
        return ops
    def process(self,data,last):
        pos=self.position;self.position+=4
        if pos<64:
            self.header.extend(data)
            if len(self.header)==64:
                try:h=HEADER.unpack(self.header)
                except struct.error:self.fail('header length');return
                if bytes(self.header[:56])!=self.expected[:56] or h[8]!=self.header_fields[8]:self.fail('header/profile/version/length');return
                if zlib.crc32(self.header[:60])!=h[9]:self.fail('header CRC');return
                self.state='directory'
        else:
            self.crc=zlib.crc32(data,self.crc)
            if pos<self.payload_base:
                local=(pos-64)%128
                # Per-array data CRC/SHA fields 64:100 are host-only. Rolling
                # body CRC still covers every byte and is fixed by the profile.
                if local<64 or local>=100:
                    if data!=self.expected[pos:pos+4]:self.fail('noncanonical descriptor');return
            else:
                self.state='payload';ops=self.payload_ops(pos-self.payload_base,data)
                if self.error:return
                self.fifo.extend(ops);self.high_water=max(self.high_water,len(self.fifo))
                if len(self.fifo)>self.capacity:raise RuntimeError('FIFO overflow')
        if last!=(self.position==len(self.expected)):
            if last or self.position>=len(self.expected):self.fail('TLAST/packet length');return
        if last:self.last_seen=True
    def beat(self,valid=False,word=0,last=False,write_allow=True):
        epoch=self.epoch;cycle=self.b.cycle;ready=(not self.busy and not self.last_seen and self.state in ['header','directory','payload'] and len(self.fifo)<=self.capacity-2)
        ops=[];remaining=collections.deque();used=set()
        while self.fifo:
            op=self.fifo.popleft()
            if write_allow and op[0] not in used:ops.append(op);used.add(op[0])
            else:remaining.append(op)
        self.fifo=remaining
        accepted=bool(valid and ready)
        self.b.stage='packet_'+getattr(self,'name','idle');self.b.tick(ops,tag='stream_bank_write')
        if self.epoch!=epoch:return False,False
        if hasattr(self,'frame_writes'):self.frame_writes+=len(ops)
        if valid and not ready:self.frame_stall+=1
        if not valid and self.state in ['header','directory','payload']:self.frame_source_idle+=1
        if accepted:
            self.frame_accept+=1;self.accepted+=1;self.process(int(word).to_bytes(4,'little'),last)
        if self.state in ['header','directory','payload'] and self.last_seen and not self.fifo and not self.error and self.position==len(self.expected):
            if self.crc!=self.header_fields[8]:self.fail('body CRC')
            else:
                self.state='done'
                if self.layer is None:self.common_valid=True
                else:self.layer_valid=True
        self.log({'cycle':cycle,'kind':'packet','valid':valid,'ready':ready,'word':int(word) if valid else None,'last':last,
            'accepted':accepted,'pending_writes':len(self.fifo),'writes':ops,'state':self.state,'error':self.error,'crc':self.crc})
        return ready,accepted
    def transfer(self,name,packet=None,source_gap=0,write_gap=0,beat_interval=1):
        self.begin(name);data=self.packets[name] if packet is None else packet
        epoch=self.epoch
        if len(data)%4:raise ValueError('32-bit stream requires aligned byte count')
        words=[int.from_bytes(data[i:i+4],'little') for i in range(0,len(data),4)];index=0;holding=False;guard=0;previous=None
        next_offer=self.b.cycle
        while self.state not in ['done','error']:
            t=self.b.cycle;enabled=t>=next_offer and (not source_gap or (t%source_gap!=source_gap-1))
            if index<len(words) and (holding or enabled):valid=True;word=words[index];last=index==len(words)-1
            else:valid=False;word=0;last=False
            if previous is not None:assert valid and (word,last)==previous,'source changed while stalled'
            _,accepted=self.beat(valid,word,last,not write_gap or t%write_gap not in [0,1])
            if self.epoch!=epoch:raise RuntimeError('packet aborted by reset')
            holding=valid and not accepted;previous=(word,last) if holding else None
            if accepted:index+=1;next_offer=self.b.cycle+beat_interval-1
            guard+=1
            if guard>max(1000,len(words)*max(20,beat_interval*3)):raise RuntimeError('stream watchdog')
        row={'packet':name,'bytes':len(data),'cycles':self.b.cycle-self.frame_start,'accepted_beats':self.frame_accept,
             'backpressure_cycles':self.frame_stall,'source_idle_cycles':self.frame_source_idle,'bank_writes':self.frame_writes,
             'CRC_valid':self.error is None,'error':self.error,'FIFO_peak_entries':self.high_water}
        self.stats.append(row);return row
    def can_start(self,layer):return not self.busy and self.common_valid and self.layer_valid and self.input_valid and layer==self.next_layer and self.layer==layer
    def start(self,layer):
        if not self.can_start(layer):raise RuntimeError('START refused: invalid/order/busy')
        self.busy=True
    def finish_layer(self):
        if not self.busy:raise RuntimeError('not busy')
        self.busy=False;self.layer_valid=False;self.next_layer+=1
    def load_input(self,array,sink_gap=0,beat_interval=1):
        if self.busy or self.next_layer!=0:raise RuntimeError('input overwrite while active task')
        if array.shape!=(99,64) or array.dtype!=np.int8 or np.any(array==-128):raise ValueError('input requires (99,64) signed symmetric int8')
        if beat_interval<1:raise ValueError('beat_interval')
        self.input_valid=False;epoch=self.epoch;next_offer=self.b.cycle
        data=array.astype(np.int8).tobytes();received=bytearray();start=self.b.cycle;accepted=stalls=0
        # A 128B pair buffer avoids unsupported byte writes/RMW. Fill and drain
        # are serialized; all producer stalls while draining are charged.
        for token in range(0,99,2):
            pair=data[token*64:min(token+2,99)*64]
            for j in range(0,len(pair),4):
                if self.epoch!=epoch:raise RuntimeError('input aborted by reset')
                while self.b.cycle<next_offer:self.b.tick(tag='input_link_interval')
                while sink_gap and self.b.cycle%sink_gap==0:self.b.tick(tag='input_producer_gap');stalls+=1
                word=pair[j:j+4];received.extend(word);accepted+=1
                self.b.tick(tag='input_pair_accept');self.log({'cycle':self.b.cycle-1,'kind':'input','valid':True,'ready':True,'word':word.hex()})
                next_offer=self.b.cycle+beat_interval-1
            for ch in range(64):
                if self.epoch!=epoch:raise RuntimeError('input aborted by reset')
                lo=pair[ch];hi=pair[64+ch] if len(pair)>64 else 0
                bank=(token%8)//2;addr=(token//8)*64+ch
                self.b.tick([(f'A{bank}',addr,'w',lo|(hi<<8))],tag='input_pair_bank_drain');stalls+=1
                next_offset=min(token+2,99)*64
                pending=data[next_offset:next_offset+4]
                self.log({'cycle':self.b.cycle-1,'kind':'input','valid':bool(pending),'ready':False,'word':pending.hex() if pending else None,'reason':'pair_drain'})
        if self.epoch!=epoch:raise RuntimeError('input aborted by reset')
        assert received==data;self.input_valid=True
        return {'bytes':len(data),'accepted_beats':accepted,'cycles':self.b.cycle-start,'backpressure_cycles':stalls,'pair_buffer_bytes':128}
    def writeback(self,sink_gap=0,base=832,beat_interval=1):
        if self.busy or self.next_layer!=12 or self.task_done:raise RuntimeError('final output before all layers complete or already consumed')
        epoch=self.epoch;next_accept=self.b.cycle
        start=self.b.cycle;output=bytearray();holding=None;stalls=0
        for token in range(99):
            for col in range(0,64,4):
                if self.epoch!=epoch:raise RuntimeError('output aborted by reset')
                lane=[]
                for ch in range(col,col+4):
                    bank=(token%8)//2;addr=base+(token//8)*64+ch
                    word=self.b.tick([(f'A{bank}',addr,'r',0)],tag='output_gather')[0];lane.append((word>>(8*(token%2)))&255)
                holding=bytes(lane)
                while self.b.cycle<next_accept:self.b.tick(tag='output_link_interval')
                while sink_gap and self.b.cycle%sink_gap in [0,1]:
                    self.b.tick(tag='output_sink_stall');stalls+=1
                    self.log({'cycle':self.b.cycle-1,'kind':'output','valid':True,'ready':False,'word':holding.hex()})
                self.b.tick(tag='output_accept');output.extend(holding)
                next_accept=self.b.cycle+beat_interval-1
                self.log({'cycle':self.b.cycle-1,'kind':'output','valid':True,'ready':True,'word':holding.hex()})
        if self.epoch!=epoch:raise RuntimeError('output aborted by reset')
        self.task_done=True
        return bytes(output),{'bytes':len(output),'cycles':self.b.cycle-start,'sink_stalls':stalls,'holding_register_bytes':4}
    def reset(self):
        # Task reset cancels ownership and buffered writes, not SRAM contents.
        # Clear every completion predicate before any subsequent idle beat.
        self.epoch+=1;self.fifo.clear();self.busy=False
        self.b.task_epoch=self.epoch
        self.common_valid=self.layer_valid=self.input_valid=False
        self.next_layer=0;self.state='idle';self.error=None;self.task_done=False
        self.b.a_swap=False;self.layer=None;self.name='idle';self.expected=b''
        self.last_seen=False;self.position=0;self.crc=0;self.header=bytearray()
        self.header_fields=None;self.descriptors=[];self.directory_bytes=0;self.payload_base=0
        self.frame_start=self.b.cycle;self.frame_accept=self.frame_stall=self.frame_source_idle=self.frame_writes=0
    def close(self):
        if self.trace:self.trace.close()
