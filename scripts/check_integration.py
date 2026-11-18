"""Independent G1-G3 evidence gate; never writes into frozen v2 releases."""
import hashlib,json,os,shutil,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from validate_integration import I,VR,ZIG,BIN,write
from validate_rtl_v2 import ledger
from rtl_v1_validation import hashes,run
from check_rtl_v2 import stored,verify_map
from validate_kwt1_r2 import artifacts
from integer_model.runtime import Encoder

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def check(out,software_only=False):
    if (out/'evidence_manifest.json').exists():verify_map(out,read(out/'evidence_manifest.json')['sha256'])
    if (out/'source_manifest.json').exists():verify_map(ROOT,read(out/'source_manifest.json'))
    old=ROOT/'testdata/rtl_v2/release'
    verify_map(old,read(old/'evidence_manifest.json')['sha256']);verify_map(ROOT,read(old/'source_manifest.json'));verify_map(ROOT,read(old/'input_hashes.json'))
    for path,digest in read(old/'toolchain.json')['tools'].items():assert sha(Path(path))==digest
    for name in ['rtl_v1/release','next_stage_v1']:
        base=ROOT/'testdata'/name;verify_map(ROOT,read(base/'source_manifest.json'));verify_map(base,read(base/'evidence_manifest.json')['sha256'])
    gate=None if software_only else read(out/'gate/summary.json');proto=read(out/'protocols/summary.json');assert proto['passed']
    if gate:
        assert gate['passed'] and len(gate['cases'])==2 and gate['output_codes']==12672 and 'PASS GATE BUS' in gate['result'] and 'GATE RESET PASS' in gate['result']
        verify_map(ROOT,read(out/'gate/source_hashes.json'))
    verify_map(ROOT,read(out/'protocols/source_hashes.json'))
    assert set(proto['tests'])=={'mmio','sram_behavior','sram_macro_wrapper','initial_bus_failure'}
    assert 'exchanges=65 accepted=77 retired=75 reset_discarded=2' in proto['tests']['mmio']
    labels=np.load(ROOT/'testdata/integer_v1/fixture/labels.npy');features=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r');saved=np.load(ROOT/'testdata/integer_v1/validation/encoder_output_int8.npy',mmap_mode='r')
    params_meta=read(ROOT/'testdata/integer_v1/params/manifest.json');packets,p=artifacts();cache={}
    def oracle(sample):
        if sample not in cache:
            x=np.clip(np.rint(features[sample].astype(np.float64)/params_meta['decode_scales']['encoder_input']),-127,127).astype(np.int8);y=Encoder(p)(x[None])[0]
            assert np.array_equal(y,saved[sample]);cache[sample]=(x.tobytes(),y.tobytes())
        return cache[sample]
    codes=0
    def outputs(folder,cases):
        nonlocal codes
        for c in cases:
            assert labels[c['sample']]==c['label'] and c['sample']==int(np.flatnonzero(labels==c['label'])[0]);x,y=oracle(c['sample']);idx=c['case']
            assert stored(folder/f'input_{idx:03d}.hex')==x
            assert stored(folder/f'expected_{idx:03d}.hex')==stored(folder/f'provider_observed_{idx:03d}.hex')==y;codes+=6336
        for name,data in packets.items():assert stored(folder/(name+'.hex'))==data
    if gate:outputs(out/'gate',gate['cases'])
    required=['candidate_always','candidate_stress','candidate_system']+[f'{kind}_cpu{cpu}_beat{beat}' for cpu in [4,8,16] for beat in [6,12] for kind in ['legacy','candidate']]
    summaries={};performance={}
    for name in required:
        folder=out/name;s=read(folder/'summary.json');assert s['passed'];summaries[name]=s;verify_map(ROOT,read(folder/'source_hashes.json'))
        expected=1 if '_cpu' in name else 12
        assert len(s['cases'])==expected
        if expected==12:assert {c['label'] for c in s['cases']}==set(range(12))
        outputs(folder,s['cases']);groups=ledger(folder/'ledger.txt',1335360)
        assert len(groups)==expected+(14 if name=='candidate_stress' else 0)
        rows=[list(map(int,r.split())) for r in (folder/'provider_metrics.txt').read_text().splitlines()];assert rows==s['metrics']
        normal=sorted(groups)[-expected:]
        for r,task in zip(rows,normal):
            assert r[1:5]==groups[task]['T'][0][:4] and r[8:10]==[13,61728] and r[13:16]==[189328,1584,1584]
            assert r[12]==(189328 if s['config']['legacy'] else 0)
        r=rows[0];performance[name]=dict(outer_cycles=r[6],transactions=r[7],status_reads=r[11],payload_status_reads=r[12],parameter_words=r[13],idle_cycles=r[18],all_cycle_range=[min(r[6] for r in rows),max(r[6] for r in rows)])
    assert performance['candidate_system']['outer_cycles']<=9000000
    grid=read(out/'budget.json');assert len(grid)==6
    for row in grid:
        cpu=row['cpu_extra_cycles'];beat=row['supply_cycles_per_word']
        for kind in ['legacy','candidate']:
            p_row=performance[f'{kind}_cpu{cpu}_beat{beat}'];assert row[kind]['outer_cycles']==p_row['outer_cycles'] and row[kind]['transactions']==p_row['transactions']
        assert row['candidate']['outer_cycles']<row['legacy']['outer_cycles'] and row['candidate']['param_words']==row['legacy']['param_words']==189328
    faults=[list(map(int,r.split())) for r in (out/'candidate_stress/faults.txt').read_text().splitlines()];assert len(faults)==14 and [r[0] for r in faults]==list(range(1,15))
    for r in faults:
        quarantined=r[0] in [7,8,12,13];assert r[6]==int(quarantined) and (r[1]==-7 if quarantined else r[5]==0)
    assert faults[6][3]==1 and faults[8][2]==8 and faults[9][2]==8 and faults[13][2]==32
    compiler=Path(os.environ.get('KWT_RISCV_GCC','E:/project/FPGAcompetition/RISCV_CPU/tools/xpack-toolchain/xpack-riscv-none-elf-gcc-15.2.0-1/bin/riscv32-unknown-elf-gcc.exe'))
    for name in ['kwt1','abi_check']:run([compiler,'-march=rv32imac','-mabi=ilp32','-std=c99','-ffreestanding','-Wall','-Wextra','-Werror','-c',I/'driver'/(name+'.c'),'-o',out/(name+'.o')],out)
    if software_only:
        report=dict(passed=True,scope='G2/G3 only; G1 still separately required',saved_output_codes_recomputed=codes,mismatches=0,full_classes_per_primary_configuration=12,provider_faults_and_complete_recoveries=14,payload_status_removed=189328,payload_status_remaining=0,candidate_cpu8_bw100_cycles=performance['candidate_system']['outer_cycles'],MMIO_same_edge_exchanges=65,RV32_device_context_bytes=40)
        write(out/'software_verification.json',report);write(out/'performance.json',performance);print(json.dumps(report,indent=2),flush=True);return
    lock=dict(PE_rows=8,PE_columns=8,SRAM_macros=20,SRAM_depth=4096,SRAM_width=16,integer_profile='INTEGER_NUMERICS_V1',register_bits=30459,register_bytes_ceiling=3808,hardware_sources=read(old/'source_manifest.json'),frozen_inputs=read(old/'input_hashes.json'),previous_release_manifest_sha256=sha(old/'evidence_manifest.json'),SOURCE_E01='OPEN',LN_E01='unchanged approved local exception; six historical failures retained')
    write(out/'architecture_lock.json',lock);write(out/'performance.json',performance)
    sources=[*[f for f in I.rglob('*') if f.is_file()],*[ROOT/'scripts'/name for name in ['validate_integration.py','check_integration.py','run_equivalence.py']]]
    source_hashes=hashes(sources)
    for path in sources:
        target=out/'source'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    write(out/'source_manifest.json',source_hashes)
    tools=[BIN/'iverilog.exe',BIN/'vvp.exe',VR/'bin/verilator_bin.exe',ZIG,compiler]
    runtime=hashes([f for f in (VR/'include').rglob('*') if f.is_file()])
    write(out/'toolchain.json',dict(tools={str(t):sha(t) for t in tools},verilator_runtime=runtime,base_toolchain_sha256=sha(old/'toolchain.json')))
    report=dict(passed=True,revision='G1-G3 closure / architecture v1.10',saved_output_codes_recomputed=codes,mismatches=0,whole_generic_netlist_cold_tasks=2,gate_inflight_reset='LN N_PASS then full cold recovery',formal_equivalence=False,driver_configurations=6,full_classes_per_primary_configuration=12,provider_faults_and_complete_recoveries=14,MMIO_same_edge_exchanges=65,payload_status_removed=189328,payload_status_remaining=0,SRAM_macros=20,register_bytes_ceiling=3808,candidate_cpu8_bw100_cycles=performance['candidate_system']['outer_cycles'],architecture_frozen=True,awaiting=['designated E203/organizer integration and instruction cycles','actual firmware image and stack high-water','designated library/macro timing/area/energy and mapped-netlist recheck','SOURCE-E01 new historical evidence only'])
    write(out/'verification.json',report)
    evidence={}
    for f in out.rglob('*'):
        if not f.is_file():continue
        rel=f.relative_to(out)
        if any(part.startswith('build') for part in rel.parts) or f.suffix in ['.obj','.o','.exe','.vvp'] or f.name=='evidence_manifest.json':continue
        evidence[rel.as_posix()]=sha(f)
    write(out/'evidence_manifest.json',dict(sha256=evidence));print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':check(Path(sys.argv[1]).resolve())
