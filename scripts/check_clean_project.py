"""Exercise archive transfer, relocation, integrity and stale-netlist guards."""
import argparse
import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import zlib


def extract(data, dest):
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for item in tf.getmembers():
            p = PurePosixPath(item.name)
            assert not p.is_absolute() and ".." not in p.parts and item.isfile()
        tf.extractall(dest)


def command(project, args, success=True, env=None):
    p = subprocess.run([sys.executable, str(project/"flow/project.py"), *args], capture_output=True, text=True, env=env)
    assert (p.returncode == 0) == success, p.stdout + p.stderr
    return p.stdout + p.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    a = ap.parse_args()
    bundle, out = a.bundle.resolve(), a.output.resolve()
    if out.exists():
        raise ValueError("choose a fresh self-test directory")
    out.mkdir(parents=True)
    tm = json.loads((bundle/"transfer_manifest.json").read_text())
    parts = sorted((bundle/"transfer").glob("kwt_source.part*.txt"))
    assert len(parts) == tm["source_chunks"]
    for p in parts:
        assert hashlib.sha256(p.read_bytes()).hexdigest() == tm["chunk_sha256"][p.stem]
    rebuilt = zlib.decompress(base64.b64decode("".join(p.read_text() for p in parts)))
    assert rebuilt == (bundle/"source.tar.gz").read_bytes()
    for name in ["full.tar.gz", "source.tar.gz"]:
        data = (bundle/name).read_bytes()
        assert len(data) == tm["archives"][name]["bytes"]
        assert hashlib.sha256(data).hexdigest() == tm["archives"][name]["sha256"]
    source = out/"source"
    full = out/"full"
    extract(rebuilt, source)
    extract((bundle/"full.tar.gz").read_bytes(), full)
    logs = [command(full, ["check"])]
    logs.append(command(source, ["check"], False))
    logs.append(command(source, ["import-fixtures", str(full/"fixtures")]))
    env = dict(os.environ)
    env.pop("KWT_PDK_ROOT", None)
    env.pop("KWT_SRAM_DB_DIR", None)
    logs.append(command(source, ["preflight"], False, env))
    env["KWT_PDK_ROOT"] = str(out/"synthetic_pdk")
    env["KWT_SRAM_DB_DIR"] = str(out/"synthetic_sram")
    logs.append(command(source, ["preflight"], False, env))
    for p in (full/"flow").glob("*.py"):
        ast.parse(p.read_text(), feature_version=(3, 6))
    # Synthetic file only exercises provenance guards; it is NOT EDA evidence.
    dc = source/"build/dc"
    dc.mkdir(parents=True)
    netlist = dc/"mapped.v"
    synthetic = "// synthetic guard test, not EDA evidence\n" + "".join(
        "RAMSP4096X16 ram%d(.RET1N(1'b1));\n" % n for n in range(20))
    netlist.write_text(synthetic)
    logs.append(command(source, ["attest-dc"]))
    logs.append(command(source, ["check-dc"]))
    netlist.write_text(synthetic + "GTECH_AND2 invalid();\n")
    rejection = command(source, ["check-dc"], False)
    assert "UNMAPPED_GENERIC_NETLIST" in rejection
    logs.append(rejection)
    netlist.write_text(synthetic.replace(".RET1N(1'b1)", ".RET1N()", 1))
    rejection = command(source, ["check-dc"], False)
    assert "NETLIST_RET1N_CONNECTION_COUNT_NOT_20" in rejection
    logs.append(rejection)
    netlist.write_text(synthetic.replace(".RET1N(1'b1)", ".RET1N(1'b0)", 1))
    rejection = command(source, ["check-dc"], False)
    assert "NETLIST_RET1N_NON_NORMAL_CONSTANT" in rejection
    logs.append(rejection)
    netlist.write_text(synthetic + "// changed synthetic self-test input\n")
    logs.append(command(source, ["check-dc"], False))
    (full/"rtl/v2/kwt_layer_banked.sv").write_text("// tamper self-test\n")
    logs.append(command(full, ["check"], False))
    (out/"checks.log").write_text("\n".join(logs))
    report = dict(passed=True, source_chunks=len(parts), archives_verified=2,
                  source_fixture_import=True, python36_syntax=True,
                  modified_source_rejected=True, stale_netlist_rejected=True,
                  unmapped_netlist_rejected=True,
                  RET1N_open_or_low_rejected=True,
                  missing_env_rejected=True, missing_library_rejected=True,
                  synthetic_guard_checks_only=True, EDA_execution=False)
    (out/"summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
