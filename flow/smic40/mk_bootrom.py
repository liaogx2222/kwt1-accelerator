# =============================================================================
# mk_bootrom.py -- assemble the KWT-1 SoC boot ROM (RV32I, two-pass assembler)
#
# Emits
#   rtl/integration/soc/sirv_mrom_top.v   <- the file that is actually compiled
#                                            (drop-in for e203_hbirdv2's
#                                             rtl/e203/mems/sirv_mrom_top.v)
#   rtl/integration/soc/sirv_mrom.v       <- dead code, kept only so that the
#                                            filelist entry has a timescale
#
# Program (SoC-level 12-case regression, see tb/tb_soc.sv):
#
#   abort
#   common packet   4144 words @0x2000_1000, frame = 256   -> wait common_valid
#   layer 0 packet 15432 words @0x2001_0000, frame = 0     -> wait layer_valid
#   1584 input words @0x200E_0000 via reg 0x14             -> wait nothing
#   start
#   11 x (wait need_parameters -> layer packet -> wait layer_valid)
#   1584 output reads -> DTCM[0..1583], marker 0x5A5 -> DTCM[1584]
#
# Register budget (RV32I has exactly 7 temporaries, all are used):
#   t0 = MMIO 0x1100_0000     t1 = data pointer     t2 = word counter
#   t3 = temp / frame         t4 = DTCM pointer     t5 = layer / out counter
#   t6 = layer stride 61728 B
#
# MMIO register map (rtl/v2/kwt1_mmio.sv, byte offsets)
#   0x00 W start(1) / abort(2)      0x04 R status
#   0x08 W frame                    0x0C W last flag
#   0x10 W coefficient word         0x14 W input word
#   0x18 R output word              0x1C R {dbg_state,error_code}
#   0x48 R ID = 0x4B575431
# Status bits: 0 busy | 1 done | 2 error | 3 common_valid | 4 input_loaded |
#              5 layer_valid | 6 need_parameters | 7 awaiting_ack |
#              8 start_ready | 9 frame_ready | 10 cfg_ready | 11 input_ready |
#              12 out_valid
# =============================================================================
import os
import re

# --------------------------------------------------------------- encoders ---
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

REG = {
    'x0': 0, 'ra': 1, 'sp': 2, 'gp': 3, 'tp': 4,
    't0': 5, 't1': 6, 't2': 7, 's0': 8, 's1': 9,
    'a0': 10, 'a1': 11, 'a2': 12, 'a3': 13, 'a4': 14, 'a5': 15,
    'a6': 16, 'a7': 17, 's2': 18, 's3': 19, 's4': 20, 's5': 21,
    's6': 22, 's7': 23, 's8': 24, 's9': 25, 's10': 26, 's11': 27,
    't3': 28, 't4': 29, 't5': 30, 't6': 31,
}

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

# --------------------------------------------------------------- program ----
# Every entry is either  ("label", name)  or  ("insn", "asm text").
PROG = [
    ("insn", "lui  t0, 0x11000"),      # MMIO   0x1100_0000
    ("insn", "lui  t4, 0x90000"),      # DTCM   0x9000_0000
    ("insn", "lui  t6, 0xa0000"),      # shmem  0xa000_0000  (+0 host seq, +4 ack)
    ("insn", "lw   t3, 0x48(t0)"),     # accelerator ID (snooped by the TB)
    ("insn", "addi t3, x0, 2"),
    ("insn", "sw   t3, 0(t0)"),        # abort: clear stale task state

    # ---- wait until the platform loader has filled common+input+layer0 ----
    ("insn", "addi t5, x0, 1"),
    ("label", "wmb0"),
    ("insn", "lw   t3, 0(t6)"),        # seq written by the host
    ("insn", "bne  t3, t5, wmb0"),

    # ---- common packet: 4144 words from 0xa000_1000, frame = 256 ---------
    ("insn", "lui  t1, 0xa0001"),
    ("insn", "lui  t2, 0x1"),
    ("insn", "addi t2, t2, 48"),       # 4096 + 48 = 4144
    ("insn", "addi t3, x0, 256"),
    ("insn", "jal  ra, send_pkt"),
    ("label", "wcommon"),
    ("insn", "lw   t3, 4(t0)"),
    ("insn", "andi t3, t3, 8"),        # bit3 common_valid
    ("insn", "beq  t3, x0, wcommon"),

    # ---- layer 0 packet: 15432 words from the lease, frame = 0 -----------
    ("insn", "lui  t1, 0xa0024"),
    ("insn", "lui  t2, 0x4"),
    ("insn", "addi t2, t2, -952"),     # 16384 - 952 = 15432
    ("insn", "addi t3, x0, 0"),
    ("insn", "jal  ra, send_pkt"),
    ("label", "wlyr0"),
    ("insn", "lw   t3, 4(t0)"),
    ("insn", "andi t3, t3, 32"),       # bit5 layer_valid
    ("insn", "beq  t3, x0, wlyr0"),
    ("insn", "addi t3, x0, 1"),
    ("insn", "sw   t3, 4(t6)"),        # ack: layer 0 consumed, lease free

    # ---- 1584 input words from 0xa002_0000 through reg 0x14 --------------
    ("insn", "lui  t1, 0xa0020"),
    ("insn", "addi t2, x0, 1584"),
    ("insn", "jal  ra, send_inp"),

    # ---- start -----------------------------------------------------------
    ("insn", "addi t3, x0, 1"),
    ("insn", "sw   t3, 0(t0)"),

    # ---- layers 1..11: wait need_parameters, then wait for the next lease -
    ("insn", "addi t5, x0, 1"),
    ("label", "lnext"),
    ("insn", "lw   t3, 4(t0)"),
    ("insn", "andi t3, t3, 64"),       # bit6 need_parameters
    ("insn", "beq  t3, x0, lnext"),
    ("label", "wmb"),
    ("insn", "lw   t3, 0(t6)"),        # host seq must be k+1  <=>  seq-1 == k
    ("insn", "addi t3, t3, -1"),
    ("insn", "bne  t3, t5, wmb"),
    ("insn", "lui  t1, 0xa0024"),
    ("insn", "lui  t2, 0x4"),
    ("insn", "addi t2, t2, -952"),
    ("insn", "addi t3, t5, 0"),        # frame = current layer
    ("insn", "jal  ra, send_pkt"),
    ("label", "wly"),
    ("insn", "lw   t3, 4(t0)"),
    ("insn", "andi t3, t3, 32"),
    ("insn", "beq  t3, x0, wly"),
    ("insn", "addi t3, t5, 1"),
    ("insn", "sw   t3, 4(t6)"),        # ack
    ("insn", "addi t5, t5, 1"),
    ("insn", "addi t3, x0, 12"),
    ("insn", "bne  t5, t3, lnext"),

    # ---- drain 1584 output words into DTCM[0..1583] ----------------------
    ("insn", "addi t5, x0, 1584"),
    ("label", "drain"),
    ("insn", "lw   t3, 4(t0)"),
    ("insn", "srli t3, t3, 12"),
    ("insn", "andi t3, t3, 1"),        # bit12 out_valid
    ("insn", "beq  t3, x0, drain"),
    ("insn", "lw   t3, 24(t0)"),       # read-consume one output word
    ("insn", "sw   t3, 0(t4)"),
    ("insn", "addi t4, t4, 4"),
    ("insn", "addi t5, t5, -1"),
    ("insn", "bne  t5, x0, drain"),

    # ---- wait done, leave the magic marker at DTCM[1584] -----------------
    ("label", "wdone"),
    ("insn", "lw   t3, 4(t0)"),
    ("insn", "andi t3, t3, 2"),        # bit1 done
    ("insn", "beq  t3, x0, wdone"),
    ("insn", "addi t3, x0, 0x5A5"),
    ("insn", "sw   t3, 0(t4)"),        # DTCM[1584] = 0x5A5
    ("label", "spin"),
    ("insn", "jal  x0, spin"),

    # ---- send_pkt: t1 = source, t2 = words, t3 = frame -------------------
    ("label", "send_pkt"),
    ("insn", "sw   t3, 8(t0)"),        # frame; stalls until frame_ready
    ("insn", "addi t2, t2, -1"),       # send n-1 words, keep the last apart
    ("label", "pkt_loop"),
    ("insn", "lw   t3, 0(t1)"),
    ("insn", "sw   t3, 16(t0)"),       # stalls until cfg_ready
    ("insn", "addi t1, t1, 4"),
    ("insn", "addi t2, t2, -1"),
    ("insn", "bne  t2, x0, pkt_loop"),
    ("insn", "addi t3, x0, 1"),
    ("insn", "sw   t3, 12(t0)"),       # last flag applies to the next word
    ("insn", "lw   t3, 0(t1)"),
    ("insn", "sw   t3, 16(t0)"),
    ("insn", "addi t1, t1, 4"),
    ("insn", "jalr x0, 0(ra)"),

    # ---- send_inp: same, through reg 0x14 -------------------------------
    ("label", "send_inp"),
    ("insn", "addi t2, t2, -1"),
    ("label", "inp_loop"),
    ("insn", "lw   t3, 0(t1)"),
    ("insn", "sw   t3, 20(t0)"),       # stalls until input_ready
    ("insn", "addi t1, t1, 4"),
    ("insn", "addi t2, t2, -1"),
    ("insn", "bne  t2, x0, inp_loop"),
    ("insn", "addi t3, x0, 1"),
    ("insn", "sw   t3, 12(t0)"),
    ("insn", "lw   t3, 0(t1)"),
    ("insn", "sw   t3, 20(t0)"),
    ("insn", "addi t1, t1, 4"),
    ("insn", "jalr x0, 0(ra)"),
]

ROM_BASE = 0x1000

# ------------------------------------------------------------ assembler ----
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
    raise ValueError("unknown mnemonic %r" % op)

# pass 1: addresses
pc = ROM_BASE
labels, addrs = {}, []
for kind, v in PROG:
    if kind == 'label':
        labels[v] = pc
    else:
        addrs.append((pc, v))
        pc += 4

# pass 2: encode
words, listing = [], []
for pc, text in addrs:
    w = encode(text, pc, labels)
    words.append(w)
    listing.append((pc, w, text))

assert len(words) <= 1024, "program too large for the 1024-word ROM"


# ------------------------------------------------------------------ emit ---
import os as _os

OUT = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                    "rtl", "integration", "soc")

# 1) bootrom.hex -- the program itself, 8 words per line so that the whole
#    firmware can be shipped over a VNC paste in ~11 short lines.
hexpath = _os.path.join(OUT, "bootrom.hex")
with open(hexpath, "w", newline="\n") as f:
    for i in range(0, len(words), 8):
        f.write(" ".join("%08x" % w for w in words[i:i + 8]) + "\n")

# 2) sirv_mrom_top.v -- a tiny ROM that loads the hex at time 0
ROMV = """// =============================================================================
// sirv_mrom_top.v -- KWT-1 boot ROM wrapper  (GENERATED by mk_bootrom.py)
//
// Drop-in for e203_hbirdv2/rtl/e203/mems/sirv_mrom_top.v: same name,
// parameters and ports, so e203_subsys_mems.v needs no edit.
//
// The program is NOT baked into this file. It is loaded from bootrom.hex at
// time 0, so changing the firmware means shipping 11 lines of hex instead of
// re-sending a few thousand characters of Verilog over the VNC console.
//
//   +ROMHEX=<path>   override the file name (default: bootrom.hex, relative
//                    to the simulator's working directory)
//
// Unused words decode as addi x0,x0,0 so a runaway PC retires instead of
// taking an illegal-instruction trap.
// =============================================================================
`timescale 1ns/1ps

module sirv_mrom_top #(
    parameter AW = 12,
    parameter DW = 32,
    parameter DP = 1024
)(
  input              rom_icb_cmd_valid,
  output             rom_icb_cmd_ready,
  input  [AW-1:0]    rom_icb_cmd_addr,
  input              rom_icb_cmd_read,

  output             rom_icb_rsp_valid,
  input              rom_icb_rsp_ready,
  output             rom_icb_rsp_err,
  output [DW-1:0]    rom_icb_rsp_rdata,

  input              clk,
  input              rst_n
);

  reg [DW-1:0] mem [0:DP-1];
  integer i;
  string  hexfn;

  initial begin
    for (i = 0; i < DP; i = i + 1) mem[i] = 32'h0000_0013;
    if (!$value$plusargs("ROMHEX=%s", hexfn)) hexfn = "bootrom.hex";
    $readmemh(hexfn, mem);
    $display("[ROM] boot program loaded from %0s (%0d words)", hexfn, DP);
  end

  wire [DW-1:0] rom_dout = mem[rom_icb_cmd_addr[AW-1:2]];

  assign rom_icb_rsp_valid = rom_icb_cmd_valid;
  assign rom_icb_cmd_ready = rom_icb_rsp_ready;
  assign rom_icb_rsp_err   = ~rom_icb_cmd_read;
  assign rom_icb_rsp_rdata = rom_dout;

endmodule
"""
open(_os.path.join(OUT, "sirv_mrom_top.v"), "w", newline="\n").write(ROMV)

# 3) sirv_mrom.v -- dead code, kept only for the `timescale of the filelist
STUB = """// not instantiated in this build; see sirv_mrom_top.v
`timescale 1ns/1ps
module sirv_mrom #(parameter AW = 12, parameter DW = 32, parameter DP = 1024)(
  input [AW-1:2] rom_addr, output [DW-1:0] rom_dout);
  assign rom_dout = 32'h0000_0013;
endmodule
"""
open(_os.path.join(OUT, "sirv_mrom.v"), "w", newline="\n").write(STUB)

print("wrote %s (%d bytes, %d words)" % (hexpath, _os.path.getsize(hexpath), len(words)))
print("wrote %s" % _os.path.join(OUT, "sirv_mrom_top.v"))
print("wrote %s" % _os.path.join(OUT, "sirv_mrom.v"))
print()
print("word  addr   hex       asm")
for i, (pc, w, text) in enumerate(listing):
    print("%3d   %04X   %08X  %s" % (i, pc, w, text))
print()
print("labels:", ", ".join("%s=0x%04X" % (k, v) for k, v in sorted(labels.items(), key=lambda kv: kv[1])))
