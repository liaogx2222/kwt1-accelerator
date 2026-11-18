"""Export a fresh, relocatable server project and VNC-safe transfer chunks."""
import argparse
import base64
import hashlib
import gzip
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
RTL = ["rtl/integration/smic40/kwt_tech_sram_4096x16.sv", "rtl/micro/mul_pipe.sv",
       "rtl/micro/rne_pipe.sv"] + ["rtl/v2/"+n for n in ["kwt_sram_sp.sv", "kwt_mac8x8.sv",
       "kwt_iterative.sv", "kwt_math.sv", "kwt_packet_loader.sv", "kwt_layer_banked.sv",
       "kwt1_accel.sv", "kwt1_mmio.sv"]]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive(files):
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tf:
            for name, data in sorted(files.items()):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0
                tf.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def gate_tb():
    text = (ROOT/"flow/smic40/tb_gate_tasks.sv").read_text()
    text, count = re.subn(r'^`define FIXDIR .*$', '', text, flags=re.M)
    assert count == 1
    text = text.replace('reg [8*260-1:0] fn;', 'reg [8*1024-1:0] fn; string fixture_dir, saif_dir;')
    text = text.replace('`FIXDIR', 'fixture_dir')
    mark = '    if (!$value$plusargs("CASE=%d", case_idx)) case_idx = 0;'
    assert text.count(mark) == 1
    text = text.replace(mark, '    if (!$value$plusargs("FIXTURES=%s", fixture_dir)) fixture_dir = "fixtures";\n'
                        '    if (!$value$plusargs("SAIF_DIR=%s", saif_dir)) saif_dir = ".";\n'+mark)
    text, count = re.subn(r'fn = \$sformatf\("/home/[^"\n]+/kwt1_gate_c%0d.saif", case_idx\);',
                         'fn = $sformatf("%0s/kwt1_gate_c%0d.saif", saif_dir, case_idx);', text)
    assert count == 1 and '/home/' not in text
    # A failed simulator must return nonzero, not just print a FAIL marker.
    text = text.replace('$display("FAIL KWT_GATE_TASK case=%0d errors=%0d mismatches=%0d", case_idx, errors, mism);',
                        '$fatal(1, "FAIL KWT_GATE_TASK case=%0d errors=%0d mismatches=%0d", case_idx, errors, mism);')
    return text.encode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--allow-dirty", action="store_true", help="development export only")
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise ValueError("output already exists; preserve it and use a new version")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    files = {name: (ROOT/name).read_bytes() for name in RTL + ["rtl/v2/generated/kwt_profile.svh"]}
    tracked = RTL + ["rtl/v2/generated/kwt_profile.svh", "flow/clean", "scripts/export_clean_project.py",
                     "flow/smic40/tb_gate_tasks.sv", "flow/smic40/tb_sram_contract.sv", "flow/review/ramsp4096x16_ret1n.v",
                     "flow/targets/smic40.server.sdc", "deliverables/local_port_20261103/fixtures"]
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--", *tracked], cwd=ROOT))
    if dirty and not a.allow_dirty:
        raise ValueError("commit the exported source/flow first, or explicitly use --allow-dirty for development")
    for p in sorted((ROOT/"flow/clean").iterdir()):
        if p.is_file():
            files["flow/"+p.name] = p.read_bytes().replace(b"\r\n", b"\n")
    files["flow/rtl_sources.txt"] = ("\n".join(RTL)+"\n").encode()
    files["flow/constraints.sdc"] = (ROOT/"flow/targets/smic40.server.sdc").read_bytes().replace(b"\r\n", b"\n")
    files["flow/tb_gate_tasks.sv"] = gate_tb()
    files["flow/tb_sram_contract.sv"] = (ROOT/"flow/smic40/tb_sram_contract.sv").read_bytes().replace(b"\r\n", b"\n")
    # Actual ten-port RET1N view; normal-mode functional contract, not vendor timing.
    files["flow/sram_contract_ret1n.v"] = (ROOT/"flow/review/ramsp4096x16_ret1n.v").read_bytes().replace(b"\r\n", b"\n")
    fixture = ROOT/"deliverables/local_port_20261103/fixtures"
    for p in sorted(fixture.glob("*.hex")):
        files["fixtures/"+p.name] = p.read_bytes()
    assert len([n for n in files if n.startswith("fixtures/")]) == 37
    manifest = dict(schema=1, git_revision=revision, development_dirty=dirty,
                    top="kwt1_mmio", numerical_contract="INTEGER_NUMERICS_V1",
                    private_macros=20, private_sram_bytes=20*4096*2,
                    macro_retention_pin="RET1N", macro_retention_normal_value=1,
                    reset_distribution=dict(max_fanout=32, max_transition_ns=0.400, scope="whole_accelerator_design"),
                    scope="accelerator partition; complete SoC PPA remains unmeasured",
                    files={n: dict(bytes=len(d), sha256=sha(d)) for n,d in sorted(files.items())})
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True)+"\n").encode()
    out.mkdir(parents=True)
    for name, data in files.items():
        target = out/"project"/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    # Source-only payload reuses fixtures only after per-file hash verification.
    payloads = {"full.tar.gz": archive(files),
                "source.tar.gz": archive({n:d for n,d in files.items() if not n.startswith("fixtures/")})}
    transfer = out/"transfer"
    transfer.mkdir()
    for name, data in payloads.items():
        (out/name).write_bytes(data)
    encoded = base64.b64encode(zlib.compress(payloads["source.tar.gz"], 9)).decode()
    chunks = [encoded[i:i+800] for i in range(0, len(encoded), 800)]
    # Type each command into the observed remote Linux terminal via VNC.
    # Fixed relative filenames prevent overwriting the old project.
    commands = []
    for i, part in enumerate(chunks):
        name = "kwt_source.part%04d" % i
        commands.append('python3 -c "open(\'%s\',\'w\').write(\'%s\')"' % (name, part))
        (transfer/(name+".txt")).write_text(part, encoding="ascii")
    commands.append('python3 -c "import glob,base64,zlib;open(\'source.tar.gz\',\'xb\').write(zlib.decompress(base64.b64decode(\'\'.join(open(p).read() for p in sorted(glob.glob(\'kwt_source.part[0-9][0-9][0-9][0-9]\'))))))"')
    commands.append("wc -c source.tar.gz")
    commands.append("sha256sum source.tar.gz")
    (transfer/"commands.csh.txt").write_text("\n".join(commands)+"\n", encoding="ascii")
    summary = dict(project_revision=revision, development_dirty=dirty, source_chunks=len(chunks),
                   archives={n: dict(bytes=len(d), sha256=sha(d)) for n,d in payloads.items()},
                   chunk_sha256={"kwt_source.part%04d" % i: sha(p.encode()) for i,p in enumerate(chunks)})
    (out/"transfer_manifest.json").write_text(json.dumps(summary, indent=2))
    subprocess.run([sys.executable, str(out/"project/flow/project.py"), "check"], check=True)
    print(json.dumps({k:v for k,v in summary.items() if k != "chunk_sha256"}, indent=2))


if __name__ == "__main__":
    main()
