"""Direct reference-platform callbacks, preserving every MMIO error query.

This experiment changes callback dispatch only relative to measured LTO.
The unchanged generic driver stays available. All public entry points reject
devices whose read/write callbacks do not match this platform backend.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from local_tools import ROOT, sha
import run_e203_software_experiments as runner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--labels', default='0')
    ap.add_argument('--faults', action='store_true')
    args = ap.parse_args()
    out = args.output.resolve()
    own_hash = sha(Path(__file__))
    original_run = runner.run

    def compile_platform(command, folder, name):
        if name == 'gcc':
            source = (folder / 'main.c').read_text()
            for old, new in [('read32', 'kwt_platform_read32'), ('write32', 'kwt_platform_write32')]:
                source = re.sub(r'\b' + old + r'\b', new, source)
                source = source.replace('static int ' + new, 'int ' + new)
            (folder / 'main.c').write_text(source)
            driver = (folder / 'driver.c').read_text()
            guard = '!d->read||!d->write'
            assert driver.count(guard) == 3
            assert driver.count('d->read(d->opaque,') == 5
            assert driver.count('d->write(d->opaque,') == 2
            driver = driver.replace(guard, 'd->read!=kwt_platform_read32||d->write!=kwt_platform_write32')
            driver = driver.replace('d->read(d->opaque,', 'kwt_platform_read32(d->opaque,')
            driver = driver.replace('d->write(d->opaque,', 'kwt_platform_write32(d->opaque,')
            declarations = '#include <stdint.h>\nint kwt_platform_read32(void *,uint32_t,uint32_t *);\nint kwt_platform_write32(void *,uint32_t,uint32_t);\n'
            (folder / 'driver.c').write_text(declarations + driver)
        return original_run(command, folder, name)

    runner.run = compile_platform
    sys.argv = [str(ROOT / 'scripts/run_e203_software_experiments.py'), '--config', 'lto',
                '--output', str(out), '--labels', args.labels]
    if args.faults:
        sys.argv += ['--faults']
    runner.main()
    assert sha(Path(__file__)) == own_hash
    bindings = json.loads((out / 'source_bindings.json').read_text())
    bindings[Path(__file__).relative_to(ROOT).as_posix()] = own_hash
    (out / 'source_bindings.json').write_text(json.dumps(bindings, indent=2))
    report = json.loads((out / 'summary.json').read_text())
    report.update(experiment='lto_direct', backend_callback_identity_guard=True,
                  per_transaction_error_query=True, time_source='unchanged HOST timer')
    (out / 'summary.json').write_text(json.dumps(report, indent=2))
    (out / 'manifest.json').write_text(json.dumps({path.name: sha(path) for path in out.iterdir()
        if path.is_file() and path.name != 'manifest.json'}, indent=2))


if __name__ == '__main__':
    main()
