# =============================================================================
# patch_gate_retin.py -- one-shot repair of the KWT-1 gate-level simulation env
# -----------------------------------------------------------------------------
# Root cause being fixed (established 2026-11-10):
#   dc_synth8/mapped.v instantiates RAMSP4096X16 with NINE pins.  The authorised
#   vendor model (SRAM_Lib_2025/.../verilog/RAMSP4096X16.v) has TEN ports: RETIN
#   is unconnected, hence Z.  The model's readWrite task then does
#       if (RETIN_int === 1'bx || RETIN_int === 1'bz) begin
#           failedWrite(0);  Q_int = {16{1'bx}};
#   and failedWrite writes {MEM_WIDTH{1'bx}} into EVERY row.  One access poisons
#   the whole array -> layer FSM goes X at ~85k cycles, exactly what we saw.
#
#   Second defect: the model's own array initialisation is guarded by
#   `ifdef INITIALIZE_MEMORY (line 223).  Without the define the array is never
#   initialised at all.
#
# What this script does (ONLY inside out/gate_sim, signoff artefacts untouched):
#   1. copy dc_synth8/mapped.v -> out/gate_sim/mapped_pu.v
#      and give all 20 macro instances .RETIN(1'b1)     (flip 1'b0 or insert)
#   2. copy the vendor model  -> out/gate_sim/ramsp_a5a5.v
#      and change the init constant {MEM_WIDTH{1'b0}} -> 128'hA5A5..A5
#      i.e. the SAME poison the RTL model kwt_sram_sp.sv uses under KWT_SIM
#   3. derive out/gate_sim/gnew.f from gate8.f
# Compile with +define+INITIALIZE_MEMORY so the patched init block is live.
# =============================================================================
import io, os, re, sys

ROOT = "/home/2026contest/server6/s6_43usr/Desktop/project"
GS   = ROOT + "/out/gate_sim"
NET  = ROOT + "/out/dc_synth8/mapped.v"
VM   = "/storage1/admin_public_dir/SRAM_Lib_2025/RAMSP4096X16/verilog/RAMSP4096X16.v"
Q    = chr(39)                      # single quote, cannot be typed inside csh easily


def rd(p):
    return io.open(p, encoding="latin-1").read()


def wr(p, s):
    io.open(p, "w", encoding="latin-1", newline="\n").write(s)


# ---------------------------------------------------------------- 1. netlist
if not os.path.exists(NET):
    print("STOP: netlist missing " + NET)
    sys.exit(3)
s = rd(NET)
n_inst = len(re.findall(r"RAMSP4096X16\s+u_\S+", s))
n0 = len(re.findall(r"\.RETIN\s*\(\s*1" + Q + r"b0\s*\)", s))
mode = "insert"
if n0:
    s2 = re.sub(r"\.RETIN\s*\(\s*1" + Q + r"b0\s*\)", ".RETIN(1" + Q + "b1)", s)
    mode = "flip0to1"
else:
    s2, n0 = re.subn(r"\.GWEN\s*\(", ".RETIN(1" + Q + "b1), .GWEN(", s)

n1 = len(re.findall(r"\.RETIN\s*\(\s*1" + Q + r"b1\s*\)", s2))
if n1 != 20:
    print("STOP: expected 20 RETIN ties after patch, got %d (instances=%d)" % (n1, n_inst))
    print("      netlist NOT written, nothing changed")
    sys.exit(5)
wr(GS + "/mapped_pu.v", s2)
print("NET   %s" % NET)
print("      instances=%d mode=%s retin_ties=%d bytes=%d" % (n_inst, mode, n1, len(s2)))

# ------------------------------------------------------------------ 2. model
m = rd(VM)
A5 = "128" + Q + "hA5A5A5A5A5A5A5A5A5A5A5A5A5A5A5A5"
m2, k2 = re.subn(r"\{MEM_WIDTH\{1" + Q + r"b0\}\}", A5, m)
if k2 == 0:
    print("STOP: init pattern {MEM_WIDTH{1'b0}} not found in the vendor model")
    sys.exit(4)
wr(GS + "/ramsp_a5a5.v", m2)
print("MODEL %s" % VM)
print("      init_rows_replaced=%d bytes=%d" % (k2, len(m2)))

# --------------------------------------------------------------- 3. filelist
src = rd(GS + "/gate8.f").splitlines()
out, seen_model, seen_net = [], False, False
for L in src:
    t = L.strip()
    if (not t) or t.startswith("#") or t.startswith("//"):
        continue
    b = os.path.basename(t).lower()
    if b.startswith("ramsp4096x16"):
        if not seen_model:
            out.append(GS + "/ramsp_a5a5.v")
            seen_model = True
        continue
    if b == "mapped.v":
        if not seen_net:
            out.append(GS + "/mapped_pu.v")
            seen_net = True
        continue
    if b == "tb_gate_tasks.sv":
        continue
    out.append(t)
out.append(GS + "/tb_gate_tasks.sv")

if not (seen_model and seen_net):
    print("STOP: gate8.f template did not contain both the macro model and mapped.v")
    sys.exit(6)
wr(GS + "/gnew.f", "\n".join(out) + "\n")
print("FLIST %s/gnew.f  (%d entries)" % (GS, len(out)))
for L in out:
    print("      " + L)
print("OK")
