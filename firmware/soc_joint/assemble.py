import argparse,json,re
from pathlib import Path
REG = {
    'x0': 0, 'ra': 1, 'sp': 2, 'gp': 3, 'tp': 4,
    't0': 5, 't1': 6, 't2': 7, 's0': 8, 's1': 9,
    'a0': 10, 'a1': 11, 'a2': 12, 'a3': 13, 'a4': 14, 'a5': 15,
    'a6': 16, 'a7': 17, 's2': 18, 's3': 19, 's4': 20, 's5': 21,
    's6': 22, 's7': 23, 's8': 24, 's9': 25, 's10': 26, 's11': 27,
    't3': 28, 't4': 29, 't5': 30, 't6': 31,
}

def r_type(f7, rs2, rs1, f3, rd, op):
    return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op

def i_type(imm, rs1, f3, rd, op):
    assert -2048 <= imm <= 2047, "imm out of range: %d" % imm
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op

def s_type(imm, rs2, rs1, f3, op):
    assert -2048 <= imm <= 2047, "imm out of range: %d" % imm
    imm &= 0xFFF
    return ((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | ((imm & 0x1F) << 7) | op

def b_type(imm, rs2, rs1, f3, op):
    assert -4096 <= imm <= 4094 and (imm & 1) == 0, "branch offset: %d" % imm
    imm &= 0x1FFF
    return (((imm >> 12) & 1) << 31) | (((imm >> 5) & 0x3F) << 25) | (rs2 << 20) | \
           (rs1 << 15) | (f3 << 12) | (((imm >> 1) & 0xF) << 8) | (((imm >> 11) & 1) << 7) | op

def u_type(imm20, rd, op):
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | op

def j_type(imm, rd, op):
    assert -1048576 <= imm <= 1048574 and (imm & 1) == 0, "jump offset: %d" % imm
    imm &= 0x1FFFFF
    return (((imm >> 20) & 1) << 31) | (((imm >> 1) & 0x3FF) << 21) | \
           (((imm >> 11) & 1) << 20) | (((imm >> 12) & 0xFF) << 12) | (rd << 7) | op

def reg(tok):
    t = tok.strip()
    if t in REG:
        return REG[t]
    if t.startswith('x') and t[1:].isdigit():
        return int(t[1:])
    raise ValueError("bad register %r" % tok)

def num(tok):
    t = tok.strip()
    return int(t, 0) if not re.fullmatch(r'-?\d+', t) else int(t, 10)

def parse_mem(s):
    m = re.fullmatch(r'(-?(?:0x[0-9a-fA-F]+|\d+))\((\w+)\)', s.strip())
    if not m:
        raise ValueError("bad memory operand %r" % s)
    return num(m.group(1)), reg(m.group(2))

def encode(text, a, labels):
    t = re.sub(r'\s+', ' ', text.replace(',', ' ')).strip().split(' ')
    op = t[0]
    if op == 'lui':
        # operand is the immediate FIELD value (imm[31:12]), i.e. "lui t0,
        # 0x11000" loads 0x1100_0000 -- same notation as the RISC-V manual.
        return u_type(num(t[2]), reg(t[1]), 0x37)
    if op in ('lw', 'sw'):
        imm, rs1 = parse_mem(t[2])
        if op == 'lw':
            return i_type(imm, rs1, 0x2, reg(t[1]), 0x03)
        return s_type(imm, reg(t[1]), rs1, 0x2, 0x23)
    if op == 'addi':
        return i_type(num(t[3]), reg(t[2]), 0x0, reg(t[1]), 0x13)
    if op == 'andi':
        return i_type(num(t[3]), reg(t[2]), 0x7, reg(t[1]), 0x13)
    if op == 'srli':
        return i_type(num(t[3]) & 0x1F, reg(t[2]), 0x5, reg(t[1]), 0x13)
    if op == 'add':
        return r_type(0x00, reg(t[3]), reg(t[2]), 0x0, reg(t[1]), 0x33)
    if op in ('beq', 'bne'):
        f3 = 0x0 if op == 'beq' else 0x1
        off = labels[t[3]] - a
        return b_type(off, reg(t[2]), reg(t[1]), f3, 0x63)
    if op == 'jal':
        off = labels[t[2]] - a
        return j_type(off, reg(t[1]), 0x6F)
    if op == 'jalr':
        imm, rs1 = parse_mem(t[2])
        return i_type(imm, rs1, 0x0, reg(t[1]), 0x67)
    if op in ('and','add'): return r_type(0,reg(t[3]),reg(t[2]),7 if op=='and' else 0,reg(t[1]),0x33)
    raise ValueError('unknown mnemonic %r' % op)

def assemble(source, output):
    labels, listing, pc = {}, [], 0x1000
    for line in Path(source).read_text().splitlines():
        line = line.split('#',1)[0].strip()
        if not line: continue
        if line.endswith(':'): labels[line[:-1]] = pc
        else: listing.append((pc,line)); pc += 4
    words = [encode(text,addr,labels) for addr,text in listing]
    assert len(words) <= 1024
    Path(output).write_text(''.join('%08x\n' % word for word in words))
    return dict(words=len(words),bytes=4*len(words),labels=labels,listing=listing)

if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--source',type=Path,default=Path(__file__).with_name('task.S'))
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    print(json.dumps(assemble(a.source,a.output),indent=2))
