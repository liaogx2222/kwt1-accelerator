"""PIO loop scheduling experiments; immediate per-word error handling retained."""
import argparse
import json
import sys
from pathlib import Path
from local_tools import ROOT, sha
import run_e203_software_experiments as recorder
import run_e203_platform_pio as platform


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--variant', choices=['unroll4', 'unroll4_likely', 'unroll8', 'unroll8_likely', 'unroll8_likely_csr'], required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--labels', default='0')
    ap.add_argument('--faults', action='store_true')
    ap.add_argument('--contract-probe', action='store_true')
    args = ap.parse_args()
    out = args.output.resolve()
    own_hash = sha(Path(__file__))
    original_run = recorder.run

    def compile_loop(command, folder, name):
        if name == 'gcc':
            driver = (folder / 'driver.c').read_text()
            old = '  if((rc=put(d,16,kwt_packet_word(cur))))return rc;cur+=4;\n'
            step = '  if((rc=put(d,16,kwt_packet_word(cur)))){return rc;}cur+=4;\n'
            assert driver.count(old) == 4
            driver = driver.replace(old, step)
            if args.variant.startswith('unroll8'):
                before = ' while((size_t)(end-cur)>=16u) {\n' + step * 4 + ' }\n'
                after = ' while((size_t)(end-cur)>=32u) {\n' + step * 8 + ' }\n'
                assert driver.count(before) == 1
                driver = driver.replace(before, after)
            if 'likely' in args.variant:
                before = 'rc=kwt_platform_write32(d->opaque,reg,value);return rc?bus_error(rc):KWT1_OK;'
                after = 'rc=kwt_platform_write32(d->opaque,reg,value);if(__builtin_expect(rc!=0,0))return bus_error(rc);return KWT1_OK;'
                assert driver.count(before) == 1
                driver = driver.replace(before, after)
            (folder / 'driver.c').write_text(driver)
            if args.contract_probe:
                source = (folder / 'main.c').read_text()
                helper = '''static __attribute__((noipa)) int opaque_contract_probe(kwt1_device *dev,kwt1_provider *provider){
 return kwt1_run_provider(dev,provider,__input,__output)==KWT1_ARGUMENT&&kwt1_abort(dev)==KWT1_ARGUMENT&&kwt1_after_hard_reset(dev)==KWT1_ARGUMENT;
}
'''
                assert source.count('int main(void){') == 1
                source = source.replace('int main(void){', helper + 'int main(void){')
                marker = ' hwrite(76,sizeof(d));'
                probe = ''' rejected=d;rejected.read=mismatch_read;
 if(!opaque_contract_probe(&rejected,&p)){hwrite(68,0xe006);for(;;){}}
 rejected=d;rejected.cancelled=mismatch_cancel;
 if(!opaque_contract_probe(&rejected,&p)){hwrite(68,0xe007);for(;;){}}
'''
                assert source.count(marker) == 1
                (folder / 'main.c').write_text(source.replace(marker, probe + marker))
        return original_run(command, folder, name)

    recorder.run = compile_loop
    source_hash = sha(ROOT / 'scripts/run_e203_platform_pio.py')
    base_variant = 'unroll4_csr' if args.variant.endswith('_csr') else 'unroll4'
    sys.argv = [str(ROOT / 'scripts/run_e203_platform_pio.py'), '--variant', base_variant,
                '--output', str(out), '--labels', args.labels]
    if args.faults:
        sys.argv += ['--faults']
    platform.main()
    assert sha(Path(__file__)) == own_hash
    assert sha(ROOT / 'scripts/run_e203_platform_pio.py') == source_hash
    bindings = json.loads((out / 'source_bindings.json').read_text())
    bindings[Path(__file__).relative_to(ROOT).as_posix()] = own_hash
    (out / 'source_bindings.json').write_text(json.dumps(bindings, indent=2))
    report = json.loads((out / 'summary.json').read_text())
    report.update(experiment=args.variant, loop_unroll=8 if args.variant.startswith('unroll8') else 4,
                  per_word_immediate_error_check=True, deferred_error_query=False,
                  opaque_noipa_contract_probes=6 if args.contract_probe else 0)
    (out / 'summary.json').write_text(json.dumps(report, indent=2))
    (out / 'manifest.json').write_text(json.dumps({path.name: sha(path) for path in out.iterdir()
        if path.is_file() and path.name != 'manifest.json'}, indent=2))


if __name__ == '__main__':
    main()
