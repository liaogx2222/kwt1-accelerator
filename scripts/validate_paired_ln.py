"""Reproduce paired-LN A/B from a Git baseline and frozen full-task fixtures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["rtl/micro/mul_pipe.sv", "rtl/micro/rne_pipe.sv"] + [
    "rtl/v2/" + n for n in ["kwt_sram_sp.sv", "kwt_mac8x8.sv", "kwt_iterative.sv",
    "kwt_math.sv", "kwt_packet_loader.sv", "kwt_layer_banked.sv", "kwt1_accel.sv",
    "kwt1_mmio.sv", "kwt1_observed.sv"]]
SUPPORT = ["rtl/v2/generated/kwt_profile.svh", "rtl/v2/sim_provider.cpp",
           "rtl/v2/driver/kwt1.c", "rtl/v2/driver/kwt1.h"]


def run(cmd, log):
    p = subprocess.run([str(x) for x in cmd], cwd=ROOT, capture_output=True, text=True)
    log.write_text(p.stdout + p.stderr, encoding="utf-8")
    if p.returncode:
        raise RuntimeError("command failed; see " + str(log))
    return p.stdout


def snapshot(dest, revision=None):
    dest.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in SOURCES + SUPPORT:
        data = subprocess.check_output(["git", "show", revision + ":" + name], cwd=ROOT) if revision else (ROOT/name).read_bytes()
        p = dest/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    (dest/"source_hashes.json").write_text(json.dumps(hashes, indent=2))
    return hashes


def build(src, out):
    out.mkdir(parents=True, exist_ok=True)
    vr = ROOT/"tools/rtl_v1_python/verilator"
    os.environ["VERILATOR_ROOT"] = str(vr)
    os.environ["ZIG_GLOBAL_CACHE_DIR"] = str(ROOT/"tools/zig-cache")
    exe = out/"sim.exe"
    run([vr/"bin/verilator_bin.exe", "--cc", "--no-timing", "--Wno-fatal",
         "-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC", "-DKWT_SIM", "-DPIPELINED",
         "-I"+str(src/"rtl/v2/generated"), "--top-module", "kwt1_observed",
         "--prefix", "Vkwt1_mmio", "--Mdir", out, *[src/n for n in SOURCES]], out/"verilate.log")
    run([ROOT/"tools/rtl_v1_python/ziglang/zig.exe", "c++", "-x", "c++", "-std=c++17", "-O1",
         "-I"+str(vr/"include"), "-I"+str(vr/"include/vltstd"), "-I"+str(out), "-o", exe,
         src/"rtl/v2/sim_provider.cpp", src/"rtl/v2/driver/kwt1.c", *sorted(out.glob("*.cpp")),
         vr/"include/verilated.cpp", vr/"include/verilated_threads.cpp"], out/"compile.log")
    return exe


def suite(exe, out, mode, faults=False, count=12):
    out.mkdir(parents=True, exist_ok=True)
    fixture = ROOT/"testdata/rtl_v2/release/v2_always"
    fh = {}
    for p in fixture.glob("*.hex"):
        shutil.copyfile(p, out/p.name)
        fh[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (out/"fixtures.json").write_text(json.dumps(fh, indent=2))
    (out/"cases.txt").write_text("".join("%d 0\n" % n for n in range(count)))
    text = run([exe, out, mode, 0, 0, 0, "faults" if faults else "none",
                "+metrics="+(out/"ledger.txt").as_posix()], out/"simulation.log")
    assert "PASS PROVIDER cases=%d codes=%d" % (count, count*6336) in text
    if faults:
        assert "six full recoveries" in text
    for n in range(count):
        assert (out/("provider_observed_%03d.hex" % n)).read_bytes() == (out/("expected_%03d.hex" % n)).read_bytes()
    sys.path.insert(0, str(ROOT/"scripts"))
    from validate_rtl_v2 import ledger
    groups = ledger(out/"ledger.txt", 1335360)
    (out/"ledger.json").write_text(json.dumps(groups, indent=2))
    rows = [list(map(int, line.split())) for line in (out/"provider_metrics.txt").read_text().splitlines()]
    assert all(r[8] == 13 and r[9] == 61728 for r in rows)
    print(out.name, text.strip().splitlines()[-1], flush=True)
    return rows


def extra(out):
    if out.exists():
        raise ValueError("extra evidence directory already exists")
    out.mkdir(parents=True)
    sys.path.insert(0, str(ROOT/"scripts"))
    from validate_rtl_v2 import build as layer_build, SOURCES as production, VR
    from rtl_v1_inventory import inventory
    exe = layer_build(out/"build")
    fixtures = ROOT/"testdata/rtl_v2/release/layer"
    for mode in ["layer", "reset"]:
        target = out/mode
        target.mkdir()
        frozen = {}
        for p in fixtures.glob("*.hex"):
            if not p.name.startswith("observed_"):
                shutil.copyfile(p, target/p.name)
                frozen[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
        (target/"fixtures.json").write_text(json.dumps(frozen, indent=2))
        shutil.copyfile(fixtures/"cases.txt", target/"cases.txt")
        if mode == "reset":
            (target/"cases.txt").write_text("0 0\n")
        text = run([exe, target, 1, *(["paired-stress"] if mode == "reset" else [])], target/"simulation.log")
        count = 1 if mode == "reset" else 24
        assert "PASS cases=%d codes=%d" % (count, count*6336) in text
        for n in range(count):
            assert (target/("observed_%03d.hex" % n)).read_bytes() == (target/("expected_%03d.hex" % n)).read_bytes()
        if mode == "reset":
            assert "execution_resets=11 paired_cache_resets=3" in text
    os.environ["VERILATOR_ROOT"] = str(VR)
    cmd = [VR/"bin/verilator_bin.exe", "--json-only", "--Wno-fatal", "-Wno-WIDTHEXPAND",
           "-Wno-WIDTHTRUNC", "-I"+str(ROOT/"rtl/v2/generated"), "--top-module", "kwt1_mmio",
           "--Mdir", out/"json", *production, ROOT/"rtl/v2/kwt1_mmio.sv"]
    run(cmd, out/"inventory.log")
    inv = inventory(out/"json/Vkwt1_mmio.tree.json", out/"register_inventory.json")
    result = dict(passed=True, layer_cases=24, boundary_profiles=12, layer_codes=24*6336,
                  execution_resets=11, paired_cache_resets=3, post_reset_layer_codes=6336,
                  register_bytes=inv["register_bytes_ceiling"], SRAM_macros=inv["SRAM_macros"],
                  sources=json.loads((out/"build/source_hashes.json").read_text()))
    (out/"summary.json").write_text(json.dumps(result, indent=2))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--baseline", default="ee42450")
    ap.add_argument("--extra-only", action="store_true")
    a = ap.parse_args()
    out = a.output.resolve()
    if a.extra_only:
        extra(out/"extra")
        return
    if out.exists():
        raise ValueError("choose a new output directory to preserve evidence")
    base_hash = snapshot(out/"baseline_source", a.baseline)
    new_hash = snapshot(out/"candidate_source")
    baseline = build(out/"baseline_source", out/"baseline_build")
    candidate = build(out/"candidate_source", out/"candidate_build")
    old = suite(baseline, out/"baseline_always", "always")
    new = suite(candidate, out/"candidate_always", "always")
    stress = suite(candidate, out/"candidate_stress", "stress", True)
    assert len(old) == len(new) == len(stress) == 12
    for b, c in zip(old, new):
        assert b[0] == c[0] and b[7] - c[7] == (b[6] - c[6])//2
    result = dict(passed=True, baseline_revision=a.baseline,
                  baseline_sources=base_hash, candidate_sources=new_hash,
                  baseline_metrics=old, candidate_metrics=new, stress_metrics=stress,
                  compared_codes=12*6336, stress_compared_codes=12*6336,
                  full_fault_recoveries=6, fault_recovery_codes=6*6336,
                  cycle_reduction=old[0][6]-new[0][6],
                  full_window_cycles=new[0][6], conditional_task_s_at_150MHz=150e6/new[0][6],
                  area_mm2=None, soc_power_mW=None, energy_uJ=None,
                  metric_scope="host MMIO provider cycles; not E203 instruction timing; candidate not mapped")
    (out/"summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if not isinstance(v, (list,dict))}, indent=2))
    extra(out/"extra")


if __name__ == "__main__":
    main()
