"""Bounded, synchronous software PIO variants for the no-cancel reference platform.

One aligned RAM load -> one accelerator store -> immediate error query per word.
No DMA, posted batch, deferred errors, or hardware change. Generic driver intact.
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
    ap.add_argument('--variant', choices=['nocancel', 'pointer_loop', 'unroll4', 'unroll4_csr'], required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--labels', default='0')
    ap.add_argument('--faults', action='store_true')
    args = ap.parse_args()
    out = args.output.resolve()
    own_hash = sha(Path(__file__))
    original_run = runner.run

    def compile_variant(command, folder, name):
        if name == 'gcc':
            source = (folder / 'main.c').read_text()
            for old, new in [('read32', 'kwt_platform_read32'), ('write32', 'kwt_platform_write32')]:
                source = re.sub(r'\b' + old + r'\b', new, source)
                source = source.replace('static int ' + new, 'int ' + new)
            # Exercise incompatible non-null callbacks and a cancellation source
            # before B0. Any accepted incompatible context causes HOST failure.
            source = source.replace('int main(void){', 'static int mismatch_read(void *p,uint32_t a,uint32_t *v){(void)p;(void)a;(void)v;return -1;}\nstatic int mismatch_cancel(void *p){(void)p;return 1;}\nint main(void){')
            probe = ''' kwt1_device rejected=d;
 rejected.read=mismatch_read;
 if(kwt1_run_provider(&rejected,&p,__input,__output)!=KWT1_ARGUMENT||kwt1_abort(&rejected)!=KWT1_ARGUMENT||kwt1_after_hard_reset(&rejected)!=KWT1_ARGUMENT){hwrite(68,0xe004);for(;;){}}
 rejected=d;rejected.cancelled=mismatch_cancel;
 if(kwt1_run_provider(&rejected,&p,__input,__output)!=KWT1_ARGUMENT||kwt1_abort(&rejected)!=KWT1_ARGUMENT||kwt1_after_hard_reset(&rejected)!=KWT1_ARGUMENT){hwrite(68,0xe005);for(;;){}}
'''
            assert source.count(' hwrite(76,sizeof(d));') == 1
            source = source.replace(' hwrite(76,sizeof(d));', probe + ' hwrite(76,sizeof(d));')
            (folder / 'main.c').write_text(source)
            driver = (folder / 'driver.c').read_text()
            guard = '!d->read||!d->write'
            assert driver.count(guard) == 3
            driver = driver.replace(guard, 'd->cancelled||d->read!=kwt_platform_read32||d->write!=kwt_platform_write32')
            driver = driver.replace('d->read(d->opaque,', 'kwt_platform_read32(d->opaque,')
            driver = driver.replace('d->write(d->opaque,', 'kwt_platform_write32(d->opaque,')
            driver = driver.replace('static int put(', 'static inline __attribute__((always_inline)) int put(')
            old_cancel = ' return d->cancelled&&d->cancelled(d->opaque);'
            assert driver.count(old_cancel) == 1
            driver = driver.replace(old_cancel, ' (void)d;return 0; /* entry guard requires no cancellation source */')
            if args.variant != 'nocancel':
                begin = driver.index(' for(k=0;k<p->size;k+=4) {')
                end = driver.index('\n return KWT1_OK;', begin)
                assert driver[begin:end].count('put(d,16,') == 1
                loop = ' const uint8_t *cur=p->data,*end=cur+p->size-4;\n'
                if args.variant.startswith('unroll4'):
                    loop += ' while((size_t)(end-cur)>=16u) {\n'
                    loop += '  if((rc=put(d,16,kwt_packet_word(cur))))return rc;cur+=4;\n' * 4
                    loop += ' }\n'
                loop += ' for(;cur<end;cur+=4) {if((rc=put(d,16,kwt_packet_word(cur))))return rc;}\n'
                loop += ' if((rc=put(d,12,1)))return rc;\n if((rc=put(d,16,kwt_packet_word(cur))))return rc;'
                driver = driver[:begin] + loop + driver[end:]
                # The original offset counter is no longer used by this packet.
                driver = driver.replace(' size_t k;int rc;\n if(!kwt_word_contract', ' int rc;\n if(!kwt_word_contract', 1)
            driver = '#include <stdint.h>\nint kwt_platform_read32(void *,uint32_t,uint32_t *);\nint kwt_platform_write32(void *,uint32_t,uint32_t);\n' + driver
            (folder / 'driver.c').write_text(driver)
        return original_run(command, folder, name)

    runner.run = compile_variant
    config = 'lto_csr' if args.variant.endswith('_csr') else 'lto'
    sys.argv = [str(ROOT / 'scripts/run_e203_software_experiments.py'), '--config', config,
                '--output', str(out), '--labels', args.labels]
    if args.faults:
        sys.argv += ['--faults']
    runner.main()
    assert sha(Path(__file__)) == own_hash
    bindings = json.loads((out / 'source_bindings.json').read_text())
    bindings[Path(__file__).relative_to(ROOT).as_posix()] = own_hash
    (out / 'source_bindings.json').write_text(json.dumps(bindings, indent=2))
    report = json.loads((out / 'summary.json').read_text())
    report.update(experiment=args.variant, per_transaction_error_query=True,
                  backend_callback_identity_guard=True, no_cancel_source_guard=True,
                  CPU_contract_rejections=6, hardware_changed=False, DMA=False,
                  time_source='mcycle CSR' if config == 'lto_csr' else 'HOST timer')
    (out / 'summary.json').write_text(json.dumps(report, indent=2))
    (out / 'manifest.json').write_text(json.dumps({path.name: sha(path) for path in out.iterdir()
        if path.is_file() and path.name != 'manifest.json'}, indent=2))


if __name__ == '__main__':
    main()
