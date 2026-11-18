import io
P = 'ramsp_a5a5.v'
KC = chr(82) + chr(69) + chr(84) + chr(49) + chr(78)
ST = '  initial force ' + KC + ' = 1;'
L = io.open(P).read().split(chr(10))
o = []
n = 0
for x in L:
    o.append(x)
    t = x.strip()
    if t.startswith('module RAMSP4096X16') and KC in x:
        o.append(ST)
        n += 1
if n == 0:
    print('NOT_PATCHED')
    raise SystemExit(1)
s2 = chr(10).join(o)
io.open(P, 'w', newline=chr(10)).write(s2)
print('PATCHED', n, 'bytes', len(s2))
