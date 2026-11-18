import io, re, sys
p = sys.argv[1]
D = set(sys.argv[2:])
L = io.open(p, encoding="utf-8", errors="replace").read().splitlines()
st = []
A = 1
K = []
for n, l in enumerate(L, 1):
    m = re.match(r"^\s*`(ifdef|ifndef|elsif|else|endif|define|undef)[ \t]*(\S*)", l)
    if m:
        k, v = m.group(1), m.group(2)
        if k in ("ifdef", "ifndef"):
            c = (v in D)
            if k == "ifndef":
                c = not c
            st.append([A, c])
            A = A and c
        elif k == "elsif" and st:
            pa, t = st[-1]
            c = (v in D) and not t
            st[-1][1] = t or c
            A = pa and c
        elif k == "else" and st:
            pa, t = st[-1]
            st[-1][1] = 1
            A = pa and not t
        elif k == "endif" and st:
            A = st.pop()[0]
        elif k == "define" and A:
            D.add(v)
        elif k == "undef" and A:
            D.discard(v)
        continue
    if A:
        K.append((n, l))
print("defines: %s" % (sorted(D) or "(none)"))
for n, l in K:
    if re.match(r"\s*module\s+RAMSP4096X16\b", l):
        print("%d: %s" % (n, l.strip()))
for n, l in K:
    if re.match(r"\s*(input|output|inout)\b", l):
        print("  %d: %s" % (n, l.strip()))
