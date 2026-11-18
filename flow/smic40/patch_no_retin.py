import io, glob, re
lib = "/storage1/admin_public_dir/SRAM_Lib_2025/RAMSP4096X16/lib/RAMSP4096X16_ss_0p99v_0p99v_125c.lib"
p   = "/home/2026contest/server6/s6_43usr/Desktop/project/server_signoff_20261106/keyword-transformer/rtl/integration/smic40/kwt_tech_sram_4096x16.sv"
N = chr(10)
hits = glob.glob(lib)
if not hits:
    hits = glob.glob("/storage1/admin_public_dir/SRAM_Lib_2025/RAMSP4096X16/**/*ss_0p99v_0p99v_125c*.lib", recursive=True)
if not hits:
    print("STOP: cannot locate the ss corner .lib; nothing changed")
    raise SystemExit(3)
print("lib_used=" + hits[0])
t = io.open(hits[0], encoding="utf-8", errors="replace").read()
# Count only real PIN DECLARATIONS. A plain substring test is wrong here: the
# .lib `when` arcs read "RETIN !CEN !WEN[15] !GWEN" even though no such pin
# exists, so counting bare "RETIN" would always fire and block the patch.
pins = re.findall(r"pin\s*\(\s*RETIN\s*\)", t)
print("bare_RETIN_mentions=" + str(t.count("RETIN")))
print("pin_RETIN_declarations=" + str(len(pins)))
if pins:
    print("STOP: the .lib DOES declare pin(RETIN), so lc_shell dropped a pin when it built the .db.")
    print("      The fix is to rebuild the .db, not to edit RTL. Nothing changed.")
    raise SystemExit(4)

s = io.open(p, encoding="utf-8").read()
edits = [
    (True,
     "        .GWEN  (gwen_n)," + N + "        .RETIN (1'b1)",
     "        .GWEN  (gwen_n)"),
    (False,
     "    // The default (named) build is what dc_shell sees, where RETIN comes from" + N +
     "    // the .lib and binds normally.",
     "    // The default (named) build is what dc_shell sees. It has NINE pins -- the" + N +
     "    // timing .lib declares no RETIN -- so the else branch below must NOT" + N +
     "    // connect .RETIN. Linking it again gives Error-[LINK-5] on all 20" + N +
     "    // instances. See [E6] in the header."),
]
for req, a, b in edits:
    if a in s:
        s = s.replace(a, b, 1)
        print("edit_applied=" + a.strip().split(N)[0][:48])
    elif req:
        print("STOP: anchor not found; wrapper already patched or has diverged. Nothing changed.")
        raise SystemExit(5)
    else:
        print("edit_skipped_optional")
io.open(p, "w", encoding="utf-8", newline=N).write(s)
print("PATCHED: synthesis branch now has 9 named pins, no RETIN")
