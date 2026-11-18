"""Python 3.6-compatible source/transfer integrity check. No EDA dependencies."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def check():
    manifest = json.loads((ROOT/"manifest.json").read_text())
    failures = []
    for name, expected in sorted(manifest["files"].items()):
        p = ROOT/name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected["sha256"]:
            failures.append(name)
    if failures:
        raise SystemExit("HASH_MISMATCH " + ", ".join(failures))
    print("KWT_PROJECT_VERIFIED files=%d source_revision=%s" %
          (len(manifest["files"]), manifest["git_revision"]))


def dc_manifest():
    netlist = ROOT/"build/dc/mapped.v"
    text = netlist.read_text(errors="replace")
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    if re.search(r"\b(?:GTECH\w*|SELECT_OP\w*)\b", text):
        raise SystemExit("UNMAPPED_GENERIC_NETLIST")
    if len(re.findall(r"^\s*RAMSP4096X16\s+", text, flags=re.M)) != 20:
        raise SystemExit("NETLIST_MACRO_COUNT_NOT_20")
    retention = re.findall(r"\.RET1N\s*\(\s*([^)]*)\)", text)
    if len(retention) != 20 or any(not value.strip() for value in retention):
        raise SystemExit("NETLIST_RET1N_CONNECTION_COUNT_NOT_20")
    bad_constants = {"0", "'0", "'x", "'z", "1'b0", "1'h0", "1'd0", "1'bx", "1'bz"}
    if any(value.strip().lower() in bad_constants for value in retention):
        raise SystemExit("NETLIST_RET1N_NON_NORMAL_CONSTANT")
    return dict(source_manifest_sha256=hashlib.sha256((ROOT/"manifest.json").read_bytes()).hexdigest(),
                netlist_sha256=hashlib.sha256(netlist.read_bytes()).hexdigest())


def check_dc():
    check()
    expected = json.loads((ROOT/"build/dc/netlist_manifest.json").read_text())
    if expected != dc_manifest():
        raise SystemExit("DC_SOURCE_OR_NETLIST_MISMATCH")
    print("KWT_NETLIST_VERIFIED " + expected["netlist_sha256"])


def preflight():
    for var in ["KWT_PDK_ROOT", "KWT_SRAM_DB_DIR"]:
        if not os.environ.get(var):
            raise SystemExit("MISSING_ENV " + var)
    pdk, sram = Path(os.environ["KWT_PDK_ROOT"]), Path(os.environ["KWT_SRAM_DB_DIR"])
    corners = [("ss_v0p99_125c", "ss_0p99v_0p99v_125c"),
               ("ff_v1p21_-40c", "ff_1p21v_1p21v_m40c"),
               ("tt_v1p1_25c", "tt_1p10v_1p10v_25c")]
    files = []
    for std, ram in corners:
        for vt in ["HVT", "LVT", "RVT"]:
            files.append(pdk/("SCC40NLL_VHSC40_%s_V0.1" % vt)/
                         ("SCC40NLL_VHSC40_%s_V0p1" % vt)/"liberty/1.1v"/
                         ("scc40nll_vhsc40_%s_%s_basic.db" % (vt.lower(), std)))
        files.append(sram/("RAMSP4096X16_%s.db" % ram))
    for p in files:
        if not p.is_file() or p.stat().st_size == 0:
            raise SystemExit("MISSING_OR_EMPTY_LIBRARY " + str(p))
    print("KWT_LIBRARY_PREFLIGHT_OK files=%d" % len(files))


if __name__ == "__main__":
    if sys.argv[1:] == ["preflight"]:
        check()
        preflight()
        raise SystemExit(0)
    elif sys.argv[1:] == ["attest-dc"]:
        check()
        with (ROOT/"build/dc/netlist_manifest.json").open("x") as f:
            json.dump(dc_manifest(), f, indent=2)
        raise SystemExit(0)
    elif sys.argv[1:] == ["check-dc"]:
        check_dc()
        raise SystemExit(0)
    elif len(sys.argv) == 3 and sys.argv[1] == "check-saif":
        check_dc()
        saif = Path(sys.argv[2])
        expected = dc_manifest()["netlist_sha256"]
        records = (saif.parent/"inputs.sha256").read_text().splitlines()
        rows = [line.split() for line in records if line.split()[-1] == "build/dc/mapped.v"]
        if not saif.is_file() or saif.stat().st_size == 0 or len(rows) != 1 or rows[0][0] != expected:
            raise SystemExit("SAIF_NETLIST_MISMATCH")
        if not (saif.parent/"run.log").is_file() or "PASS KWT_GATE_TASK" not in (saif.parent/"run.log").read_text():
            raise SystemExit("SAIF_GATE_PASS_MISSING")
        print("KWT_SAIF_PROVENANCE_VERIFIED")
        raise SystemExit(0)
    elif len(sys.argv) == 3 and sys.argv[1] == "import-fixtures":
        manifest = json.loads((ROOT/"manifest.json").read_text())
        source = Path(sys.argv[2])
        # Validate every source before creating or copying any fixture.
        names = [n for n in manifest["files"] if n.startswith("fixtures/")]
        for name in names:
            p = source/Path(name).name
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != manifest["files"][name]["sha256"]:
                raise SystemExit("FIXTURE_SOURCE_MISMATCH " + name)
        for name in names:
            target = ROOT/name
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != manifest["files"][name]["sha256"]:
                raise SystemExit("REFUSE_OVERWRITE " + name)
        (ROOT/"fixtures").mkdir(exist_ok=True)
        for name in names:
            target = ROOT/name
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != manifest["files"][name]["sha256"]:
                    raise SystemExit("REFUSE_OVERWRITE " + name)
            else:
                shutil.copyfile(source/Path(name).name, target)
    elif sys.argv[1:] != ["check"]:
        raise SystemExit("usage: project.py check | import-fixtures <existing frozen fixture directory>")
    check()
