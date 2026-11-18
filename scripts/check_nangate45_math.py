"""Native Linux mapping and frozen arithmetic-vector regression, isolated output.

Only kwt_math is library mapped in this test. The other tested units remain RTL.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    out = a.output.resolve()
    assert not out.exists(), 'Use new output'
    out.mkdir(parents=True)
    lib = ROOT / 'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    sources = [ROOT / p for p in ['rtl/micro/mul_pipe.sv', 'rtl/micro/rne_pipe.sv',
               'rtl/v2/kwt_math.sv', 'rtl/v2/kwt_iterative.sv', 'rtl/v2/kwt_mac8x8.sv',
               'rtl/v2/kwt_sram_sp.sv', 'rtl/v2/tb_units.sv']]
    bindings = {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}
    versions = {}
    def run(args, name):
        p = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True, text=True)
        (out / (name + '.log')).write_text(p.stdout + p.stderr)
        assert p.returncode == 0, (name, p.returncode, p.stderr[-1500:])
        return p.stdout
    for tool in ['yosys', 'iverilog', 'vvp']:
        path = Path(shutil.which(tool))
        versions[tool] = dict(path=str(path), sha256=sha(path))
    flow = f'''read_verilog -sv {" ".join(str(p) for p in sources[:3])}
synth -top kwt_math -flatten -noabc -noshare
read_liberty -lib {lib}
dfflibmap -liberty {lib}
abc -liberty {lib} -D 6667
clean
check -assert
write_verilog -noattr -noexpr {out}/math_mapped.v
stat -liberty {lib}
design -reset
read_liberty -ignore_miss_func -ignore_miss_dir {lib}
write_verilog -noattr {out}/functional_cells.v
'''
    (out / 'math.ys').write_text(flow)
    run(['yosys', '-Q', '-T', '-s', out / 'math.ys'], 'mapping')
    for name in ['math.txt', 'iter.txt']:
        shutil.copyfile(ROOT / 'testdata/rtl_v1/release/unit' / name, out / name)
    run(['iverilog', '-g2012', '-DKWT_SIM', '-s', 'tb_units', '-o', out / 'test.vvp',
         out / 'math_mapped.v', out / 'functional_cells.v', *sources[3:]], 'compile')
    result = run(['vvp', out / 'test.vvp', '+root=' + str(out)], 'simulation')
    assert 'PASS math=2592 iterative=640 PE=64 SRAM=1 resets=5' in result, result
    for name, digest in bindings.items():
        assert sha(ROOT / name) == digest
    summary = dict(passed=True, library_mapped_unit='kwt_math', mapped_math_vectors=2592,
                   other_units='iterative/PE/SRAM remain RTL', result=result,
                   cell_models='Functional Verilog derived from the same Liberty by Yosys; no SDF',
                   whole_accelerator_equivalence=False, timing_signoff=False,
                   source_sha256=bindings, library_sha256=sha(lib), tools=versions,
                   script_sha256=sha(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2))
    (out / 'manifest.json').write_text(json.dumps({p.name: sha(p) for p in out.iterdir() if p.is_file()}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
