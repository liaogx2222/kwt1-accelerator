"""Measure a bounded NICE block loader on the frozen trim2 reference system."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from local_tools import ROOT, Tools, sha


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Frozen input no longer matches: {old!r}')
    return source.replace(old, new)


def firmware_sources(out, frozen):
    driver = (frozen / 'driver.c').read_text()
    driver = replace_once(driver, 'static int packet(', '''static kwt1_packet retained_packet;
static int lease_retained;
void kwt_block_release_after_recovery(kwt1_provider *provider) {
 if(lease_retained) {
  provider->release(provider->opaque,&retained_packet);
  lease_retained=0;
 }
 provider->cancel(provider->opaque);
}
int kwt_block_copy(const uint8_t *source,uint32_t words) {
 int rc;
 __asm__ volatile (".insn r 0x7b, 7, 0x28, %0, %1, %2"
                   : "=r"(rc) : "r"(source),"r"(words) : "memory");
 return rc;
}
static int packet(''')
    start = driver.index(' while((size_t)(end-cur)>=32u)')
    end = driver.index(' return KWT1_OK;\n}', start)
    driver = driver[:start] + ''' while(cur<end) {
  uint32_t words=(uint32_t)(end-cur)/4;
  if(words>64)words=64;
  rc=kwt_block_copy(cur,words);
  if(rc)return bus_error(rc);
  cur+=4*words;
 }
 if((rc=put(d,12,1)))return rc;
 if((rc=kwt_block_copy(cur,1)))return bus_error(rc);
''' + driver[end:]
    driver = replace_once(driver, '  provider->release(provider->opaque,&p);return rc;',
                          '''  if(rc){retained_packet=p;lease_retained=1;return rc;}
  provider->release(provider->opaque,&p);return KWT1_OK;''')
    driver = replace_once(driver, ' cleanup=abort_confirm(d);provider->cancel(provider->opaque);d->abort_error=cleanup;',
                          ' cleanup=abort_confirm(d);d->abort_error=cleanup;')
    driver = replace_once(driver, ' if(cleanup){d->recovery_required=1;return KWT1_RESET_REQUIRED;}\n return rc;',
                          ''' if(cleanup){d->recovery_required=1;return KWT1_RESET_REQUIRED;}
 kwt_block_release_after_recovery(provider);
 return rc;''')
    (out / 'driver.c').write_text(driver)
    main = replace_once((frozen / 'main.c').read_text(), '#include "kwt1.h"',
                        '''#include "kwt1.h"
void kwt_block_release_after_recovery(kwt1_provider *);
int kwt_block_copy(const uint8_t *,uint32_t);''')
    main = replace_once(main, ' hwrite(76,sizeof(d));', ''' hwrite(76,sizeof(d));
 if(kwt_block_copy(__packet,0)!=-3 || kwt_block_copy(__packet+1,1)!=-3 ||
    kwt_block_copy(__packet,65)!=-3 || kwt_block_copy(__packet+65532,2)!=-3 ||
    kwt_block_copy(__packet-4,1)!=-3) {hwrite(68,0xe006);for(;;){}}
 hwrite(100,1);''')
    main = replace_once(main, 'hwrite(48,1);if(kwt1_after_hard_reset(&d)){hwrite(68,0xe002);for(;;){}}',
                        '''hwrite(48,1);if(kwt1_after_hard_reset(&d)){hwrite(68,0xe002);for(;;){}}
   kwt_block_release_after_recovery(&p);''')
    (out / 'main.c').write_text(main)


def simulation_sources(out, frozen, baseline):
    wrapper = replace_once((frozen / 'reference_top.sv').read_text(), ' e203_cpu_top cpu(',
                           ''' wire [31:0] ppi_response_data;
 kwt_block_write_response block_ack(clk,rst_n,pv&&pr,pread,pa,bus_rc,prd,ppi_response_data);
 e203_cpu_top cpu(''')
    wrapper = replace_once(wrapper, '.ppi_icb_rsp_rdata(prd)', '.ppi_icb_rsp_rdata(ppi_response_data)')
    (out / 'reference_top.sv').write_text(wrapper)
    host = replace_once((baseline / 'observer.cpp').read_text(), '  case 76:', '''  case 100:
   require(!active&&d.parameter_words==0&&value==1,"invalid-descriptor probe committed DATA");break;
  case 76:''')
    (out / 'observer.cpp').write_text(host)
    header = (baseline / 'window_observer.hpp').read_text()
    header = replace_once(header, 'static void observe_begin(){', '''static void observe_begin(){
 for(auto&v:phase_retired)v=0;
 data_ready_cycles=data_stall_cycles=0;''')
    header = replace_once(header, 'require(lease_bytes==packet.size()||(int32_t(d.bus_rc)!=0&&lease_bytes<packet.size()),"early release without error")',
                          '''require(lease_bytes==packet.size() ||
  (jobs[ji].fault==2 && lease_bytes<packet.size() && reset_requests==1 && last_error==-2 && abort_error==-2),
  "short lease released before confirmed reset")''')
    (out / 'window_observer.hpp').write_text(header)


def phase_report(folder):
    result = []
    for path in sorted(folder.glob('window_job_*.txt')):
        rows = [line.split() for line in path.read_text().splitlines()]
        phases = [int(row[2]) for row in rows if row[0] == 'phase']
        retired = [int(row[2]) for row in rows if row[0] == 'phase_retired']
        main = next(row for row in rows if row[:2] == ['window', '0'])
        tail = next(row for row in rows if row[:2] == ['window', '1'])
        ram = next(row for row in rows if row[:3] == ['ram', '0', '4'])
        ready, stalled = next((int(row[1]), int(row[2])) for row in rows if row[0] == 'data_request')
        assert sum(phases) == int(main[2]) and sum(retired) == int(main[3]), path
        result.append(dict(cycles=sum(phases), retired=sum(retired), phases=phases,
                           phase_retired=retired, staging_reads=int(ram[3]), tail_cycles=int(tail[2]),
                           words=int(next(row[1] for row in rows if row[0] == 'words')),
                           data_ready_cycles=ready, data_stall_cycles=stalled))
    return result


def verify(out, baseline):
    assert not (out/'verification.json').exists(), out
    results = {}
    for name in ('pio', 'block', 'faults'):
        folder = out/name
        log = (out/(name+'.log')).read_text()
        job_count = 4 if name == 'faults' else 1
        assert f'PASS E203 jobs={job_count} ' in log
        cases = phase_report(folder)
        assert len(cases) == job_count
        expected_jobs = [1, 3] if name == 'faults' else [0]
        for job in expected_jobs:
            assert (folder/f'cpu_observed_job_{job:02d}.hex').read_text().split() == (folder/'expected_000.hex').read_text().split()
            assert cases[job]['words'] == cases[job]['staging_reads'] == cases[job]['data_ready_cycles'] == 189328
        if name == 'faults':
            # The 64th write was accepted but its response was dropped. The
            # reader must not issue a 65th SRAM read or a 65th DATA write.
            assert cases[2]['staging_reads'] == cases[2]['words'] == 64
            assert cases[1] == cases[3] == results['block'][0]
            metrics = [list(map(int, row.split())) for row in (folder/'cpu_metrics.txt').read_text().splitlines()]
            assert [row[3] for row in metrics] == [-3, 0, -7, 0]
        results[name] = cases
    pio, block = results['pio'][0], results['block'][0]
    p0 = json.loads((baseline/'verification.json').read_text())
    assert pio['cycles'] == p0['cycles'] and pio['retired'] == p0['retired']
    assert pio['phase_retired'][2] == p0['phase_retired']['packet_lease']
    report = dict(passed=True, actual_E203=True, added_RAM_port=False, architecture='trim2 full-layer loader',
                  word_limit=64, phase_order=list(p0['phase_cycles']), cases=results,
                  output_codes=4*6336, mismatches=0, rejected_descriptors=5,
                  lease_retired_reduction=1-block['phase_retired'][2]/pio['phase_retired'][2],
                  tasks_per_second_at_assumed_150MHz=150000000/block['cycles'],
                  mean_SoC_power_mW=None, complete_counted_area_mm2=None, verifier_sha256=sha(__file__))
    (out/'verification.json').write_text(json.dumps(report, indent=2))
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*')
                                                if p.is_file() and 'model' not in p.relative_to(out).parts}, indent=2))
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify-existing', action='store_true', help='validate saved simulator output without rebuilding')
    args = parser.parse_args()
    out = args.output.resolve()
    base = ROOT / 'testdata/input16_rtl_20261105'
    frozen, baseline = base / 'trim2_e203', base / 'p0_baseline'
    if args.verify_existing:
        bindings = json.loads((out/'source_bindings.json').read_text())
        for path, digest in bindings.items():
            source = ROOT/path
            if source == Path(__file__).resolve() and sha(source) != digest:
                source = out/'runner_before_counter_assert_fix.py'
            assert sha(source) == digest, source
        verify(out, baseline)
        return
    out.mkdir(parents=True)
    cpu = ROOT.parent / 'e203_hbirdv2'
    rtl = ROOT / 'rtl/input16_trim2'
    cwd = '/mnt/e/project/ChipCompetition/keyword-transformer'
    tools = Tools()

    def run(command, log):
        with (out / log).open('w') as handle:
            result = subprocess.run([str(v) for v in command], stdout=handle, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'{log}\n{(out / log).read_text(errors="replace")[-4500:]}')

    def linux(command, log):
        run(['wsl.exe', '-d', 'Ubuntu-24.04', '--', 'bash', '-lc', f'cd {cwd} && {command}'], log)

    fixtures = sorted(frozen.glob('*.bin.hex')) + [frozen / f'{n}_000.hex' for n in ('input', 'expected')]
    common = [frozen / n for n in ('kwt1.h', 'word_access.h', 'link.ld', 'main.c', 'driver.c', 'reference_top.sv', 'firmware.bin')]
    observed = [baseline / n for n in ('observer.cpp', 'window_observer.hpp', 'verification.json')]
    for folder, paths in ((frozen, fixtures + common), (baseline, observed)):
        manifest = json.loads((folder / 'manifest.json').read_text())
        for path in paths:
            assert sha(path) == manifest[path.name], path
    for path in common[:3]:
        shutil.copyfile(path, out / path.name)
    firmware_sources(out, frozen)
    simulation_sources(out, frozen, baseline)
    start = ROOT / 'firmware/e203_experiments_20261104/start_itcm.S'
    flags = ['-march=rv32imac_zicsr', '-mabi=ilp32', '-mcmodel=medany', '-msmall-data-limit=0',
             '-O2', '-flto', '-g', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
             '-nostdlib', '-nostartfiles', '-Wall', '-Wextra', '-Werror']
    compiler = [tools.gcc(), *flags, '-I'+str(out), '-T', out/'link.ld', '-Wl,--no-relax,-Map='+str(out/'firmware.map'),
                start, out/'main.c', out/'driver.c', '-o', out/'firmware.elf']
    (out / 'compiler_command.json').write_text(json.dumps(list(map(str, compiler)), indent=2))
    run(compiler, 'firmware.log')
    run([tools.binutil('objcopy'), '-O', 'binary', out/'firmware.elf', out/'firmware.bin'], 'objcopy.log')
    run(['git', '-C', cpu, 'rev-parse', 'HEAD'], 'cpu_revision.txt')
    cpu_files = sorted((cpu/'rtl/e203/core').glob('*.v')) + sorted((cpu/'rtl/e203/general').glob('*.v'))
    inputs = [ROOT/'rtl/block_transfer/kwt_e203_block_write.sv',
              ROOT/'rtl/micro/mul_pipe.sv', ROOT/'rtl/micro/rne_pipe.sv',
              *sorted(p for p in rtl.glob('*.sv') if p.name != 'kwt_tech_sram_blackbox.sv'),
              ROOT/'rtl/reference/icb_kwt_bridge.sv', ROOT/'rtl/input16_icb_top.sv', out/'reference_top.sv']
    bound = [Path(__file__), start, *fixtures, *common, *observed, *cpu_files, *inputs, rtl/'generated/kwt_profile.svh']
    (out/'source_bindings.json').write_text(json.dumps({os.path.relpath(p, ROOT).replace('\\','/'):sha(p) for p in bound}, indent=2))
    rel = out.relative_to(ROOT).as_posix()
    sources = ' '.join(os.path.relpath(p, ROOT).replace('\\','/') for p in [*cpu_files, *inputs]
                       if p.name not in ('config.v', 'e203_defines.v'))
    linux(f'verilator --cc --exe --no-timing -Wno-fatal --output-split 16000 --output-split-cfuncs 500 '
          f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
          f'--top-module reference_top --Mdir {rel}/model {sources} {cwd}/{rel}/observer.cpp', 'generate.log')
    linux(f'make -C {rel}/model -f Vreference_top.mk -j 3 OPT_FAST=-O2 OPT_SLOW=-O0', 'build.log')
    for name, firmware, mode in [('pio', frozen/'firmware.bin', 'batch'), ('block', out/'firmware.bin', 'batch'),
                                 ('faults', out/'firmware.bin', 'faults')]:
        folder = out/name
        folder.mkdir()
        for path in fixtures:
            shutil.copyfile(path, folder/path.name)
        shutil.copyfile(firmware, folder/'firmware.bin')
        (folder/'cases.txt').write_text('0 0\n')
        linux(f'{rel}/model/Vreference_top {rel}/{name} {mode}', name+'.log')
    verify(out, baseline)


if __name__ == '__main__':
    main()
