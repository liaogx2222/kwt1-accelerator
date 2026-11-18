"""Execute PIO firmware with source-bound host-only transaction instrumentation."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from local_tools import ROOT, sha
import run_e203_software_experiments as recorder
import run_e203_pio_loop as variant


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--variant', required=True)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--labels', default='0')
    ap.add_argument('--faults', action='store_true')
    ap.add_argument('--contract-probe', action='store_true')
    args = ap.parse_args()
    out, model = args.output.resolve(), args.model.resolve()
    own_hash = sha(Path(__file__))
    model_hash = sha(model)
    for name, digest in json.loads((model.parent / 'build_bindings.json').read_text()).items():
        assert sha(Path(name)) == digest, name
    assert json.loads((model.parent / 'summary.json').read_text())['model_sha256'] == model_hash
    old_model = ROOT / 'testdata/e203_combined_20261104/compare_abc/combinations.exe'

    def execute(command, **kwargs):
        assert Path(command[0]) == old_model and len(command) == 3, command
        actual = [str(model), *command[1:]]
        (out / 'actual_model_command.json').write_text(json.dumps(actual, indent=2))
        return subprocess.run(actual, **kwargs)

    # Replace only this recorder's subprocess binding, not local_tools or Python's
    # shared subprocess module. Compilation uses the original tools unchanged.
    recorder.subprocess = SimpleNamespace(run=execute, STDOUT=subprocess.STDOUT)
    sys.argv = [str(ROOT / 'scripts/run_e203_pio_loop.py'), '--variant', args.variant,
                '--output', str(out), '--labels', args.labels]
    if args.faults:
        sys.argv += ['--faults']
    if args.contract_probe:
        sys.argv += ['--contract-probe']
    variant.main()
    assert sha(Path(__file__)) == own_hash and sha(model) == model_hash
    execution = json.loads((out / 'execution.json').read_text())
    execution['model_sha256'] = model_hash
    execution['host_transaction_instrumentation'] = True
    (out / 'execution.json').write_text(json.dumps(execution, indent=2))
    bindings = json.loads((out / 'source_bindings.json').read_text())
    for path in [Path(__file__), model, model.parent / 'build_bindings.json', model.parent / 'summary.json']:
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    (out / 'source_bindings.json').write_text(json.dumps(bindings, indent=2))
    (out / 'manifest.json').write_text(json.dumps({path.name: sha(path) for path in out.iterdir()
        if path.is_file() and path.name != 'manifest.json'}, indent=2))


if __name__ == '__main__':
    main()
