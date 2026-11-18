"""Unified Windows reference PIO campaign entry: fresh runs or read-only check."""
import argparse
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path
from local_tools import ROOT, sha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', choices=['all', 'check'], default='check')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    commands = []

    def execute(script, *arguments):
        command = [sys.executable, str(ROOT/'scripts'/script), *map(str, arguments)]
        commands.append(command)
        subprocess.run(command, cwd=ROOT, check=True)

    if args.stage == 'all':
        assert not out.exists(), 'Fresh campaign output required'
        out.mkdir(parents=True)
        experiments = [
            ('compare_lto', 'run_e203_software_experiments.py', ['--config','lto']),
            ('compare_lto_csr', 'run_e203_software_experiments.py', ['--config','lto_csr']),
            ('compare_lto_direct', 'run_e203_direct_backend.py', []),
            ('compare_inline_put', 'run_e203_inline_backend.py', ['--variant','inline_put']),
            ('compare_direct_inline', 'run_e203_inline_backend.py', ['--variant','direct_inline']),
            ('compare_nocancel', 'run_e203_platform_pio.py', ['--variant','nocancel']),
            ('compare_pointer_loop', 'run_e203_platform_pio.py', ['--variant','pointer_loop']),
            *[(name,'run_e203_pio_loop.py',['--variant',variant]) for name,variant in [
                ('compare_unroll4_v2','unroll4'),('compare_unroll4_likely','unroll4_likely'),
                ('compare_unroll8','unroll8'),('compare_unroll8_likely','unroll8_likely'),
                ('compare_unroll8_likely_csr','unroll8_likely_csr')]]]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(execute,script,*options,'--output',out/name) for name,script,options in experiments]
            for future in futures:
                future.result()
        selection = dict(selected_variant='unroll8_likely',selected_group='compare_unroll8_likely',
            comparison_groups=[name for name,_,_ in experiments],
            selection_reason='Retain original HOST timer; CSR has negligible cycle benefit and substantially higher retired polling instructions in the measured reference.',
            production_driver_changed=False,hardware_changed=False,official_metrics_complete=False)
        (out/'selection.json').write_text(json.dumps(selection,indent=2))
        execute('build_e203_transaction_observer.py','--output',out/'transaction_model')
        model=out/'transaction_model/combinations.exe'
        groups=[('observer_control_v2',[]),('full_classes',['--labels',','.join(map(str,range(12)))]),
                ('faults',['--faults']),('opaque_contract',['--contract-probe'])]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(execute,'run_e203_pio_metrics.py','--variant','unroll8_likely',
                '--model',model,'--output',out/name,*options) for name,options in groups]
            for future in futures:
                future.result()
        # An unbound technology is an expected diagnostic, never a passed PPA.
        subprocess.run([sys.executable,str(ROOT/'scripts/check_technology.py'),'--config',
                        str(ROOT/'flow/targets/smic40.binding.pending.json'),'--output',str(out/'smic40_preflight.json')],cwd=ROOT)
        execute('check_e203_software_campaign.py','--input',out,'--output',out/'review')
        (out/'reproducer.json').write_text(json.dumps(dict(script_sha256=sha(Path(__file__)),commands=commands),indent=2))
    review=out/'review'
    for name,digest in json.loads((review/'manifest.json').read_text()).items():
        assert sha(review/name)==digest,name
    for name,digest in json.loads((review/'source_bindings.json').read_text()).items():
        assert sha(ROOT/name)==digest,name
    selection=json.loads((out/'selection.json').read_text())
    for group in selection['comparison_groups']+['observer_control_v2','full_classes','faults','opaque_contract']:
        for name,digest in json.loads((out/group/'manifest.json').read_text()).items():
            assert sha(out/group/name)==digest,(group,name)
    print(json.dumps(json.loads((review/'verification.json').read_text()),indent=2))


if __name__=='__main__':
    main()
