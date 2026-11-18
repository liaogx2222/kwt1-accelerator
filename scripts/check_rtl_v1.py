"""Strict evidence gate for the complete banked v1 RTL release."""
import hashlib,json,os,platform,re,shutil,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from rtl_v1_validation import SOURCES,BIN,run,hashes
from rtl_v1_inventory import inventory
from validate_kwt1_r2 import artifacts
from validate_kwt1_r1 import boundary_oracle,edge_input
from integer_model.runtime import Encoder
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stored(path):
    return b''.join(int(s,16).to_bytes(4,'little') for s in path.read_text().split())
def check(out):
    if (out/'evidence_manifest.json').exists():
        for path,digest in json.loads((out/'evidence_manifest.json').read_text())['sha256'].items():assert sha(out/path)==digest,('released evidence changed',path)
    if (out/'toolchain.json').exists():
        for path,digest in json.loads((out/'toolchain.json').read_text())['tools'].items():assert sha(Path(path))==digest,('tool changed',path)
    required=['unit','layer','full','mmio','stress','cross'];summaries={}
    for stage in required:
        folder=out/stage;summary=json.loads((folder/'summary.json').read_text());assert summary['passed'],stage;summaries[stage]=summary
        for path,digest in json.loads((folder/'source_hashes.json').read_text()).items():assert sha(ROOT/path)==digest,('compiled source changed',stage,path)
    assert len(summaries['layer']['cases'])==24 and len(summaries['full']['cases'])==2
    previous=ROOT/'testdata/next_stage_v1';frozen=json.loads((ROOT/'testdata/r1r2/release/provenance.json').read_text())['inputs']
    for path,digest in frozen.items():assert sha(ROOT/path)==digest,('frozen input changed',path)
    old_sources=json.loads((previous/'source_manifest.json').read_text())
    for path,digest in old_sources.items():assert sha(ROOT/path)==digest,('old source changed',path)
    old_evidence=json.loads((previous/'evidence_manifest.json').read_text())['sha256']
    for path,digest in old_evidence.items():assert sha(previous/path)==digest,('old evidence changed',path)
    packets,p=artifacts();meta=json.loads((ROOT/'testdata/integer_v1/params/manifest.json').read_text())
    fixture=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r');saved=np.load(ROOT/'testdata/integer_v1/validation/encoder_output_int8.npy',mmap_mode='r')
    labels=np.load(ROOT/'testdata/integer_v1/fixture/labels.npy')
    ordinary=[c for c in summaries['layer']['cases'] if not c.get('boundary')]
    assert {c['profile'] for c in ordinary}==set(range(12)) and {c['label'] for c in ordinary}==set(range(12))
    assert all(labels[c['sample']]==c['label'] for c in ordinary)
    input_hashes=dict(frozen)
    input_hashes.update(hashes([ROOT/'testdata/integer_v1/fixture/labels.npy',ROOT/'testdata/integer_v1/fixture/manifest.json']))
    (out/'input_hashes.json').write_text(json.dumps(input_hashes,indent=2))
    def quant(sample):return np.clip(np.rint(fixture[sample].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
    verified=0
    for c in summaries['layer']['cases']:
        if c.get('boundary'):x=edge_input();y=boundary_oracle(p,c['profile'],x)['layernorm2_output']
        else:
            q=quant(c['sample']);taps={};Encoder(p,lambda n,v,z:taps.update({n:v[0].copy()}) if n.count('/')==1 else None)(q[None]);l=c['profile']
            x=q if l==0 else taps[f'layer_{l-1:02d}/layernorm2_output'];y=taps[f'layer_{l:02d}/layernorm2_output']
        folder=out/'layer';assert stored(folder/f'input_{c["case"]:03d}.hex')==x.tobytes()
        assert stored(folder/f'expected_{c["case"]:03d}.hex')==stored(folder/f'observed_{c["case"]:03d}.hex')==y.tobytes();verified+=6336
    for c in summaries['full']['cases']:
        x=quant(c['sample']);y=Encoder(p)(x[None])[0];assert np.array_equal(y,saved[c['sample']]);folder=out/'full'
        assert stored(folder/f'input_{c["case"]:03d}.hex')==x.tobytes()
        for prefix in ['expected','observed','mmio_observed']:assert stored(folder/f'{prefix}_{c["case"]:03d}.hex')==y.tobytes()
        verified+=2*6336
    for stage in ['stress','cross']:
        assert stored(out/stage/'expected_000.hex')==stored(out/stage/'observed_000.hex');verified+=6336
    vr=ROOT/'tools/rtl_v1_python/verilator';os.environ['VERILATOR_ROOT']=str(vr)
    run([vr/'bin/verilator_bin.exe','--json-only','--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC','-I'+str(ROOT/'rtl/v1/generated'),'--top-module','kwt1_mmio','--Mdir',out/'json',*SOURCES,ROOT/'rtl/v1/kwt1_mmio.sv'],out)
    inv=inventory(out/'json/Vkwt1_mmio.tree.json',out/'register_inventory.json')
    # Width conversions are reviewed fixed-profile assignments; every other
    # diagnostic remains fatal. There must be no combinational-loop/latch warning.
    run([vr/'bin/verilator_bin.exe','--lint-only','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC','-I'+str(ROOT/'rtl/v1/generated'),'--top-module','kwt1_mmio',*SOURCES,ROOT/'rtl/v1/kwt1_mmio.sv'],out)
    run([BIN/'iverilog.exe','-g2012','-I',ROOT/'rtl/v1/generated','-s','kwt1_mmio','-o',out/'production_compile.vvp',*SOURCES,ROOT/'rtl/v1/kwt1_mmio.sv'],out)
    for path in SOURCES+[ROOT/'rtl/v1/kwt1_mmio.sv']:
        text=path.read_text();assert '$readmemh' not in text and re.search(r'\breal\b',text) is None,path
    tools=[BIN/'iverilog.exe',BIN/'vvp.exe',vr/'bin/verilator_bin.exe',ROOT/'tools/rtl_v1_python/ziglang/zig.exe']
    source_paths=sorted(set([*SOURCES,*[p for p in (ROOT/'rtl/v1').rglob('*') if p.is_file()],*[ROOT/'scripts'/n for n in ['validate_rtl_v1.py','rtl_v1_validation.py','rtl_v1_inventory.py','rtl_v1_trace_compare.py','check_rtl_v1.py']]]))
    source_hashes=hashes(source_paths)
    for path in source_paths:
        dest=out/'source'/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
    (out/'source_manifest.json').write_text(json.dumps(source_hashes,indent=2))
    tool_info=dict(python=platform.python_version(),numpy=np.__version__,tools={str(p):sha(p) for p in tools},versions=dict(verilator='5.48.0 wheel (binary reports vUNKNOWN-built20260516-4e853d8)',zig='0.13.0',iverilog='12.0 devel s20150603'))
    assert tool_info['python']=='3.10.9' and tool_info['numpy']=='1.26.2'
    (out/'toolchain.json').write_text(json.dumps(tool_info,indent=2))
    # Metrics are sampled from RTL counters, not a software schedule estimate.
    metric_rows=[list(map(int,line.split())) for line in (out/'full/mmio_metrics.txt').read_text().splitlines()]
    report=dict(passed=True,release='banked RTL v1 / architecture v1.6',required=required,saved_output_codes_recomputed=verified,mismatches=0,
                register_bytes_ceiling=inv['register_bytes_ceiling'],SRAM_macros=20,nonconstant_multiplier_nodes=68,
                cold_MMIO_cycles=[r[1] for r in metric_rows],at_150MHz_ms=[r[1]/150000 for r in metric_rows],meets_60ms=False,
                frozen_inputs=len(frozen),previous_source_files=len(old_sources),previous_evidence_files=len(old_evidence),source_files=len(source_hashes),
                scope='complete fixed-profile synthesizable RTL + synchronous behavioral SRAM + generic MMIO; no designated SoC/technology mapping, PPA or frequency signoff',
                LN_E01='fixed v1 local exception unchanged; six historical quality failures retained',SOURCE_E01='OPEN; no new history recovered')
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    evidence={}
    keep={'verification.json','source_manifest.json','toolchain.json','input_hashes.json','register_inventory.json','tools.jsonl'}
    for path in out.rglob('*'):
        if not path.is_file():continue
        rel=path.relative_to(out);parts=rel.parts
        if parts[0] in required or parts[0]=='source' or str(rel) in keep:
            if path.suffix in ['.vvp','.exe'] or path.name.endswith('trace.txt') or path.name=='tools.jsonl':continue
            evidence[rel.as_posix()]=sha(path)
    (out/'evidence_manifest.json').write_text(json.dumps(dict(sha256=evidence),indent=2));print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':check(Path(sys.argv[1]).resolve())
