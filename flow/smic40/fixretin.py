import io
P = 'ramsp_a5a5.v'
K = 'RETIN'
s = io.open(P).read()
S = '  initial force ' + K + ' = 1;'
o = []
n = 0
for x in s.split(chr(10)):
    o.append(x)
    t = x.strip()
    if t.startswith('module RAMSP4096X16 (') and K in x:
        o.append(S)
        n += 1
if n == 0:
    print('NO_HIT lines=%d bytes=%d' % (len(s.split(chr(10))), len(s)))
    raise SystemExit(1)
s2 = chr(10).join(o)
io.open(P, 'w', newline=chr(10)).write(s2)
print('patched', n, 'retin_total', s2.count(K), 'bytes', len(s2))
