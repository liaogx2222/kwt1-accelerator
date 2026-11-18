"""Independent integer, transaction, cold-task and recovery gate for PIO software."""
import argparse
import json
import re
import struct
import sys
from pathlib import Path
from local_tools import ROOT, sha
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]


def read(path):
    return json.loads(path.read_text())


def stored(path):
    return b''.join(int(word, 16).to_bytes(4, 'little') for word in path.read_text().split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    base, out = args.input.resolve(), args.output.resolve()
    assert not out.exists(), 'New review output required'
    campaign = read(base / 'selection.json')
    import numpy as np
    from integer_model.runtime import Encoder
    from validate_kwt1_r2 import artifacts
    packets, parameters = artifacts()
    features = np.load(ROOT / 'testdata/integer_v1/fixture/encoder_input.npy', mmap_mode='r')
    labels = np.load(ROOT / 'testdata/integer_v1/fixture/labels.npy')
    saved = np.load(ROOT / 'testdata/integer_v1/validation/encoder_output_int8.npy', mmap_mode='r')
    meta = read(ROOT / 'testdata/integer_v1/params/manifest.json')
    cache, source_hashes, results = {}, {}, {}
    codes = hashes = paired_transactions = 0
    for group in campaign['comparison_groups'] + ['observer_control_v2', 'full_classes', 'faults', 'opaque_contract']:
        folder = base / group
        for name, digest in read(folder / 'manifest.json').items():
            assert sha(folder / name) == digest, (group, name)
            hashes += 1
        for name, digest in read(folder / 'source_bindings.json').items():
            assert sha(ROOT / name) == digest, name
            source_hashes[name] = digest
        summary = read(folder / 'summary.json')
        assert summary['passed'] and not summary['hardware_changed']
        metrics = [list(map(int, line.split())) for line in (folder / 'cpu_metrics.txt').read_text().splitlines()]
        assert len(metrics) == len(summary['jobs'])
        for name, data in packets.items():
            assert stored(folder / (name + '.hex')) == data
        for raw, job in zip(metrics, summary['jobs']):
            assert raw == job['legacy_18_fields']
            assert job['main']['cycles'] == raw[4] == sum(job['phase_cycles'].values())
            assert job['main']['retired'] == raw[5]
            for window, name in [(0, 'main'), (1, 'report_tail')]:
                clock, retired = 0, 0
                for line in (folder / f'window_job_{raw[0]:02d}.txt').read_text().splitlines():
                    fields = line.split()
                    if fields[:2] == ['pc', str(window)]:
                        clock += int(fields[3]); retired += int(fields[4])
                assert clock == job[name]['cycles'] and retired == job[name]['retired']
            assert raw[16] == sum(value['reads'] for key in ['ram_main', 'ram_tail'] for value in job[key].values())
            assert raw[17] == sum(value['writes'] for key in ['ram_main', 'ram_tail'] for value in job[key].values())
            if raw[3] == 0:
                label = raw[1]
                if label not in cache:
                    sample = int(np.flatnonzero(labels == label)[0])
                    x = np.clip(np.rint(features[sample].astype(np.float64) / meta['decode_scales']['encoder_input']), -127, 127).astype(np.int8)
                    sentinel = [0]
                    def softmax_observer(name, value, clipped):
                        if name.endswith('/attention_softmax/index_q8'):
                            sentinel[0] += int(np.count_nonzero(value == 4096))
                    y = Encoder(parameters, observer=softmax_observer)(x[None])[0]
                    assert np.array_equal(y, saved[sample])
                    cache[label] = (x.tobytes(), y.tobytes(), sentinel[0])
                x, y, sentinel_count = cache[label]
                assert stored(folder / f'input_{label:03d}.hex') == x
                assert stored(folder / f'cpu_observed_job_{raw[0]:02d}.hex') == y
                assert raw[8:13] == [189328, 13, 13, 0, 61728]
                assert raw[15] == 5058532 and job['errors'] == [0, 0, 0]
                assert job['ram_main']['packet_staging']['reads'] == 189328
                assert job['ram_main']['code_address_range']['reads'] == 0
                codes += 6336
            elif raw[3] == -3:
                assert raw[2] == 1 and job['errors'] == [-3, 0, 0]
            else:
                assert raw[3] == -7 and raw[2] == 2 and raw[8] == 64 and job['errors'] == [-2, -2, 1]
            transaction_file = folder / f'transactions_job_{raw[0]:02d}.txt'
            if transaction_file.exists():
                tx = {line.split()[0]: int(line.split()[1]) for line in transaction_file.read_text().splitlines()}
                assert tx['pending'] == 0
                assert tx['error_queries'] == tx['acc_reads'] + tx['acc_writes'] + tx['unaccepted_error_queries']
                assert tx['parameter_writes'] == raw[8]
                if raw[3] == 0:
                    assert tx['unaccepted_error_queries'] == 0 and tx['input_writes'] == 1584
                    # SM_RQ skips exp LUT banks 18/19 for index 4096. Explain
                    # input-dependent read variation against the observed
                    # silence baseline; never copy one sample's count to all.
                    expected_reads = 10862768 + 2*(cache[0][2]-sentinel_count)
                    assert tx['SRAM_reads'] == expected_reads and tx['SRAM_writes'] == 1312536, (group, raw[1], tx, expected_reads)
                paired_transactions += tx['acc_reads'] + tx['acc_writes']
        elf = (folder / 'firmware.elf').read_bytes()
        image = (folder / 'firmware.bin').read_bytes()
        assert elf[:6] == b'\x7fELF\x01\x01' and struct.unpack_from('<H', elf, 18)[0] == 243
        assert struct.unpack_from('<I', elf, 24)[0] == 0xa0000000
        offset = struct.unpack_from('<I', elf, 28)[0]
        size, count = struct.unpack_from('<HH', elf, 42)
        for i in range(count):
            kind, pos, virtual, physical, filesz, memsz, flags, align = struct.unpack_from('<8I', elf, offset+i*size)
            if kind == 1:
                assert 0xa0000000 <= physical <= physical+filesz <= 0xa0020000
                assert elf[pos:pos+filesz] == image[physical-0xa0000000:physical-0xa0000000+filesz]
                if virtual != physical:
                    assert virtual == 0x80000000 and physical == 0xa0001000
        memory = read(folder / 'memory_map.json')
        assert memory['__image_end'] == 0xa0002010 and memory['__stack_top'] - memory['__stack_bottom'] == 16384
        assert 'FAIL' not in (folder / 'execution.log').read_text()
        source_hashes[(folder / 'manifest.json').relative_to(ROOT).as_posix()] = sha(folder / 'manifest.json')
        results[group] = summary
    full = results['full_classes']
    assert len(full['jobs']) == 12 and [job['label'] for job in full['jobs']] == list(range(12))
    assert len(results['faults']['jobs']) == 4 and [job['rc'] for job in results['faults']['jobs']] == [-3, 0, -7, 0]
    selected = results[campaign['selected_group']]
    assert sha(base / campaign['selected_group'] / 'firmware.bin') == sha(base / 'full_classes/firmware.bin') == sha(base / 'faults/firmware.bin')
    assert selected['jobs'][0]['main'] == full['jobs'][0]['main']
    assert results['observer_control_v2']['jobs'][0]['main'] == results['compare_unroll8_likely']['jobs'][0]['main']
    assert sha(base / 'observer_control_v2/firmware.bin') == sha(base / 'compare_unroll8_likely/firmware.bin')
    assert results['opaque_contract']['opaque_noipa_contract_probes'] == 6
    opaque_nm = (base / 'opaque_contract/firmware.nm').read_text()
    assert re.search(r'\bt opaque_contract_probe$', opaque_nm, re.M)
    for api in ['kwt1_run_provider', 'kwt1_abort', 'kwt1_after_hard_reset']:
        assert api in (base / 'opaque_contract/disassembly.log').read_text()
    clocks = [job['main']['cycles'] for job in full['jobs']]
    totals = sum(clocks)
    report = dict(passed=True, selected=campaign['selected_variant'], full_class_codes=76032,
        recovery_codes=12672, all_independent_codes=codes, mismatches=0,
        comparisons={name: results[name]['jobs'][0]['main'] for name in campaign['comparison_groups']},
        twelve_task_cycles=totals, normal_cycle_range=[min(clocks), max(clocks)],
        assumed_150MHz_twelve_task_seconds=totals/150000000,
        assumed_150MHz_throughput_tasks_per_second=12*150000000/totals,
        measured_on_silicon=False, official_performance_tasks=False,
        internal_9M_target_met=max(clocks)<=9000000,
        source_and_evidence_hashes_checked=hashes,
        immediate_error_checked_ACC_transactions=paired_transactions,
        CPU_contract_probe_noipa_checks=6, observer_control_zero_cycle_difference=True,
        stack_highwater_bytes=max(job['stack_highwater'] for job in full['jobs']),
        ITCM_bytes=full['ITCM_bytes'], shared_image_bytes=8208,
        shared_occupied_including_16KiB_reserved_stack_bytes=98992,
        SRAM_read_range=[min(10862768+2*(cache[0][2]-cache[i][2]) for i in range(12)),
                         max(10862768+2*(cache[0][2]-cache[i][2]) for i in range(12))],
        SRAM_read_variation='2 skipped bank reads per Softmax exp index 4096; absolute baseline observed, all class deltas independently explained',
        Softmax_exp_zero_sentinel_counts={str(i): cache[i][2] for i in range(12)},
        SRAM_writes_per_task=1312536,
        production_driver_changed=False, DMA=False, CPU_RTL_changed=False,
        accelerator_RTL_changed=False, physical_signoff=False)
    out.mkdir(parents=True)
    source_hashes[Path(__file__).relative_to(ROOT).as_posix()] = sha(Path(__file__))
    (out / 'verification.json').write_text(json.dumps(report, indent=2))
    (out / 'source_bindings.json').write_text(json.dumps(source_hashes, indent=2))
    (out / 'manifest.json').write_text(json.dumps({path.name: sha(path) for path in out.iterdir() if path.is_file()}, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
