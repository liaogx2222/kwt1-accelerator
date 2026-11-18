"""Real 13 packet stream, all layer transitions and final output handshake."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integer_model.execution_banks import ExecutionBanks
from integer_model.packet_stream import PacketStream
from integer_model.executable_layer import ExecutableLayer
from integer_model.hw_abi import unpack
from integer_model.runtime import Encoder
from integer_model.register_contract import budget


def artifacts():
    root=ROOT/'testdata/p4a/hw_params_verified';m=json.loads((root/'manifest.json').read_text())
    packets={r['file']:(root/r['file']).read_bytes() for r in m['packets']}
    p={}
    for name,data in packets.items():p.update(unpack(data,m['profile_sha256'],m['schema'],None if name=='common.bin' else int(name[6:8])))
    return packets,p


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,default=ROOT/'testdata/r1r2/r2')
    ap.add_argument('--execute',action='store_true');ap.add_argument('--sample',type=int,default=187)
    ap.add_argument('--execution-only',action='store_true');ap.add_argument('--optimized',action='store_true')
    ap.add_argument('--MBps',type=int,choices=[25,50,100,200,600],default=100)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True);packets,p=artifacts()
    scenarios=[]
    for bandwidth in ([] if a.execution_only else [25,50,100,200,600]):
        banks=ExecutionBanks();stream=PacketStream(banks,packets,p,trace=a.output/f'stream_{bandwidth}.gz')
        interval=600//bandwidth
        for name in ['common.bin']+[f'layer_{i:02d}.bin' for i in range(12)]:
            if name!='common.bin':stream.next_layer=int(name[6:8])
            stream.transfer(name,beat_interval=interval,write_gap=11)
        # Per-packet service: no aggregate max can borrow slack from other layers.
        result={'MBps':bandwidth,'packets':stream.stats,'third_segment_cycles':banks.cycle,
            'two_other_segments_cycles':sum(2*((len(data)//4)*interval) for data in packets.values()),
            'CPU_housekeeping_cycles':sum((len(data)//4)*4+500 for data in packets.values()),
            'metadata_ROM_bytes':stream.constant_ROM_bytes,'FIFO_peak_entries':stream.high_water}
        result['serialized_parameter_cycles']=result['third_segment_cycles']+result['two_other_segments_cycles']+result['CPU_housekeeping_cycles']
        stream.close();scenarios.append(result);print('stream',bandwidth,banks.cycle,flush=True)
    banks=ExecutionBanks();stream=PacketStream(banks,packets,p,trace=a.output/'errors.gz');tests={}
    stream.transfer('common.bin');good=packets['layer_00.bin']
    cases={'body_bitflip':good[:-1]+bytes([good[-1]^1]),'truncated':good[:-4],
           'trailing':good+b'\0\0\0\0','header_corrupt':b'X'+good[1:],
           'descriptor_layout':good[:105]+bytes([good[105]^1])+good[106:]}
    for label,packet in cases.items():
        result=stream.transfer('layer_00.bin',packet,source_gap=7,write_gap=11);assert result['error'] and not stream.can_start(0)
        tests[label]=result['error']
    stream.transfer('layer_00.bin',source_gap=7,write_gap=11);stream.input_valid=True;stream.start(0)
    before={k:v.copy() for k,v in banks.mem.items()}
    try:stream.begin('layer_01.bin')
    except RuntimeError:tests['busy_active_overwrite']='rejected'
    else:raise AssertionError('busy overwrite')
    assert all(np.array_equal(before[k],v) for k,v in banks.mem.items())
    stream.reset();assert not stream.can_start(0)
    tests['reset_invalidates_slots']='passed'
    try:stream.begin('layer_01.bin')
    except RuntimeError:tests['wrong_layer_sequence']='rejected'
    else:raise AssertionError('layer order')
    stream.close();execution=None
    if a.execute:
        meta=json.loads((ROOT/'testdata/integer_v1/params/manifest.json').read_text());x=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r')[a.sample:a.sample+1]
        q=np.clip(np.rint(x.astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
        taps={}
        Encoder(p,lambda n,v,c:taps.update({n:v[0].copy()}) if n.count('/')==1 else None)(q)
        banks=ExecutionBanks(a.output/'execution_banks.gz');stream=PacketStream(banks,packets,p,a.output/'execution_stream.gz')
        external_cycles=0
        def transfer_at_bandwidth(name):
            nonlocal external_cycles
            words=len(packets[name])//4;delay=2*words*(600//a.MBps)+4*words+500
            banks.idle(delay,'modeled_two_external_segments_and_CPU');external_cycles+=delay
            return stream.transfer(name,write_gap=11,beat_interval=600//a.MBps)
        transfer_at_bandwidth('common.bin')
        input_stat=stream.load_input(q[0],sink_gap=7);layer_stats=[];current=q[0]
        for i in range(12):
            banks.a_swap=bool(a.optimized and i%2)
            transfer=transfer_at_bandwidth(f'layer_{i:02d}.bin')
            stream.start(i);begin=banks.cycle
            before_stages=dict(banks.stage_cycles)
            expected={n.split('/')[1]:v for n,v in taps.items() if n.startswith(f'layer_{i:02d}/')}
            model=ExecutableLayer(p,a.output/f'unused_{i}.gz',i,banks=banks,preloaded=True,
                coefficient_cache=a.optimized,gelu_ports=8 if a.optimized else 1,pingpong=a.optimized)
            current=model.run(current,expected);stream.finish_layer()
            layer_stats.append({'layer':i,'transfer':transfer,'compute_and_handoff_cycles':banks.cycle-begin,'register_peak_bytes':model.measured['peak_bytes'],'mismatches':0})
            layer_stats[-1]['register_budget']=budget(model.measured)
            layer_stats[-1]['coefficient_read_bytes']=model.coefficient_reads
            layer_stats[-1]['handoff_cycles']=model.handoff_cycles
            layer_stats[-1]['stage_cycles']={stage:sum(n-before_stages.get((s,tag),0) for (s,tag),n in banks.stage_cycles.items() if s==stage) for stage in set(s for s,t in banks.stage_cycles)}
            print('R2 execute layer',i,'cycle',banks.cycle,flush=True)
        output,output_stat=stream.writeback(sink_gap=7)
        assert output==current.astype(np.int8).tobytes()
        golden=np.load(ROOT/'testdata/integer_v1/validation/encoder_output_int8.npy',mmap_mode='r')[a.sample]
        assert output==golden.tobytes()
        execution={'optimized':a.optimized,'MBps':a.MBps,'external_pipeline_modeled_cycles':external_cycles,
            'layers':layer_stats,'input':input_stat,'output':output_stat,'total_cycles':banks.cycle,
            'latency_ms_at_assumed_150MHz':banks.cycle/150000,'output_sha256':hashlib.sha256(output).hexdigest(),'saved_golden_equal':True}
        np.save(a.output/'output.npy',np.frombuffer(output,np.int8).reshape(99,64));stream.close();banks.trace.close()
    result={'online_subset':'fixed profile header/layout/length/order and rolling CRC32; SHA offline only',
        'source_packets':13,'scenarios':scenarios,'negative_tests':tests,'execution':execution,
        'metadata_ROM_bytes':2580,'write_FIFO_capacity':8,'input_pair_buffer_bytes':128,'host_offline_493_arrays_verified':True}
    (a.output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')


if __name__=='__main__':main()
