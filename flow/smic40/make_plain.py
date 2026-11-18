import io
p = "/home/2026contest/server6/s6_43usr/Desktop/project/server_signoff_20261106/keyword-transformer/rtl/integration/smic40/kwt_tech_sram_4096x16.sv"
s = io.open(p, encoding="utf-8").read()
N = chr(10)
i = s.index("        .GWEN  (gwen_n)")
j = s.index("    );", i) + len("    );")
new = "        .GWEN  (gwen_n)," + N + "        .RETIN (1'b1)" + N + "    );"
o = s[:i] + new + s[j:]
q = "/home/2026contest/server6/s6_43usr/Desktop/project/out/sc_v5/kwt_plain.sv"
io.open(q, "w", encoding="utf-8", newline=N).write(o)
print("written", q, len(o))
