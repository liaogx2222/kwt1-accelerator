"""Five-bandwidth data transport and byte/cycle ledger regression."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from validate_kwt1_r2 import artifacts
from integer_model.execution_banks import ExecutionBanks
from integer_model.packet_stream import PacketStream
from integer_model.system_io import SystemIO
from integer_model.bank_model import address

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--quick',action='store_true');a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    packets,p=artifacts();rows=[];x=((np.arange(6336)%255)-127).astype(np.int8).reshape(99,64)
    for bandwidth in [25,50,100,200,600]:
        b=ExecutionBanks();s=PacketStream(b,packets,p);io=SystemIO(s,bandwidth)
        for name in ['common.bin']+[f'layer_{i:02d}.bin' for i in range(12)]:
            if name!='common.bin':s.next_layer=int(name[6:8])
            result=io.packet(name);assert result['CRC_valid']
        # This is a transport test, no compute is asserted. Fill output SRAM via
        # timed writes, independently of input loading, and check actual bytes.
        s.next_layer=0;input_stat=io.input(x)
        for t in range(0,99,2):
            for c in range(64):
                bank,addr,byte=address('token',832,t,c,64);hi=int(x[t+1,c])&255 if t+1<99 else 0
                b.tick([(f'A{bank}',addr,'w',(int(x[t,c])&255)|(hi<<8))],tag='test_only_output_fixture')
        s.next_layer=12;output,stat=io.output();assert output==x.tobytes()
        ledger=io.summary();counts={}
        for r in ledger['ledger']:counts[r['segment']]=counts.get(r['segment'],0)+r['bytes']
        assert all(counts[k]==757312+2*6336 for k in ['host_cpu_link','CPU_copy','cpu_device_link','device_stream'])
        # Serial segments each charge all beats, not a maximum over packets.
        interval=600//bandwidth
        for r in ledger['ledger']:
            if r['segment'] in ['host_cpu_link','cpu_device_link']:assert r['cycles']==r['bytes']//4*interval
            if r['segment']=='CPU_copy':assert r['cycles']==r['bytes']//4*4+500
        assert input_stat['cycles']>=1584*interval
        rows.append(dict(MBps=bandwidth,input=input_stat,output=stat,io=ledger,per_segment_bytes=counts,output_sha256=hashlib.sha256(output).hexdigest()))
        print('IO',bandwidth,input_stat['cycles'],stat['cycles'],flush=True)
    (a.output/'system_io.json').write_text(json.dumps(dict(passed=True,scenarios=rows,transport_only=True),indent=2),encoding='utf-8')
if __name__=='__main__':main()
