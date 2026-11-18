"""Measured software-only experiments on the frozen ABC E203/DUT model."""
import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from local_tools import ROOT, Tools, run, sha

BASE = ROOT / 'testdata/e203_combined_20261104'
EX = ROOT / 'firmware/e203_experiments_20261104'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', choices=['lto', 'lto_csr'], required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--labels', default='0')
    ap.add_argument('--faults', action='store_true')
    args = ap.parse_args()
    out = args.output.resolve()
    assert not out.exists(), 'Use a new evidence directory'
    out.mkdir(parents=True)
    frozen = BASE / 'compare_abc'
    manifest = json.loads((frozen / 'manifest.json').read_text())
    sources = [Path(__file__), EX / 'start_itcm.S', EX / 'link_itcm.ld',
               ROOT / 'rtl/integration/driver/kwt1.h']
    for name in ['main.c', 'driver.c', 'word_access.h']:
        source = frozen / name
        assert sha(source) == manifest[name], source
        sources.append(source)
        shutil.copyfile(source, out / name)
    if args.config == 'lto_csr':
        main_source = (out / 'main.c').read_text()
        old = 'static void idle(void *ctx,uint32_t cycles){(void)ctx;uint32_t t=hread(36);while((uint32_t)(hread(36)-t)<cycles)__asm__ volatile("nop");}'
        new = 'static uint32_t lowcycle(void){uint32_t v;__asm__ volatile("csrr %0,0xb00":"=r"(v));return v;}\nstatic void idle(void *ctx,uint32_t cycles){(void)ctx;uint32_t t=lowcycle();while((uint32_t)(lowcycle()-t)<cycles)__asm__ volatile("nop");}'
        assert main_source.count(old) == 1
        (out / 'main.c').write_text(main_source.replace(old, new))
    tools = Tools()
    command = [tools.gcc(), '-march=rv32imac_zicsr', '-mabi=ilp32', '-mcmodel=medany',
               '-msmall-data-limit=0', '-O2', '-flto', '-g', '-ffreestanding',
               '-fno-builtin', '-fno-stack-protector', '-nostdlib', '-nostartfiles',
               '-Wall', '-Wextra', '-Werror', '-I' + str(ROOT / 'rtl/integration/driver'),
               '-I' + str(out), '-T', EX / 'link_itcm.ld',
               '-Wl,--no-relax,-Map=' + str(out / 'firmware.map'), EX / 'start_itcm.S',
               out / 'main.c', out / 'driver.c', '-o', out / 'firmware.elf']
    run(command, out, 'gcc')
    run([tools.binutil('objcopy'), '-O', 'binary', out / 'firmware.elf', out / 'firmware.bin'], out, 'objcopy')
    symbols = run([tools.binutil('nm'), '-n', out / 'firmware.elf'], out, 'nm')
    (out / 'firmware.nm').write_text(symbols)
    memory = {line.split()[2]: int(line.split()[0], 16) for line in symbols.splitlines() if len(line.split()) == 3}
    assert memory['__image_end'] == 0xa0002010
    assert 0 < memory['__itcm_end'] - memory['__itcm_start'] <= 65536
    (out / 'memory_map.json').write_text(json.dumps(memory, indent=2))
    (out / 'compiler_command.json').write_text(json.dumps([str(x) for x in command], indent=2))
    run([tools.binutil('objdump'), '-d', out / 'firmware.elf'], out, 'disassembly')
    for path, digest in json.loads((frozen / 'build_bindings.json').read_text()).items():
        assert sha(Path(path)) == digest, path
    model = frozen / 'combinations.exe'
    expected = json.loads((frozen / 'execution.json').read_text())['model_sha256']
    assert sha(model) == expected
    sources += [model, frozen / 'build_bindings.json', frozen / 'execution.json']
    bindings = {path.relative_to(ROOT).as_posix(): sha(path) for path in sources}
    (out / 'source_bindings.json').write_text(json.dumps(bindings, indent=2))
    for path in frozen.glob('*.hex'):
        if path.name.startswith(('input_', 'expected_', 'common.bin', 'layer_')):
            assert sha(path) == manifest[path.name], path
            shutil.copyfile(path, out / path.name)
    labels = list(map(int, args.labels.split(',')))
    assert labels and all(0 <= label < 12 for label in labels)
    (out / 'cases.txt').write_text(''.join(f'{label} 0\n' for label in labels))
    start = time.time()
    mode = 'faults' if args.faults else 'batch'
    with (out / 'execution.log').open('w') as log:
        process = subprocess.run([str(model), str(out), mode], stdout=log, stderr=subprocess.STDOUT)
    assert process.returncode == 0, (out / 'execution.log').read_text()[-2000:]
    (out / 'execution.json').write_text(json.dumps(dict(passed=True, kind='abc', experiment=args.config,
        labels=labels, mode=mode, elapsed_seconds=time.time()-start,
        model_sha256=sha(model), firmware_sha256=sha(out / 'firmware.bin')), indent=2))
    for name, digest in bindings.items():
        assert sha(ROOT / name) == digest, name
    from summarize_e203_combinations import summarize
    report = summarize(out)
    report['experiment'] = args.config
    report['production_driver_changed'] = False
    report['hardware_changed'] = False
    (out / 'summary.json').write_text(json.dumps(report, indent=2))
    (out / 'manifest.json').write_text(json.dumps({path.name: sha(path) for path in out.iterdir()
        if path.is_file() and path.name != 'manifest.json'}, indent=2))


if __name__ == '__main__':
    main()
