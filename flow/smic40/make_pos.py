import io
p = "/path/to/project/server_signoff_20261106/keyword-transformer/rtl/integration/smic40/kwt_tech_sram_4096x16.sv"
s = io.open(p, encoding="utf-8").read()
N = chr(10)
# RETIRED 2026-11-07: this script was used once to introduce the positional
# simulation branch. The wrapper now ships with that branch already in place
# (plus a nine-pin synthesis default), so re-running it would nest a second
# `ifdef inside the existing one and destroy the file. It refuses from now on.
if "`ifdef KWT_SIM_POSITIONAL" in s:
    print("STOP: wrapper already carries the KWT_SIM_POSITIONAL branch; nothing to do")
    raise SystemExit(0)
start = s.index("    RAMSP4096X16 u_ramsp4096x16 (")
end = s.index("    );", start) + len("    );")
block = [
    "`ifdef KWT_SIM_POSITIONAL",
    "    RAMSP4096X16 u_ramsp4096x16 (",
    "        rdata, clk, cen_n, wen_n, addr, wdata, 3'b010, 2'b00, gwen_n, 1'b1",
    "    );",
    "`else",
    "    RAMSP4096X16 u_ramsp4096x16 (",
    "        .Q     (rdata),",
    "        .CLK   (clk),",
    "        .CEN   (cen_n),",
    "        .WEN   (wen_n),",
    "        .A     (addr),",
    "        .D     (wdata),",
    "        .EMA   (3'b010),",
    "        .EMAW  (2'b00),",
    "        .GWEN  (gwen_n)",
    "    );",
    "`endif",
]
o = s[:start] + N.join(block) + s[end:]
io.open(p, "w", encoding="utf-8", newline=N).write(o)
print("patched wrapper,", len(o), "bytes")
