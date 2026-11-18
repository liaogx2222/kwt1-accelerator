import io
import re
import sys

args = list(sys.argv[1:])
path = "/storage1/admin_public_dir/SRAM_Lib_2025/RAMSP4096X16/verilog/RAMSP4096X16.v"
if args and args[0].endswith(".v"):
    path = args.pop(0)
defs = set(args)

lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
stack = []
active = True
kept = []
directive = re.compile(r"^`(ifdef|ifndef|elsif|else|endif|define|undef)\b[ \t]*(\S*)")

for num, ln in enumerate(lines, 1):
    m = directive.match(ln.strip())
    if m:
        kw, name = m.group(1), m.group(2)
        if kw in ("ifdef", "ifndef"):
            cond = (name in defs)
            if kw == "ifndef":
                cond = not cond
            stack.append([active, cond])
            active = active and cond
        elif kw == "elsif":
            if stack:
                parent, taken = stack[-1]
                cond = (name in defs) and not taken
                stack[-1][1] = taken or cond
                active = parent and cond
        elif kw == "else":
            if stack:
                parent, taken = stack[-1]
                stack[-1][1] = True
                active = parent and not taken
        elif kw == "endif":
            if stack:
                parent, _ = stack.pop()
                active = parent
        elif kw == "define" and active and name:
            defs.add(name)
        elif kw == "undef" and active and name:
            defs.discard(name)
        continue
    if active:
        kept.append((num, ln))

print("file      : " + path)
print("total line: %d" % len(lines))
print("defines   : %s" % (", ".join(sorted(defs)) if defs else "(none)"))
print("active ln : %d" % len(kept))
print("")

mods = [(n, l) for n, l in kept if re.match(r"\s*module\s+", l)]
print("active module declarations (%d):" % len(mods))
for n, l in mods:
    print("  %d: %s" % (n, l.strip()))
print("")

target = [(n, l) for n, l in kept if re.match(r"\s*module\s+RAMSP4096X16\b", l)]
if not target:
    print("STOP: no active module named RAMSP4096X16")
    raise SystemExit(2)

for n, l in target:
    head = l.strip()
    ports = []
    m = re.search(r"\((.*)\)", head)
    if m:
        ports = [p.strip() for p in m.group(1).split(",") if p.strip()]
    print("RAMSP4096X16 at line %d" % n)
    print("  ports (%d): %s" % (len(ports), ", ".join(ports)))
    print("  has RETIN: %s" % ("YES" if "RETIN" in ports else "NO"))
    print("")

    body = []
    for n2, l2 in kept:
        if n2 <= n:
            continue
        if re.match(r"\s*endmodule\b", l2):
            break
        if re.match(r"\s*(input|output|inout)\b", l2):
            body.append((n2, l2.strip()))
    print("  declared inside body (%d):" % len(body))
    for n2, l2 in body:
        print("    %d: %s" % (n2, l2))
    print("")
