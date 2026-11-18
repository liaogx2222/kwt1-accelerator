"""Portable tool discovery for new flows; frozen validation scripts stay intact."""
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = '.exe' if os.name == 'nt' else ''


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Tools:
    def __init__(self, config=None):
        self.cfg = json.loads(Path(config).read_text()) if config else {}

    def find(self, name, env=None, candidates=()):
        value = os.environ.get(env or 'KWT_' + name.upper().replace('-', '_')) or self.cfg.get(name)
        options = [value] if value else [shutil.which(name), *candidates]
        for item in options:
            if item:
                p = Path(item).expanduser()
                if not p.is_absolute():
                    p = Path(shutil.which(str(p)) or ROOT / p)
                if p.is_file():
                    return p.resolve()
        raise FileNotFoundError(f'{name} unavailable; set {env or "KWT_" + name.upper()} or a tools configuration')

    def iverilog(self):
        return self.find('iverilog', candidates=[ROOT/'tools/iverilog/bin'/('iverilog'+SUFFIX), Path('E:/project/FPGAcompetition/RISCV_CPU/tools/iverilog/bin/iverilog.exe')] if os.name == 'nt' else [])

    def vvp(self):
        return self.find('vvp', candidates=[self.iverilog().with_name('vvp'+SUFFIX)])

    def gcc(self):
        names = ['riscv32-unknown-elf-gcc', 'riscv-none-elf-gcc', 'riscv64-unknown-elf-gcc']
        candidates = [shutil.which(n) for n in names]
        if os.name == 'nt':
            candidates += [Path('E:/project/FPGAcompetition/RISCV_CPU/tools/xpack-toolchain/xpack-riscv-none-elf-gcc-15.2.0-1/bin/riscv32-unknown-elf-gcc.exe')]
        return self.find('riscv-gcc', 'KWT_RISCV_GCC', candidates)

    def binutil(self, name):
        gcc = self.gcc()
        return gcc.with_name(gcc.name.replace('gcc', name))

    def cxx(self):
        value = os.environ.get('KWT_CXX') or self.cfg.get('cxx')
        if value:
            return shlex.split(value, posix=os.name != 'nt')
        zig = ROOT/'tools/rtl_v1_python/ziglang'/('zig'+SUFFIX)
        return [str(zig), 'c++'] if zig.is_file() else [str(self.find('c++'))]

    def verilator(self):
        root = os.environ.get('VERILATOR_ROOT') or self.cfg.get('verilator_root')
        local = ROOT/'tools/rtl_v1_python/verilator'
        if not root and local.is_dir():
            root = str(local)
        exe = self.find('verilator', 'KWT_VERILATOR', [Path(root)/'bin'/('verilator_bin'+SUFFIX)] if root else [])
        if not root:
            result = subprocess.check_output([str(exe), '-V'], text=True)
            import re
            found = re.search(r'^\s*VERILATOR_ROOT\s*=\s*(\S+)', result, re.M)
            if not found:
                raise ValueError('Set VERILATOR_ROOT to locate the Verilator C++ runtime')
            root = found[1]
        root = Path(root).resolve()
        if not (root/'include/verilated.h').is_file():
            raise FileNotFoundError(f'Verilator runtime missing: {root}')
        return exe, root


def run(args, output, name='command'):
    args = [str(a) for a in args]
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    (Path(output)/(name+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'{name} exited {result.returncode}:\n{result.stdout[-3000:]}{result.stderr[-3000:]}')
    return result.stdout
