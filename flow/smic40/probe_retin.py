import io
P = 'ramsp_a5a5.v'
KL = 'RETIN'
KC = chr(82) + chr(69) + chr(84) + chr(73) + chr(78)
print('KL', [hex(ord(x)) for x in KL])
print('KC', [hex(ord(x)) for x in KC])
L = io.open(P).read().split(chr(10))
cs = set(i for i, x in enumerate(L) if 'RAMSP4096X16' in x)
print('n_ramsp', len(cs), sorted(cs))
for i in sorted(cs):
    x = L[i]
    print(i + 1, 'len', len(x), 'KL', KL in x, 'KC', KC in x,
          'tail', [hex(ord(c)) for c in x[-7:]])
ST = '  initial force ' + KC + ' = 1;'
o = []
n = 0
for i, x in enumerate(L):
    o.append(x)
    if i in cs and KC in x:
        o.append(ST)
        n += 1
if n == 0:
    print('NOT_PATCHED')
    raise SystemExit(1)
s2 = chr(10).join(o)
io.open(P, 'w', newline=chr(10)).write(s2)
print('PATCHED', n, 'bytes', len(s2))
