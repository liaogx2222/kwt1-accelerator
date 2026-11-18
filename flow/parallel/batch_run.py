"""Python 3.6 isolated accelerator DC/PT batch. Never stops unrelated tasks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
DC = '/eda/synopsys/dc/dc_2022.03-SP5-5/bin/dc_shell'
PT = '/eda/synopsys/prime/prime_2022.03-SP5-1/bin/pt_shell'


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify():
    origin = json.loads((ROOT/'INSTALL_RECEIPT.json').read_text())
    if sha(ROOT/'batch_manifest.json') != origin['batch_manifest_sha256']:
        raise SystemExit('BATCH_MANIFEST_CHANGED')
    spec = json.loads((ROOT/'batch_manifest.json').read_text())
    for name, value in spec['batch_tools'].items():
        if sha(ROOT/name) != value:
            raise SystemExit('BATCH_TOOL_MISMATCH '+name)
    for name, row in spec['projects'].items():
        project = ROOT/name
        if sha(project/'manifest.json') != row['manifest_sha256']:
            raise SystemExit('BATCH_PROJECT_MANIFEST_MISMATCH '+name)
        manifest = json.loads((project/'manifest.json').read_text())
        for file, value in manifest['files'].items():
            if sha(project/file) != value['sha256']:
                raise SystemExit('BATCH_SOURCE_MISMATCH '+name+'/'+file)
    return spec


def save(state):
    temp = ROOT/'states.tmp.json'
    temp.write_text(json.dumps(state, indent=2)+'\n')
    os.replace(str(temp), str(ROOT/'states.json'))


def resources():
    cores = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1
    info = Path('/proc/meminfo')
    available = None
    if info.exists():
        m = re.search(r'^MemAvailable:\s+(\d+) kB', info.read_text(), re.M)
        if m:
            available = int(m.group(1))*1024
    return cores, available


def stage_check(project, command, log):
    with log.open('x') as stream:
        p = subprocess.run(command, cwd=str(project), stdout=stream, stderr=subprocess.STDOUT)
    if p.returncode:
        raise RuntimeError('precheck failed; preserve '+str(log))


def accept_dc(project, row):
    log = project/'build/dc.console.log'
    text = log.read_text(errors='replace')
    if 'KWT_CLEAN_SYNTH_DONE' not in text or re.search(r'^(?:Error:|KWT_FATAL)', text, re.M):
        raise RuntimeError('DC completion/error gate rejected')
    stage_check(project, [sys.executable, 'flow/project.py', 'check-dc'], project/'build/check_dc.log')
    area = (project/'build/dc/reports/area.rpt').read_text()
    total = re.search(r'Total cell area:\s+([0-9.]+)', area)
    macro = re.search(r'Macro/Black Box area:\s+([0-9.]+)', area)
    row['netlist_sha256'] = sha(project/'build/dc/mapped.v')
    row['DC_source_netlist_verified'] = True
    row['cell_area_library_units'] = float(total.group(1)) if total else None
    row['macro_area_library_units'] = float(macro.group(1)) if macro else None
    row['whole_SoC_area_mm2'] = None
    row['power_mW'] = None
    row['energy_uJ'] = None


def accept_pt(project, row):
    text = (project/'build/pt.console.log').read_text(errors='replace')
    if not (project/'build/pt_batch/complete').exists() or re.search(r'^(?:Error:|KWT_FATAL)', text, re.M):
        raise RuntimeError('PT report generation/error gate rejected')
    values = {}
    for corner in ['ss', 'ff', 'tt']:
        groups = []
        active = None
        for line in (project/('build/pt_batch/area_'+corner+'.rpt')).read_text().splitlines():
            if 'Timing Path Group' in line:
                active = dict(group=line.strip())
                groups.append(active)
            elif active is not None:
                for label, key in [('Critical Path Slack:', 'slack_ns'), ('Total Negative Slack:', 'TNS_ns'), ('No. of Violating Paths:', 'violations')]:
                    if label in line:
                        active[key] = float(line.split(label, 1)[1].strip())
        if len(groups) < 2 or any(not all(key in item for key in ['slack_ns','TNS_ns','violations']) for item in groups):
            raise RuntimeError('incomplete PT QoR '+corner)
        for report in ['coverage_', 'coverage_untested_', 'check_timing_', 'constraints_']:
            if not (project/('build/pt_batch/'+report+corner+'.rpt')).is_file():
                raise RuntimeError('missing PT report '+report+corner)
        values[corner] = groups
    row['PT_QoR'] = values
    row['PT_reports_complete'] = True
    row['hold_remediation'] = 'deferred by user; reports retained'
    row['timing_signoff'] = False


def monitor():
    if not (ROOT/'states.json').exists():
        print('BATCH_NOT_STARTED')
        return
    state = json.loads((ROOT/'states.json').read_text())
    print('jobs=%s cores/job=%s hold_fix=OFF scope=accelerator_partition' % (state['jobs'], state['cores_per_job']))
    for name, row in state['projects'].items():
        print('%-14s %-18s pid=%s %s' % (name, row['stage'], row.get('pid', '-'), row.get('error', '')))
        # DC's executable can be common_shell_exec, not dc_shell. Match owned
        # processes by project cwd rather than filtering the display name.
        proc = Path('/proc')
        if proc.is_dir() and hasattr(os, 'getuid'):
            for p in proc.iterdir():
                try:
                    if not p.name.isdigit() or p.stat().st_uid != os.getuid():
                        continue
                    cwd = (p/'cwd').resolve()
                    project = ROOT/name
                    if cwd != project and project not in cwd.parents:
                        continue
                    text = (p/'status').read_text()
                    comm = (p/'comm').read_text().strip()
                    rss = re.search(r'^VmRSS:\s+(.*)$', text, re.M)
                    stat = (p/'stat').read_text(); words = stat[stat.rfind(')')+2:].split()
                    cpu_seconds = (int(words[11])+int(words[12]))/os.sysconf('SC_CLK_TCK')
                    print('  live pid=%s comm=%s state=%s CPU_s=%.1f RSS=%s' %
                          (p.name, comm, words[0], cpu_seconds, rss.group(1) if rss else '-'))
                except (OSError, ValueError, IndexError):
                    pass
        for stage in ['dc', 'pt']:
            p = ROOT/name/('build/'+stage+'.console.log')
            if p.exists():
                with p.open('rb') as stream:
                    stream.seek(max(0, p.stat().st_size-8192))
                    tail = stream.read().decode(errors='replace').splitlines()[-3:]
                print('  '+stage+': '+' | '.join(tail))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['check', 'run', 'status'])
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--cores-per-job', type=int, default=4)
    ap.add_argument('--memory-gib-per-job', type=int, default=10)
    ap.add_argument('--skip-pt', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if a.action == 'status':
        monitor()
        return
    spec = verify()
    if a.action == 'check':
        print('BATCH_SOURCE_VERIFIED projects=%d hold_optimization=OFF' % len(spec['projects']))
        return
    if not 1 <= a.jobs <= 4 or not 1 <= a.cores_per_job <= 8 or a.memory_gib_per_job < 1:
        raise SystemExit('invalid batch resource request')
    cpu, mem = resources()
    capacity = min(a.jobs, max(1, cpu//a.cores_per_job), len(spec['projects']))
    if mem is not None:
        capacity = min(capacity, mem//(a.memory_gib_per_job*1024**3))
    if capacity < 1:
        raise SystemExit('insufficient available memory for requested budget')
    state = dict(jobs=capacity, cores_per_job=a.cores_per_job, available_logical_cores=cpu,
                 available_memory_bytes=mem, scope=spec['scope'], hold_optimization=False,
                 projects={n: dict(stage='planned') for n in spec['projects']})
    if a.dry_run:
        print(json.dumps(dict(dry_run=True, plan=state), indent=2))
        return
    if spec.get('development_dirty'):
        raise SystemExit('development batch cannot launch CAD; export a clean committed release')
    for tool in [DC]+([] if a.skip_pt else [PT]):
        if not os.path.isfile(tool) or not os.access(tool, os.X_OK):
            raise SystemExit('missing CAD executable '+tool)
    env = dict(os.environ, KWT_JOB_CORES=str(a.cores_per_job), KWT_PT_RUN='pt_batch')
    env.pop('KWT_GATE_SAIF', None)
    if not a.skip_pt:
        lc = shutil.which('lc_shell')
        if lc and lc.endswith('/bin/lc_shell'):
            env['SYNOPSYS_LC_ROOT'] = str(Path(lc).parent.parent)
        if not os.access(os.path.join(env.get('SYNOPSYS_LC_ROOT', ''), 'bin/lc_shell'), os.X_OK):
            raise SystemExit('LC path missing; preserve evidence and bind actual SYNOPSYS_LC_ROOT')
    with (ROOT/'launch.lock').open('x') as stream:
        stream.write(str(os.getpid())+'\n')
    save(state)
    # Serial short vendor prechecks avoid simultaneous VCS license requests.
    for name in state['projects']:
        project = ROOT/name
        (project/'build').mkdir(exist_ok=True)
        row = state['projects'][name]
        try:
            row['stage'] = 'vendor_precheck'; save(state)
            stage_check(project, [sys.executable, 'flow/project.py', 'preflight'], project/'build/preflight.log')
            stage_check(project, ['bash', 'flow/run_sram_contract.sh'], project/'build/vendor_contract.console.log')
            row['stage'] = 'queued'
        except Exception as error:
            row.update(stage='failed_precheck', error=str(error))
        save(state)
    queue = [n for n, row in state['projects'].items() if row['stage'] == 'queued']
    active = {}
    def start(name, stage):
        project = ROOT/name
        log = (project/('build/'+stage+'.console.log')).open('x')
        command = [DC, '-f', 'flow/dc.tcl', '-output_log_file', 'build/dc.log'] if stage == 'dc' else [PT, '-f', 'flow/pt.tcl']
        try:
            p = subprocess.Popen(command, cwd=str(project), env=env, stdout=log, stderr=subprocess.STDOUT)
        except Exception:
            log.close()
            raise
        active[name] = (p, log, stage)
        state['projects'][name].update(stage=stage+'_running', pid=p.pid, started_UTC=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        save(state)
    while queue or active:
        while queue and len(active) < capacity:
            name = queue.pop(0)
            try:
                start(name, 'dc')
            except Exception as error:
                state['projects'][name].update(stage='failed_launch', error=str(error))
                save(state)
        for name, (p, log, stage) in list(active.items()):
            code = p.poll()
            if code is None:
                continue
            log.close(); del active[name]
            row = state['projects'][name]
            try:
                if code:
                    raise RuntimeError(stage+' exit='+str(code))
                if stage == 'dc':
                    accept_dc(ROOT/name, row)
                    if not a.skip_pt:
                        try:
                            start(name, 'pt')
                        except Exception as error:
                            row.update(stage='failed_pt_launch', error=str(error))
                            save(state)
                        continue
                else:
                    accept_pt(ROOT/name, row)
                row['stage'] = 'reports_done' if stage == 'pt' else 'dc_done'
            except Exception as error:
                row.update(stage='failed_'+stage, error=str(error))
            row['return_code'] = code
            save(state)
        if active:
            time.sleep(5)
    print('BATCH_FINISHED; report generation is not timing/functional signoff')
    monitor()


if __name__ == '__main__':
    main()
