"""P4b bank/data schedule and conditional full-window cycle accounting."""
import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from integer_model.bank_model import LayerModel
from integer_model.hw_abi import unpack
from integer_model.runtime import Encoder
from integer_model.export import sha


def csv_out(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows(rows)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=ROOT/'testdata/p4b/banks_v3')
    ap.add_argument('--sample',type=int,default=187)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if (a.output/'cycle_model.json').exists():raise FileExistsError('Preserve schedule evidence')
    base=ROOT/'testdata/integer_v1';hw=ROOT/'testdata/p4a/hw_params'
    meta=json.loads((base/'params/manifest.json').read_text());abi=json.loads((hw/'manifest.json').read_text())
    p={}
    for layer in [None]+list(range(12)):
        file='common.bin' if layer is None else f'layer_{layer:02d}.bin'
        p.update(unpack((hw/file).read_bytes(),abi['profile_sha256'],meta['array_schema'],layer))
    inp=np.load(base/'fixture/encoder_input.npy',mmap_mode='r')[a.sample:a.sample+1]
    q=np.clip(np.rint(inp.astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
    expected={}
    def capture(name,x,clip):
        if name.startswith('layer_00/') and name.count('/')==1:expected[name.split('/')[1]]=x[0].copy()
    entire=Encoder(p,capture)(q)
    gold=np.load(base/'validation/encoder_output_int8.npy',mmap_mode='r')
    assert np.array_equal(entire[0],gold[a.sample])
    model=LayerModel(p,a.output/'bank_trace.jsonl.gz')
    out=model.run(q[0],expected);np.save(a.output/'layer_00_output.npy',out)
    b=model.b;core=b.cycle-model.local_load_cycles-model.handoff_cycles
    stage_totals={}
    for (stage,tag),count in b.stage_cycles.items():stage_totals[stage]=stage_totals.get(stage,0)+count
    csv_out(a.output/'stage_cycles.csv',[{'stage':s,'reason':tag,'cycles':n} for (s,tag),n in b.stage_cycles.items()])
    csv_out(a.output/'wide_arithmetic_calls.csv',[{'operation':k,'calls':v,'unit':'isqrt' if k=='isqrt64' else 'divider' if 'reciprocal' in k else 'mul32x32'} for k,v in b.resource_calls.items()])
    regions=[
        {'region':'X/LN1','group':'A0..A3','base_word':0,'words_per_bank':832,'layout':'token pairs','lifetime':'input through each query LN1; then FC1/LN2','alias':'LN1 overwrites only rows whose X residual was consumed'},
        {'region':'Q/final_Y','group':'A0..A3','base_word':832,'words_per_bank':832,'layout':'token pairs','lifetime':'Q through last attention block; final Y after FF2','alias':'Q then Y'},
        {'region':'P_low/P_high/O/FF2','group':'A0..A3','base_word':1664,'words_per_bank':832,'layout':'8-query probability planes; then token pairs','lifetime':'P until complete PV; O until LN1; FF2 until LN2','alias':'P/O reuse only after all PV output channels'},
        {'region':'context','group':'A0..A3','base_word':2496,'words_per_bank':832,'layout':'token pairs','lifetime':'query PV through O projection','alias':'none while P active'},
        {'region':'K/hidden','group':'B0..B3','base_word':0,'words_per_bank':3328,'layout':'K token pairs 832; hidden token pairs3328','lifetime':'K until all attention; hidden FF1->GELU->FC2','alias':'hidden overwrites K/V only after final query LN1'},
        {'region':'V','group':'B0..B3','base_word':832,'words_per_bank':792,'layout':'channel pairs','lifetime':'V through final PV','alias':'overwritten by later FF1 hidden'},
        {'region':'weights','group':'W0..W3','base_word':0,'words_per_bank':6144,'layout':'output-channel pairs, tile-major K','lifetime':'entire layer','alias':'no next-layer prefetch'},
        {'region':'coefficients','group':'C0/C1','base_word':0,'words_per_bank':1880,'layout':'low16/high16 of 32-bit words','lifetime':'entire layer','alias':'none'},
        {'region':'GELU','group':'C0','base_word':1880,'words_per_bank':128,'layout':'two S8 entries/word','lifetime':'layer','alias':'none'},
        {'region':'score','group':'C0/C1','base_word':2048,'words_per_bank':792,'layout':'8x99 low16/high16','lifetime':'query QK through Softmax','alias':'next query after PV/LN1'},
        {'region':'residual','group':'C0','base_word':2880,'words_per_bank':512,'layout':'8x64 S16','lifetime':'residual align through corresponding LN','alias':'LN1/LN2 reusable'},
        {'region':'exp','group':'E0/E1','base_word':0,'words_per_bank':4096,'layout':'low16/high16 of U32','lifetime':'cold task','alias':'exp[4096] hardwired 0'}]
    for r in regions:assert r['base_word']+r['words_per_bank'] <= (8192 if r['group'].startswith('W') else 4096)
    csv_out(a.output/'memory_map.csv',regions)
    stats=[{'bank':bank,'capacity_words':len(b.mem[bank]),'read_requests':b.counts[(bank,'r')],
            'write_requests':b.counts[(bank,'w')],'physical_macros_16x4096':2 if bank.startswith('W') else 1} for bank in b.mem]
    csv_out(a.output/'bank_access_counts.csv',stats)
    assert sum(r['physical_macros_16x4096'] for r in stats)==20
    # No optimistic overlap: fully serialized cold host/CPU/MMIO baseline.
    packet_bytes=abi['cold_packet_bytes'];io_bytes=2*99*64;words=math.ceil((packet_bytes+io_bytes)/4)
    cpu_housekeeping=words*4+12*500
    crc_cycles=math.ceil(packet_bytes/4)
    scenarios=[]
    for mbps in [25,50,100,200,600]:
        # Effective bus rate excludes CPU housekeeping. Local port is max2B/cycle
        # for weights, but the slowest selected bus segment dominates here.
        single=math.ceil((packet_bytes+io_bytes)*150/mbps)
        local_floor=12*model.local_load_cycles # includes exp/input each layer: conservative floor only
        # Remove 11 redundant exp/input cold loads in the floor.
        input_write_cycles=b.stage_cycles[('cold_local_load','packed_write')]
        local_floor-=11*(4096+input_write_cycles)
        transport=2*single+max(single,local_floor)
        handoff=11*model.handoff_cycles
        cycles=12*core+transport+cpu_housekeeping+crc_cycles+handoff
        scenarios.append({'effective_bus_MBps':mbps,'serialized_bus_and_local_cycles':transport,
            'packet_crc_cycles':crc_cycles,'CPU_housekeeping_cycles':cpu_housekeeping,
            'inter_layer_copy_cycles':handoff,
            'encoder_core_cycles':12*core,'total_cycles':cycles,'conditional_ms_at_150MHz':cycles/150000,
            'tasks_per_second':150000000/cycles})
    # Reproduce the candidate hidden channel-layout conflict rather than hiding it.
    conflict={}
    from integer_model.bank_model import Banks
    check=Banks(a.output/'conflict_probe.jsonl.gz')
    try:check.tick([('B0',i*32,'r',0) for i in range(8)])
    except ValueError:conflict['channel_layout_FC2_8_token_reads']='rejected: eight addresses share B0'
    else:raise AssertionError('Port conflict not detected')
    finally:check.trace.close()
    result={'profile_sha256':abi['profile_sha256'],'sample_offset':a.sample,'layer':0,
        'functional_output_codes':int(out.size),'functional_mismatches':0,'all_checked_stage_outputs_equal':True,
        'trace_cycles':b.cycle,'local_initialization_cycles':model.local_load_cycles,'layer_core_cycles':core,
        'one_handoff_copy_cycles':model.handoff_cycles,'final_layer_no_handoff':True,
        'stage_total_cycles':stage_totals,'max_SRAM_bytes_requested_in_cycle':b.max_bytes,
        'single_port_conflicts_unaccounted':0,'initial_SRAM_poison_hex':'a5a5','tail_tokens':99,
        'PV_passes':2,'physical_macro_count':20,'SRAM_bytes':20*4096*2,
        'shared_multiplier':{'instances':1,'II':1,'multiplier_latency':3,'RNE_latency':1,'overlap_credit':0},
        'divider':{'instances':1,'latency':64,'non_pipelined':True},'isqrt':{'instances':1,'latency':32},
        'PE_mode':'64 parallel MACs, S8xS8 and U8xS8 (PV); all reduction results S32',
        'register_scratch_budget_bytes':4096,'register_budget_note':'separate from SRAM; includes block LN vector buffers/coefficients; implementation/area unmeasured',
        'wide_arithmetic_calls':dict(b.resource_calls),'resource_serialization':'every wide operation uses the single multiplier; fetch/compute/drain phases do not overlap',
        'conditional_system_model':scenarios,'CPU_assumptions':'4 non-wait housekeeping cycles/32bit word +500/layer, separately from bus handshake; not platform measurements',
        'transfer_path':'3 serialized segments host->shared SRAM, CPU read, MMIO write; output counted conservatively with same 3 segments',
        'packet_validation':'one 32-bit CRC word/cycle, serialized, no free CRC overlap',
        'layer_scaling':'12 identical shape schedules plus 11 explicitly charged same-layout output->input copies; only layer0 has full data trace, no cycle dependence on data or scale values',
        'conflict_probe':conflict,'model_source_sha256':sha(ROOT/'integer_model/bank_model.py'),
        'runner_source_sha256':sha(__file__),'trace_sha256':sha(a.output/'bank_trace.jsonl.gz')}
    result['ABI_reader_source_sha256']=sha(ROOT/'integer_model/hw_abi.py')
    csv_out(a.output/'register_scratch_budget.csv',[
        {'phase':'matrix','components':'64xS32 accum256 + 8x(bias,M,shift)96 + operand/packing/control128','budget_bytes':480},
        {'phase':'softmax','components':'two probability rows396 + reused score/exp/eR scratch792 + control128','budget_bytes':1316},
        {'phase':'LN','components':'8x64xS16 residual1024 + in-place S32 normalized/affine2048 + gamma/beta512 + row sums/recip64 + control128','budget_bytes':3776},
        {'phase':'declared envelope','components':'4KiB registers, reused between non-overlapping phases; area not measured','budget_bytes':4096}])
    (a.output/'cycle_model.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['functional_mismatches','trace_cycles','layer_core_cycles','stage_total_cycles','conditional_system_model']},indent=2))


if __name__=='__main__':main()
