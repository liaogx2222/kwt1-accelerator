"""Rebuild exported measured PIO firmware and require an identical load image."""
import argparse
import json
from pathlib import Path
from local_tools import ROOT, Tools, run, sha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    source, out = args.source.resolve(), args.output.resolve()
    assert not out.exists(), 'Use new output'
    parent = source.parent
    manifest = json.loads((parent / 'manifest.json').read_text())
    for path in source.iterdir():
        assert sha(path) == manifest[path.relative_to(parent).as_posix()], path
    out.mkdir(parents=True)
    tools = Tools()
    command = [tools.gcc(), '-march=rv32imac_zicsr', '-mabi=ilp32', '-mcmodel=medany',
               '-msmall-data-limit=0', '-O2', '-flto', '-g', '-ffreestanding',
               '-fno-builtin', '-fno-stack-protector', '-nostdlib', '-nostartfiles',
               '-Wall', '-Wextra', '-Werror', '-I'+str(source), '-T', source/'link_itcm.ld',
               '-Wl,--no-relax,-Map='+str(out/'firmware.map'), source/'start_itcm.S',
               source/'main.c', source/'driver.c', '-o', out/'firmware.elf']
    run(command, out, 'gcc')
    run([tools.binutil('objcopy'), '-O', 'binary', out/'firmware.elf', out/'firmware.bin'], out, 'objcopy')
    assert (out/'firmware.bin').read_bytes() == (source/'firmware.bin').read_bytes(), 'Rebuilt load image differs'
    report = dict(passed=True, binary_identical=True, firmware_sha256=sha(out/'firmware.bin'),
                  source_package_manifest_sha256=sha(parent/'manifest.json'),
                  source_script_sha256=sha(Path(__file__)),
                  debug_ELF_identity_required=False, scope='standalone exported-source compilation; real task regressions reference the identical load image')
    (out/'compiler_command.json').write_text(json.dumps([str(value) for value in command], indent=2))
    (out/'verification.json').write_text(json.dumps(report, indent=2))
    (out/'manifest.json').write_text(json.dumps({path.name:sha(path) for path in out.iterdir() if path.is_file()}, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
