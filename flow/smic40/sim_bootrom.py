# =============================================================================
# sim_bootrom.py -- run the generated boot ROM on a minimal RV32I interpreter
#
# Purpose: catch instruction-encoding and control-flow bugs of the SoC driver
# BEFORE it is pushed to the VNC-only server. The interpreter executes the
# exact words emitted by mk_bootrom.py and talks to a model of
# kwt1_mmio + kwt1_accel that implements the same handshake contract:
#
#   frame write (0x08)  -> selects common (bit8) or layer packet
#   cfg write   (0x10)  -> one coefficient word, last one flagged by 0x0C
#   input write (0x14)  -> one of 1584 input words, 6336 bytes total
#   start       (0x00)  -> RUN layer 0
#   0x04 status         -> busy done error common_valid input_loaded
#                          layer_valid need_parameters ... start_ready
#                          frame_ready cfg_ready input_ready out_valid
#   0x18 output read    -> one of 1584 result words (last one acks -> done)
#
# Every coefficient word the driver sends is compared against the fixture it
# should have read from the external memory, so a wrong pointer, stride or
# counter shows up as a data mismatch instead of a hang.
# =============================================================================
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FIX = os.path.join(ROOT, "deliverables", "local_port_20261103", "fixtures")

N_COMMON, N_LAYER, N_IO = 4144, 15432, 1584

MMIO_BASE = 0x1100_0000
SHMEM_BASE = 0xa000_0000
DTCM_BASE  = 0x9000_0000
COMMON_OFF = 0x0000_1000
INPUT_OFF  = 0x0002_0000
LEASE_OFF  = 0x0002_4000

# ------------------------------------------------------------------ program --
ROM = {}


def load_rom():
    """Read the generated bootrom.hex (8 words per line)."""
    p = os.path.join(ROOT, "rtl", "integration", "soc", "bootrom.hex")
    n = 0
    for line in open(p):
        for w in line.split():
            ROM[0x1000 + 4 * n] = int(w, 16)
            n += 1
    return n


def load_hex(path):
    out = []
    for line in open(path):
        s = line.strip()
        if s and not s.startswith("//"):
            out.append(int(s, 16) & 0xFFFFFFFF)
    return out


# ------------------------------------------------------------------- memory --
class Mem:
    def __init__(self):
        self.d = {}

    def rd(self, a):
        return self.d.get(a & 0xFFFF_FFFC, 0)

    def wr(self, a, v):
        self.d[a & 0xFFFF_FFFC] = v & 0xFFFFFFFF


class Accel:
    """Behaves like kwt1_mmio+kwt1_accel at the register level."""

    def __init__(self, common, layers, inp, trace=False):
        self.common, self.layers, self.inp = common, layers, inp
        self.trace = trace
        self.reset()
        self.errors = []
        self.packets = []          # (kind, frame, words)

    def reset(self):
        self.common_ok = self.input_ok = self.layer_ok = False
        self.input_bytes = 0
        self.busy = self.done = self.error = False
        self.frame = None          # current packet descriptor
        self.cfg_n = 0
        self.need_params = False
        self.cur_layer = 0
        self.run_left = 0
        self.out_left = 0
        self.out_sent = 0
        self.last_flag = 0

    # ---- helpers ---------------------------------------------------------
    def _expect_words(self):
        return N_COMMON if self.frame["common"] else N_LAYER

    def _src(self):
        if self.frame["common"]:
            return self.common
        return self.layers[self.frame["layer"]]

    def status(self):
        v = 0
        v |= 1 << 0 if self.busy else 0
        v |= 1 << 1 if self.done else 0
        v |= 1 << 2 if self.error else 0
        v |= 1 << 3 if self.common_ok else 0
        v |= 1 << 4 if self.input_ok else 0
        v |= 1 << 5 if self.layer_ok else 0
        v |= 1 << 6 if self.need_params else 0
        v |= 1 << 8 if not self.busy else 0          # start_ready
        v |= 1 << 9 if self.frame is None else 0     # frame_ready
        v |= 1 << 10 if self.frame is not None else 0  # cfg_ready
        v |= 1 << 11 if self.frame is None and not self.input_ok else 0
        v |= 1 << 12 if self.out_left > 0 else 0
        v |= (self.cur_layer & 0xF) << 16
        return v

    def tick(self):
        """One accelerator cycle of progress (called per instruction)."""
        if self.busy and self.run_left > 0:
            self.run_left -= 1
            if self.run_left == 0:
                if self.cur_layer < 11:
                    self.cur_layer += 1
                    self.need_params = True
                else:
                    self.out_left = N_IO

    # ---- bus -------------------------------------------------------------
    def write(self, off, data):
        if off == 0x00:
            if data & 2:
                self.reset()
                self.packets.append(("abort", 0, 0))
            elif data == 1:
                if not (self.common_ok and self.input_ok and self.layer_ok):
                    self.errors.append("start without common/input/layer0 ready")
                self.busy = True
                self.run_left = 400
        elif off == 0x08:
            self.frame = {"common": bool(data & 0x100), "layer": data & 0xF}
            self.cfg_n = 0
            self.packets.append((("common" if data & 0x100 else "layer%d" % (data & 0xF)), data, 0))
        elif off == 0x0C:
            self.last_flag = data & 1
        elif off == 0x10:
            if self.frame is None:
                self.errors.append("cfg write without frame")
                return
            src = self._src()
            n = self.cfg_n
            if n < len(src) and data != src[n]:
                self.errors.append("packet %s word %d = %08x, expected %08x"
                                   % (self.packets[-1][0], n, data, src[n]))
            self.cfg_n += 1
            last = (self.cfg_n == self._expect_words())
            if last != bool(self.last_flag):
                self.errors.append("last flag %d at word %d/%d"
                                   % (self.last_flag, self.cfg_n, self._expect_words()))
            self.last_flag = 0
            if last:
                if self.frame["common"]:
                    self.common_ok = True
                else:
                    if self.frame["layer"] == self.cur_layer:
                        self.layer_ok = True
                        self.need_params = False
                        self.run_left = 400       # KICK + RUN this layer
                    else:
                        self.errors.append("layer packet %d while expecting %d"
                                           % (self.frame["layer"], self.cur_layer))
                self.packets[-1] = (self.packets[-1][0], self.packets[-1][1], self.cfg_n)
                self.frame = None
        elif off == 0x14:
            n = self.input_bytes // 4
            if n < len(self.inp) and data != self.inp[n]:
                self.errors.append("input word %d = %08x, expected %08x" % (n, data, self.inp[n]))
            self.input_bytes += 4
            last = (self.input_bytes == 6336)
            if last != bool(self.last_flag):
                self.errors.append("input last flag %d at byte %d" % (self.last_flag, self.input_bytes))
            self.last_flag = 0
            if last:
                self.input_ok = True
                self.busy = False        # stays IDLE until start
        else:
            self.errors.append("write to unmapped MMIO offset %02x" % off)

    def read(self, off):
        if off == 0x04:
            return self.status()
        if off == 0x18:
            if self.out_left == 0:
                self.errors.append("output read while out_valid=0")
                return 0
            v = self.out_left & 0xFFFFFFFF
            self.out_left -= 1
            self.out_sent += 1
            if self.out_left == 0:
                self.done = True
                self.busy = False
            return v
        if off == 0x48:
            return 0x4B575431
        return 0



class Shmem:
    """512 KiB shared SRAM plus the platform parameter loader (mailbox)."""

    def __init__(self, common, layers, inp):
        self.d = {}
        self.layers = layers
        for i, v in enumerate(common):
            self.d[SHMEM_BASE + COMMON_OFF + 4 * i] = v
        for i, v in enumerate(inp):
            self.d[SHMEM_BASE + INPUT_OFF + 4 * i] = v
        self.resident = -1
        self.load_layer(0)
        self.d[SHMEM_BASE] = 1          # seq 1: common + input + layer0 ready

    def load_layer(self, k):
        for i, v in enumerate(self.layers[k]):
            self.d[SHMEM_BASE + LEASE_OFF + 4 * i] = v
        self.resident = k

    def rd(self, a):
        return self.d.get(a & 0xFFFF_FFFC, 0)

    def wr(self, a, v):
        a &= 0xFFFF_FFFC
        v &= 0xFFFFFFFF
        if a == SHMEM_BASE + 4:         # CPU ack -> host reloads the lease
            self.d[a] = v
            if v < len(self.layers):
                self.load_layer(v)
                self.d[SHMEM_BASE] = v + 1
            return
        self.d[a] = v


# --------------------------------------------------------------- RV32I core --
class CPU:
    def __init__(self, accel, ext, dtcm, rom):
        self.r = [0] * 32
        self.pc = 0x1000
        self.accel, self.ext, self.dtcm, self.rom = accel, ext, dtcm, rom
        self.n = 0

    def _load(self, a):
        if 0x1000 <= a < 0x2000:
            return self.rom.get(a & ~3, 0x13)
        if a >= MMIO_BASE and a < MMIO_BASE + 0x10000:
            return self.accel.read(a & 0xFFFF)
        if SHMEM_BASE <= a < SHMEM_BASE + 0x8_0000:
            return self.ext.rd(a)
        if a >= DTCM_BASE:
            return self.dtcm.rd(a)
        raise RuntimeError("load from unmapped 0x%08x (pc=0x%08x)" % (a, self.pc))

    def _store(self, a, v):
        if a >= MMIO_BASE and a < MMIO_BASE + 0x10000:
            self.accel.write(a & 0xFFFF, v)
        elif SHMEM_BASE <= a < SHMEM_BASE + 0x8_0000:
            self.ext.wr(a, v)
        elif a >= DTCM_BASE:
            self.dtcm.wr(a, v)
        else:
            raise RuntimeError("store to unmapped 0x%08x (pc=0x%08x)" % (a, self.pc))

    def step(self):
        w = self._load(self.pc)
        op = w & 0x7F
        rd = (w >> 7) & 0x1F
        f3 = (w >> 12) & 0x7
        rs1 = (w >> 15) & 0x1F
        rs2 = (w >> 20) & 0x1F
        f7 = (w >> 25) & 0x7F
        imm_i = (w >> 20) & 0xFFF
        if imm_i & 0x800:
            imm_i -= 0x1000
        imm_s = (((w >> 25) & 0x7F) << 5) | ((w >> 7) & 0x1F)
        if imm_s & 0x800:
            imm_s -= 0x1000
        imm_b = (((w >> 31) & 1) << 12) | (((w >> 7) & 1) << 11) | (((w >> 25) & 0x3F) << 5) | \
                (((w >> 8) & 0xF) << 1)
        if imm_b & 0x1000:
            imm_b -= 0x2000
        imm_j = (((w >> 31) & 1) << 20) | (((w >> 12) & 0xFF) << 12) | \
                (((w >> 20) & 1) << 11) | (((w >> 21) & 0x3FF) << 1)
        if imm_j & 0x100000:
            imm_j -= 0x200000

        npc = self.pc + 4
        if op == 0x37:                                  # lui
            self.r[rd] = (w & 0xFFFFF000)
        elif op == 0x13:                                # addi / andi / srli
            a = self.r[rs1]
            if f3 == 0:
                self.r[rd] = (a + imm_i) & 0xFFFFFFFF
            elif f3 == 7:
                self.r[rd] = a & imm_i
            elif f3 == 5:
                self.r[rd] = (a >> ((w >> 20) & 0x1F)) & 0xFFFFFFFF
            else:
                raise RuntimeError("unsupported OP-IMM f3=%d" % f3)
        elif op == 0x33:                                # add
            assert f3 == 0 and f7 == 0
            self.r[rd] = (self.r[rs1] + self.r[rs2]) & 0xFFFFFFFF
        elif op == 0x03:                                # lw
            self.r[rd] = self._load((self.r[rs1] + imm_i) & 0xFFFFFFFF)
        elif op == 0x23:                                # sw
            self._store((self.r[rs1] + imm_s) & 0xFFFFFFFF, self.r[rs2])
        elif op == 0x63:                                # beq / bne
            a, b = self.r[rs1], self.r[rs2]
            if (f3 == 0 and a == b) or (f3 == 1 and a != b):
                npc = self.pc + imm_b
        elif op == 0x6F:                                # jal
            if rd:                                      # x0 must stay 0
                self.r[rd] = self.pc + 4
            npc = self.pc + imm_j
        elif op == 0x67:                                # jalr
            t = self.pc + 4
            npc = (self.r[rs1] + imm_i) & 0xFFFFFFFE
            if rd:
                self.r[rd] = t
        else:
            raise RuntimeError("unsupported opcode 0x%02x at 0x%08x (word %08x)"
                               % (op, self.pc, w))

        if rd != 0:
            self.r[rd] &= 0xFFFFFFFF
        self.pc = npc & 0xFFFFFFFF
        self.n += 1
        self.accel.tick()


def main():
    n = load_rom()
    print("ROM words: %d" % n)

    common = load_hex(os.path.join(FIX, "common.bin.hex"))
    layers = [load_hex(os.path.join(FIX, "layer_%02d.bin.hex" % c)) for c in range(12)]
    inp = load_hex(os.path.join(FIX, "input_000.hex"))

    ext = Shmem(common, layers, inp)

    accel = Accel(common, layers, inp)
    dtcm = Mem()
    cpu = CPU(accel, ext, dtcm, ROM)

    limit = 40_000_000
    while cpu.n < limit:
        cpu.step()
        if dtcm.rd(DTCM_BASE + 4 * N_IO) == 0x5A5:   # marker written
            break
    else:
        print("TIMEOUT after %d instructions, pc=0x%08x" % (cpu.n, cpu.pc))
        return 1

    print("instructions: %d" % cpu.n)
    print("packets:")
    for kind, frame, words in accel.packets:
        print("  %-9s frame=%-4d words=%d" % (kind, frame, words))
    print("input bytes : %d" % accel.input_bytes)
    print("outputs sent: %d, remaining %d, done=%s" % (accel.out_sent, accel.out_left, accel.done))
    print("DTCM[1584]  : 0x%08x" % dtcm.rd(DTCM_BASE + 4 * N_IO))
    print("DTCM[0],[1] : 0x%08x 0x%08x" % (dtcm.rd(DTCM_BASE), dtcm.rd(DTCM_BASE + 4)))

    ok = True
    if accel.errors:
        ok = False
        print("ERRORS (%d):" % len(accel.errors))
        for e in accel.errors[:12]:
            print("   ", e)
    if dtcm.rd(DTCM_BASE + 4 * N_IO) != 0x5A5:
        ok = False
        print("marker missing")
    if accel.out_sent != N_IO:
        ok = False
    print("BOOTROM PROGRAM: %s" % ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
