"""R17 release gate: rederive outputs, validate counters and freeze source/evidence."""
import hashlib,json,os,platform,re,shutil,sys
from importlib.metadata import distributions
from collections import Counter
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from validate_rtl_v2 import SOURCES,VR,BIN,run,hashes,ledger
from rtl_v1_inventory import inventory
from validate_kwt1_r2 import artifacts
from validate_kwt1_r1 import edge_input,boundary_oracle
from integer_model.runtime import Encoder

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def stored(path):return b''.join(int(v,16).to_bytes(4,'little') for v in path.read_text().split())
def verify_map(base,mapping):
    for name,digest in mapping.items():assert sha(base/name)==digest,('hash mismatch',str(base/name))

def check(out):
    if (out/'evidence_manifest.json').exists():verify_map(out,read(out/'evidence_manifest.json')['sha256'])
    if (out/'toolchain.json').exists():
        for path,digest in read(out/'toolchain.json')['tools'].items():assert sha(Path(path))==digest,('tool changed',path)
    old=ROOT/'testdata/rtl_v1/release'
    verify_map(ROOT,read(old/'source_manifest.json'));verify_map(ROOT,read(old/'input_hashes.json'));verify_map(old,read(old/'evidence_manifest.json')['sha256'])
    previous=ROOT/'testdata/next_stage_v1'
    verify_map(ROOT,read(previous/'source_manifest.json'));verify_map(previous,read(previous/'evidence_manifest.json')['sha256'])
    required=['unit','layer','stress','cross','v1_always','v1_stress','v2_always','v2_stress','v2_system','synth']
    summaries={name:read(out/name/'summary.json') for name in required}
    for name,s in summaries.items():
        assert s['passed'],name
        verify_map(ROOT,read(out/name/'source_hashes.json'))
    verify_map(ROOT,read(out/'synth/post_math/source_hashes.json'))
    assert read(out/'synth/post_math/summary.json')['passed']
    assert summaries['stress']['rejected']==7 and summaries['stress']['reset_scenarios']==12
    assert len(summaries['layer']['cases'])==24
    ordinary=[c for c in summaries['layer']['cases'] if not c.get('boundary')]
    assert {c['profile'] for c in ordinary}=={c['label'] for c in ordinary}==set(range(12))
    assert {c['profile'] for c in summaries['layer']['cases'] if c.get('boundary')}==set(range(12))
    packets,p=artifacts();meta=read(ROOT/'testdata/integer_v1/params/manifest.json')
    fixture=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r');labels=np.load(ROOT/'testdata/integer_v1/fixture/labels.npy')
    saved=np.load(ROOT/'testdata/integer_v1/validation/encoder_output_int8.npy',mmap_mode='r');cache={}
    def quant(sample):return np.clip(np.rint(fixture[sample].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
    def trace(sample):
        if sample not in cache:
            taps={};x=quant(sample);y=Encoder(p,lambda n,v,z:taps.update({n:v[0].copy()}) if n.count('/')==1 else None)(x[None])[0]
            assert np.array_equal(y,saved[sample]);cache[sample]=(x,y,taps)
        return cache[sample]
    verified=0
    for c in summaries['layer']['cases']:
        lid=c['profile']
        if c.get('boundary'):x=edge_input();y=boundary_oracle(p,lid,x)['layernorm2_output']
        else:
            assert labels[c['sample']]==c['label'];q,_,taps=trace(c['sample']);x=q if lid==0 else taps[f'layer_{lid-1:02d}/layernorm2_output'];y=taps[f'layer_{lid:02d}/layernorm2_output']
        assert stored(out/'layer'/f'input_{c["case"]:03d}.hex')==x.tobytes()
        assert stored(out/'layer'/f'expected_{c["case"]:03d}.hex')==stored(out/'layer'/f'observed_{c["case"]:03d}.hex')==y.tobytes();verified+=6336
    perf={};phase_names=['Q','K','V','O','FC1','FC2','QK','Softmax','PV','LN','GELU','handoff','control']
    block_names=['core_disabled','memory_disabled','iterative_wait','scalar_math_wait','request_backpressure','active']
    for name in ['v1_always','v1_stress','v2_always','v2_stress','v2_system']:
        s=summaries[name];folder=out/name;cases=s['cases'];is_v1=name.startswith('v1');expected_labels={0,4} if is_v1 else set(range(12))
        assert len(cases)==len(expected_labels) and {c['label'] for c in cases}==expected_labels
        assert s['config']['version']==('v1' if is_v1 else 'v2') and s['config']['mode']==name.split('_')[1]
        assert not s['config']['is_E203_instruction_timing']
        for c in cases:
            sample=c['sample'];assert labels[sample]==c['label'] and sample==int(np.flatnonzero(labels==c['label'])[0]);x,y,_=trace(sample)
            assert stored(folder/f'input_{c["case"]:03d}.hex')==x.tobytes()
            assert stored(folder/f'expected_{c["case"]:03d}.hex')==stored(folder/f'provider_observed_{c["case"]:03d}.hex')==y.tobytes();verified+=6336
        for packet,data in packets.items():assert stored(folder/(packet+'.hex'))==data
        metrics=[list(map(int,line.split())) for line in (folder/'provider_metrics.txt').read_text().splitlines()];assert metrics==s['metrics']
        groups=ledger(folder/'ledger.txt',6470592 if is_v1 else 1335360)
        assert len(groups)==len(cases)+(6 if name=='v2_stress' else 0)
        if name=='v2_stress':assert 'PROVIDER FAULTS PASS' in s['result']
        # Last twelve records are the normal saved tasks; earlier records are recoveries.
        normal=sorted(groups)[-len(cases):]
        for row,task in zip(metrics,normal):
            assert row[1:5]==groups[task]['T'][0][:4] and row[6]>=row[1] and row[8:10]==[13,61728]
        g=groups[normal[0]];r=metrics[0]
        perf[name]=dict(RTL_cycles=r[1],outer_cycles=r[6],compute_cycles=r[2],SRAM_reads_16bit=r[3],SRAM_writes_16bit=r[4],injected_stalls=r[5],transactions=r[7],MAC_launches=g['T'][0][6],valid_scalar_MACs=g['T'][0][7],
            phases={phase_names[v[0]]:dict(cycles=v[1],reads=v[2],writes=v[3],wide_requests=v[4],wide_retired=v[5]) for v in g['P']},exclusive_blockers={block_names[v[0]]:v[1] for v in g['B']},
            outer_cycles_range=[min(v[6] for v in metrics),max(v[6] for v in metrics)],at_assumed_150MHz_ms=r[6]/150000)
    for mode in ['always','stress']:
        a=read(out/('v1_'+mode)/'config.json');b=read(out/('v2_'+mode)/'config.json');a.pop('version');b.pop('version');assert a==b
    x,y,taps=trace(ordinary[0]['sample']);layer0=taps['layer_00/layernorm2_output'].tobytes()
    for name in ['stress','cross']:
        assert stored(out/name/'input_000.hex')==x.tobytes()
        assert stored(out/name/'expected_000.hex')==stored(out/name/'observed_000.hex')==layer0;verified+=6336
    os.environ['VERILATOR_ROOT']=str(VR)
    production=[*SOURCES,ROOT/'rtl/v2/kwt1_mmio.sv']
    for path in production:
        code=path.read_text();assert '$readmemh' not in code and re.search(r'\breal\b',code) is None,path
    run([VR/'bin/verilator_bin.exe','--json-only','--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC','-I'+str(ROOT/'rtl/v2/generated'),'--top-module','kwt1_mmio','--Mdir',out/'json',*production],out)
    inv=inventory(out/'json/Vkwt1_mmio.tree.json',out/'register_inventory.json')
    run([VR/'bin/verilator_bin.exe','--lint-only','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC','-I'+str(ROOT/'rtl/v2/generated'),'--top-module','kwt1_mmio',*production],out)
    run([BIN/'iverilog.exe','-g2012','-I',ROOT/'rtl/v2/generated','-s','kwt1_mmio','-o',out/'production.vvp',*production],out)
    net=read(out/'synth/generic.json')['modules']['kwt1_mmio']['cells'];types=Counter(c['type'] for c in net.values())
    macros=[c for c in net.values() if c['type']=='kwt_tech_sram_4096x16'];assert len(macros)==20,types
    assert not any('LATCH' in t.upper() or t.startswith('$mem') for t in types),types
    pre=read(out/'synth/premap.json')['modules']['kwt1_mmio']['cells']
    variable_mul=[(n,c) for n,c in pre.items() if c['type']=='$mul' and all(any(isinstance(b,int) for b in c['connections'][port]) for port in ['A','B'])]
    assert len(variable_mul)==68,len(variable_mul)
    assert all(('pe.' in n or 'mul.' in n) for n,c in variable_mul),[n for n,c in variable_mul]
    synth_report=dict(cell_types=dict(types),generic_cell_count=len(net),SRAM_macro_instances=20,variable_multiplier_nodes=68,check_assert_passed=True,post_synthesis_math_vectors=2592,RTL_iterative_vectors_in_same_TB=640,scope='technology independent generic gates; only math block post-synthesis simulated; iterative/PE/SRAM remain RTL in that TB; SRAM blackboxes; no physical library')
    (out/'synthesis_inventory.json').write_text(json.dumps(synth_report,indent=2))
    compiler=Path(os.environ.get('KWT_RISCV_GCC','E:/project/FPGAcompetition/RISCV_CPU/tools/xpack-toolchain/xpack-riscv-none-elf-gcc-15.2.0-1/bin/riscv32-unknown-elf-gcc.exe'))
    run([compiler,'-march=rv32imac','-mabi=ilp32','-std=c99','-ffreestanding','-Wall','-Wextra','-Werror','-c',ROOT/'rtl/v2/driver/kwt1.c','-o',out/'driver_rv32.o'],out)
    input_hashes=read(old/'input_hashes.json');(out/'input_hashes.json').write_text(json.dumps(input_hashes,indent=2))
    sources=sorted(set([*SOURCES,*[v for v in (ROOT/'rtl/v2').rglob('*') if v.is_file()],*[ROOT/'scripts'/n for n in ['validate_rtl_v2.py','check_rtl_v2.py','run_yosys_v2.py','rtl_v1_validation.py','rtl_v1_inventory.py','rtl_v1_trace_compare.py']]]))
    source_hashes=hashes(sources)
    for path in sources:
        target=out/'source'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    (out/'source_manifest.json').write_text(json.dumps(source_hashes,indent=2))
    tools=[BIN/'iverilog.exe',BIN/'vvp.exe',VR/'bin/verilator_bin.exe',ROOT/'tools/rtl_v1_python/ziglang/zig.exe',compiler,ROOT/'tools/rtl_v2_python/yowasp_yosys/yosys.wasm']
    assert platform.python_version()=='3.10.9' and np.__version__=='1.26.2'
    packages={d.metadata['Name'].lower().replace('_','-'):d.version for d in distributions(path=[str(ROOT/'tools/rtl_v2_python')])}
    locked={'yowasp-yosys':'0.69.0.0.post1233','yowasp-runtime':'1.96','wasmtime':'47.0.1','click':'8.5.0','platformdirs':'4.12.4'}
    assert all(packages[k]==v for k,v in locked.items()),packages
    (out/'toolchain.json').write_text(json.dumps(dict(python=platform.python_version(),numpy=np.__version__,packages=locked,tools={str(v):sha(v) for v in tools}),indent=2))
    (out/'performance.json').write_text(json.dumps(perf,indent=2))
    report=dict(passed=True,release='R17 A-E / RTL v2 / architecture v1.8',required=required,saved_output_codes_recomputed=verified,mismatches=0,full_classes=12,full_tasks_per_v2_configuration=12,provider_fault_recoveries=6,register_bits=inv['register_bits'],register_bytes_ceiling=inv['register_bytes_ceiling'],SRAM_macros=20,
        data_bytes=74400,firmware_reservation_bytes=131072,stack_reservation_bytes=16384,reserved_used_bytes=221856,shared_capacity_bytes=524288,
        outer_cycles={n:p['outer_cycles_range'] for n,p in perf.items()},meets_internal_9M_cycles={n:max(p['outer_cycles_range'])<=9000000 for n,p in perf.items() if n.startswith('v2')},
        previous_source_files=len(read(old/'source_manifest.json')),previous_evidence_files=len(read(old/'evidence_manifest.json')['sha256']),source_files=len(source_hashes),
        scope='fixed8x8/20SP-SRAM generic RTL and bounded host provider; real CPU image/stack and instructions, organizer supply integration, whole-netlist equivalence and physical PPA await designated platform',LN_E01='approved fixed-profile exception unchanged; six historical failures retained',SOURCE_E01='OPEN; no new historical evidence')
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    keep={'verification.json','source_manifest.json','toolchain.json','input_hashes.json','register_inventory.json','performance.json','synthesis_inventory.json'};evidence={}
    for path in out.rglob('*'):
        if not path.is_file():continue
        rel=path.relative_to(out)
        if any(v.startswith('build') or v=='json' for v in rel.parts):continue
        if rel.parts[0] not in required+['source'] and rel.as_posix() not in keep:continue
        if path.suffix in ['.vvp','.exe','.o'] or path.name=='tools.jsonl' or path.name.endswith('trace.txt'):continue
        evidence[rel.as_posix()]=sha(path)
    (out/'evidence_manifest.json').write_text(json.dumps(dict(sha256=evidence),indent=2));print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':check(Path(sys.argv[1]).resolve())
