"""Independent reference-system gate: rederive integer outputs, bind all inputs.

This checker never supplies outputs to the CPU/model and never edits old releases.
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path
import numpy as np
from local_tools import ROOT, Tools, SUFFIX, sha
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from integer_model.runtime import Encoder
from validate_kwt1_r2 import artifacts

COLUMNS=['job','label','fault','rc','outer_cycles','retired','cpu_csr_cycles','cpu_csr_instret','parameter_words','acquires','releases','cancels','packet_peak_bytes','stack_highwater_bytes','accelerator_task_cycles','accelerator_compute_cycles','ram_read_words','ram_write_words']
GROUPS=['classes_0_3','classes_4_7','classes_8_11','faults']

def read(p):return json.loads(p.read_text())
def stored(p):return b''.join(int(x,16).to_bytes(4,'little') for x in p.read_text().split())
def verify(base,values):
    for name,digest in values.items():assert sha(base/name.replace('\\','/'))==digest,('hash mismatch',str(base/name))

def check(out,cpu):
    if (out/'evidence_manifest.json').exists():verify(out,read(out/'evidence_manifest.json')['sha256'])
    if (out/'source_manifest.json').exists():verify(ROOT,read(out/'source_manifest.json'))
    # Existing closures stay byte-for-byte intact; no slow gate simulation repeated.
    previous={}
    for name in ['integration_v1/release','rtl_v2/release','rtl_v1/release','next_stage_v1']:
        base=ROOT/'testdata'/name
        verify(base,read(base/'evidence_manifest.json')['sha256']);verify(ROOT,read(base/'source_manifest.json'))
        previous[name]=sha(base/'evidence_manifest.json')
    verify(ROOT,read(ROOT/'testdata/rtl_v2/release/input_hashes.json'))
    assert read(ROOT/'testdata/integration_v1/release/verification.json')['passed']
    stamp=read(out/'build/model/stamp.json')
    for name,digest in stamp['inputs'].items():assert sha(Path(name))==digest,name
    packets,params=artifacts();profile=read(ROOT/'rtl/v2/generated/profile.json')
    assert set(packets)==set(profile['packets']) and len(packets)==13
    for name,value in packets.items():assert hashlib.sha256(value).hexdigest()==profile['packets'][name]
    labels=np.load(ROOT/'testdata/integer_v1/fixture/labels.npy')
    features=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r')
    saved=np.load(ROOT/'testdata/integer_v1/validation/encoder_output_int8.npy',mmap_mode='r')
    meta=read(ROOT/'testdata/integer_v1/params/manifest.json');cache={}
    def oracle(label):
        if label not in cache:
            sample=int(np.flatnonzero(labels==label)[0]);x=np.clip(np.rint(features[sample].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
            y=Encoder(params)(x[None])[0];assert np.array_equal(y,saved[sample]);cache[label]=(sample,x.tobytes(),y.tobytes())
        return cache[label]
    rows=[];all_classes=[];codes=0;bindings={};firmware_hashes=set();bin_hashes=set();load_hashes=set();stack=0
    for group in GROUPS:
        base=out/group;ex=read(base/'execution.json');assert ex['passed'] and not ex['quick']
        assert ex['mode']==('faults' if group=='faults' else 'batch')
        prov=read(base/'provenance.json');assert prov['cpu_revision']=='9f3e34f337f5d0a1236a285871ffa2032491617a'
        assert prov['cpu_license']=='Apache-2.0' and prov['ISA']=='rv32imac_zicsr' and prov['ABI']=='ilp32'
        assert prov['defines']==['FPGA_SOURCE'] and not prov['physical_signoff']
        verify(ROOT,prov['project']);verify(cpu,prov['cpu']);bindings.update(prov['project'])
        assert prov['model_sha256']==sha(out/'build/model'/('sim'+SUFFIX))
        assert prov['firmware_sha256']==sha(base/'firmware.elf');firmware_hashes.add(prov['firmware_sha256']);bin_hashes.add(sha(base/'firmware.bin'))
        elf=(base/'firmware.elf').read_bytes();assert elf[:6]==b'\x7fELF\x01\x01' and struct.unpack_from('<H',elf,18)[0]==243 and struct.unpack_from('<I',elf,24)[0]==0xa0000000
        phoff=struct.unpack_from('<I',elf,28)[0];phsize,phnum=struct.unpack_from('<HH',elf,42);segments=[];image=(base/'firmware.bin').read_bytes()
        for i in range(phnum):
            kind,offset,addr,physical,filesz,memsz,flags,alignment=struct.unpack_from('<8I',elf,phoff+i*phsize)
            if kind!=1:continue
            data=elf[offset:offset+filesz];assert physical==addr and 0xa0000000<=addr<=addr+memsz<=0xa0020000
            assert data==image[addr-0xa0000000:addr-0xa0000000+filesz]
            segments.append((addr,filesz,memsz,flags,data.hex()))
        assert segments;load_hashes.add(hashlib.sha256(json.dumps(segments).encode()).hexdigest())
        mem=read(base/'memory_map.json');assert mem['__input']==0xa0020000 and mem['__output']==0xa0022000 and mem['__packet']==0xa0024000 and mem['__stack_bottom']==0xa007c000 and mem['__stack_top']==0xa0080000
        assert mem['__image_end']<=mem['__input'] and mem['__input']+6336<=mem['__output'] and mem['__output']+6336<=mem['__packet'] and mem['__packet']+61728<=mem['__stack_bottom']
        for name,value in packets.items():assert stored(base/(name+'.hex'))==value
        cases=read(base/'cases.json')
        for case in cases:
            sample,x,y=oracle(case['label']);assert case['sample']==sample
            assert stored(base/f'input_{case["case"]:03d}.hex')==x and stored(base/f'expected_{case["case"]:03d}.hex')==y
        parsed=[dict(zip(COLUMNS,map(int,line.split()))) for line in (base/'cpu_metrics.txt').read_text().splitlines()]
        assert len(parsed)==4 and [r['job'] for r in parsed]==[0,1,2,3]
        if group=='faults':assert [(r['fault'],r['rc']) for r in parsed]==[(1,-3),(0,0),(2,-7),(0,0)]
        else:
            assert all(r['fault']==r['rc']==0 for r in parsed)
            assert [r['label'] for r in parsed]==[c['label'] for c in cases];all_classes += [r['label'] for r in parsed]
        for row in parsed:
            assert len(row)==18 and row['outer_cycles']>row['cpu_csr_cycles']>row['cpu_csr_instret']>0
            assert row['retired']>row['cpu_csr_instret'] and row['outer_cycles']-row['cpu_csr_cycles']<20000 and row['retired']-row['cpu_csr_instret']<2000
            assert 0<row['stack_highwater_bytes']<=16384;stack=max(stack,row['stack_highwater_bytes'])
            assert row['ram_read_words']>0 and row['ram_write_words']>0
            if row['rc']==0:
                assert [row[k] for k in ['parameter_words','acquires','releases','cancels','packet_peak_bytes','accelerator_compute_cycles']]==[189328,13,13,0,61728,5058532]
                assert 5058532<row['accelerator_task_cycles']<row['outer_cycles']
                assert stored(base/f'cpu_observed_job_{row["job"]:02d}.hex')==oracle(row['label'])[2];codes+=6336
            else:assert row['cancels']==1 and row['acquires']==row['releases']
            rows.append(dict(group=group,**row))
        log=(base/'live.log').read_text();assert 'FAIL' not in log and 'PASS E203 jobs=4' in log
        match=re.search(r'min_sp=([0-9a-f]+) stack_highwater=(\d+)',log);assert match and 0xa0080000-int(match[1],16)==int(match[2])==max(r['stack_highwater_bytes'] for r in parsed)
    # ELF debug/non-load sections may contain per-invocation compiler paths.
    # Compare all actual PT_LOAD bytes/addresses/flags plus the installed image.
    assert sorted(all_classes)==list(range(12)) and codes==88704 and len(bin_hashes)==len(load_hashes)==1
    normal=[r for r in rows if r['rc']==0];clocks=[r['outer_cycles'] for r in normal]
    footprint=mem['__image_end']-0xa0000000+6336*2+61728+16384
    assert footprint<=524288
    report=dict(passed=True,scope='supplied E203 RTL + external shared RAM reference; not designated SoC or SMIC40 timing signoff',cpu_revision=prov['cpu_revision'],full_classes=12,class_output_codes=76032,recovery_output_codes=12672,saved_output_codes_recomputed=codes,mismatches=0,consecutive_cold_tasks_per_class_instance=4,fault_scenarios=['CRC error + complete cold recovery','persistent response stall, callback timeout, ABORT timeout, RESET_REQUIRED API quarantine, hardware accelerator reset + complete cold recovery'],normal_tasks=14,parameter_words_per_normal_task=189328,max_packet_bytes=61728,firmware_image_end=mem['__image_end'],firmware_memory_bytes=mem['__image_end']-0xa0000000,occupied_bytes_including_reserved_stack=footprint,shared_ram_capacity_bytes=524288,stack_reserved_bytes=16384,stack_highwater_bytes=stack,normal_outer_cycles_range=[min(clocks),max(clocks)],normal_retired_range=[min(r['retired'] for r in normal),max(r['retired'] for r in normal)],accelerator_compute_cycles=5058532,internal_9M_target_met=max(clocks)<=9000000,assumed_150MHz_ms_range=[min(clocks)/150000,max(clocks)/150000],physical_signoff=False,linux_execution='pending',unused_reference_CPU_TCM_bytes=131072,SOURCE_E01='OPEN',LN_E01='approved local exception unchanged',previous_manifests=previous)
    for p in [Path(__file__),ROOT/'scripts/validate_reference_system.py',ROOT/'rtl/reference/tb_icb_kwt_bridge.sv']:
        bindings[p.relative_to(ROOT).as_posix()]=sha(p)
    for name,digest in bindings.items():
        dest=out/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/name).read_bytes())
    (out/'source_manifest.json').write_text(json.dumps(bindings,indent=2))
    tools=Tools();verilator,vr=tools.verilator();paths=[tools.gcc(),tools.binutil('objcopy'),tools.binutil('nm'),verilator,Path(tools.cxx()[0])]
    if not paths[-1].is_file():
        import shutil
        paths[-1]=Path(shutil.which(str(paths[-1])))
    toolchain=dict(tools={str(p):sha(p) for p in paths},runtime={str(p):sha(p) for p in sorted((vr/'include').rglob('*')) if p.is_file()})
    (out/'toolchain.json').write_text(json.dumps(toolchain,indent=2));(out/'metrics.json').write_text(json.dumps(rows,indent=2));(out/'verification.json').write_text(json.dumps(report,indent=2))
    evidence={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file() and 'model' not in p.relative_to(out).parts and p.name!='evidence_manifest.json'}
    (out/'evidence_manifest.json').write_text(json.dumps(dict(sha256=evidence),indent=2));print(json.dumps(report,indent=2),flush=True)
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--cpu',type=Path,default=ROOT.parent/'e203_hbirdv2');a=ap.parse_args();check(a.output.resolve(),a.cpu.resolve())
