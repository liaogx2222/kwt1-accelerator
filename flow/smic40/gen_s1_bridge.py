# -*- coding: utf-8 -*-
"""Generate s1_icb_bridge.py: deploys icb2kwt.sv + tb_icb_bridge.sv into kwt1_chip.

Uses @@ICB@@ / @@TB@@ placeholders so the Verilog source never has to be
escaped inside the Python template.
"""
import io, os, py_compile

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(BASE))          # .../keyword-transformer

icb = io.open(os.path.join(REPO, "rtl/integration/soc/icb2kwt.sv"),
              "r", encoding="utf-8", newline="").read()
tb = io.open(os.path.join(REPO, "rtl/integration/soc/tb_icb_bridge.sv"),
             "r", encoding="utf-8", newline="").read()

icb = icb.replace("\r\n", "\n").replace("\r", "\n")
tb = tb.replace("\r\n", "\n").replace("\r", "\n")

# the delimiter used by the template must not occur inside the payloads
DELIM = "'''"
assert DELIM not in icb, "icb2kwt.sv contains '''"
assert DELIM not in tb, "tb_icb_bridge.sv contains '''"

TEMPLATE = """# -*- coding: utf-8 -*-
import io, os, sys, stat

ROOT = os.environ.get("KWT1_CHIP", "/home/2026contest/server6/s6_43usr/Desktop/project/kwt1_chip")
if not os.path.isdir(ROOT):
    print("MISS_ROOT", ROOT)
    sys.exit(1)

NEED_RTL = ["mul_pipe.sv", "rne_pipe.sv", "kwt_sram_sp.sv", "kwt_mac8x8.sv",
            "kwt_iterative.sv", "kwt_math.sv", "kwt_packet_loader.sv",
            "kwt_layer_banked.sv", "kwt1_accel.sv", "kwt1_mmio.sv"]
accel = os.path.join(ROOT, "rtl", "accel")
have = set(os.listdir(accel)) if os.path.isdir(accel) else set()
miss = [n for n in NEED_RTL if n not in have]
if miss:
    print("MISS_RTL", " ".join(miss))
    sys.exit(1)

for rel in ("rtl/soc", "tb", "sim/icb"):
    d = os.path.join(ROOT, rel)
    if not os.path.isdir(d):
        os.makedirs(d)
        print("MKDIR", rel)

ICB2KWT = '''@@ICB@@'''

TB = '''@@TB@@'''

FLIST = '''+incdir+../../rtl/accel/generated
../../rtl/accel/mul_pipe.sv
../../rtl/accel/rne_pipe.sv
../../rtl/accel/kwt_sram_sp.sv
../../rtl/accel/kwt_mac8x8.sv
../../rtl/accel/kwt_iterative.sv
../../rtl/accel/kwt_math.sv
../../rtl/accel/kwt_packet_loader.sv
../../rtl/accel/kwt_layer_banked.sv
../../rtl/accel/kwt1_accel.sv
../../rtl/accel/kwt1_mmio.sv
../../rtl/soc/icb2kwt.sv
../../tb/tb_icb_bridge.sv
'''

RUN = '''#!/bin/bash
# S1: stand-alone ICB bridge test. No CPU, no firmware, no linker script.
# 150 MHz, behavioural SRAM (KWT_TECH_SRAM undefined), ~10 us of simulation.
set -e
cd "$(dirname "$0")"
vcs -full64 -sverilog +v2k -timescale=1ns/1ps -error+50 +define+KWT_SIM -f filelist.f -o simv_icb -l compile_icb.log
./simv_icb | tee run_icb.log
'''

total = 0

def put(rel, text, exec_bit=False):
    global total
    p = os.path.join(ROOT, rel)
    io.open(p, "w", newline="\\n").write(text)
    n = len(text.encode("utf-8"))
    total += n
    if exec_bit:
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print("WROTE %-26s %6d B" % (rel, n))

put("rtl/soc/icb2kwt.sv",  ICB2KWT)
put("tb/tb_icb_bridge.sv", TB)
put("sim/icb/filelist.f",  FLIST)
put("sim/icb/run_icb.sh",  RUN, exec_bit=True)

print("DONE files=4 bytes=%d" % total)
"""

out = TEMPLATE.replace("@@ICB@@", icb).replace("@@TB@@", tb)
assert "\r" not in out, "CRLF leaked into generated script"

dst = os.path.join(BASE, "s1_icb_bridge.py")
io.open(dst, "w", newline="\n", encoding="utf-8").write(out)
py_compile.compile(dst, doraise=True)

print("generated s1_icb_bridge.py  %d bytes  PY_OK" % len(out.encode("utf-8")))
print("  icb2kwt.sv %d B   tb_icb_bridge.sv %d B" % (len(icb.encode("utf-8")), len(tb.encode("utf-8"))))
