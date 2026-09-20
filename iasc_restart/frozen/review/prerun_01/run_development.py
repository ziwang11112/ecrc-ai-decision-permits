"""Prepare a frozen protocol, then run all eight bounded development cells."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
import urllib.request
from common import ARMS, EXPIRY, HERE, LIMIT, RAW, ROOT, S8, T0, TB, TC, TD, TR, canonical, jobs, read, write

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest():
    files = list(HERE.glob('*.py')) + [HERE / 'PROTOCOL.md']
    files += [RAW / 'direct_client.py', S8 / 'ecrc_e2e.py', S8 / 'inputs/distinct_contenders.json']
    files += list((S8 / 'legacy_snapshot').rglob('*.py'))
    files += [ROOT / 'output/iasc_overleaf/main.tex', *sorted((ROOT / 'output/iasc_overleaf/content').glob('*.tex'))]
    return {str(p.resolve()): sha(p) for p in sorted(set(files))}


class Process:
    def __init__(self, args, log):
        self.log, self.lines, self.q = Path(log), [], queue.Queue()
        self.saved = False
        self.p = subprocess.Popen([sys.executable, '-B', *map(str, args)], cwd=HERE,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding='utf-8', creationflags=FLAGS)
        def drain():
            for line in self.p.stdout:
                self.lines.append(line)
                self.q.put(line)
        self.thread = threading.Thread(target=drain, daemon=True)
        self.thread.start()

    def event(self):
        try:
            line = self.q.get(timeout=15)
        except queue.Empty:
            raise RuntimeError('child produced no event: ' + self.log.name)
        value = json.loads(line)
        if value.get('event') == 'error':
            raise RuntimeError(canonical(value))
        return value

    def command(self, value):
        self.p.stdin.write(canonical(value) + '\n')
        self.p.stdin.flush()
        return self.event()

    def kill(self):
        if self.p.poll() is None:
            self.p.kill()
        code = self.p.wait(timeout=10)
        self.thread.join(timeout=2)
        if not self.saved:
            self.log.write_text(''.join(self.lines) + '\nSTDERR\n' + self.p.stderr.read(), encoding='utf-8')
            self.saved = True
        return {'pid': self.p.pid, 'exit_code': code, 'terminated': code != 0}


def backup(source, target):
    if not source.exists():
        return
    src = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def run_cell(folder, arm, condition):
    folder.mkdir(parents=True, exist_ok=False)
    case = {'arm': arm, 'condition': condition, 'external_limit': LIMIT, 'jobs': jobs(),
            'synthetic_effects_only': True, 'all_input_jobs_in_denominator': 4,
            'queue_A_dispatch_deadline': '2026-09-12T13:00:10.000000Z' if condition == 'mixed' else None,
            'scope': 'mixed-workflow-development-v1'}
    write(folder / 'CASE.json', case)
    events, processes, failure = [], [], None
    worker = None
    def record(value):
        events.append(value)
        write(folder / 'TRACE.json', {'events': events, 'failure': failure})
        return value
    def send(op, job=None, at=T0, **extra):
        command = {'op': op, 'at': at, **extra}
        if op == 'snapshot':
            command.pop('at')
        if job:
            command['job'] = job
        result = worker.command(command)
        return record({'command': command, **result})
    def checkpoint(name):
        result = send('snapshot')
        path = folder / 'checkpoints' / name
        path.mkdir(parents=True, exist_ok=False)
        backup(folder / 'client.sqlite', path / 'client.sqlite')
        backup(folder / 'sink.sqlite', path / 'sink.sqlite')
        write(path / 'CLIENT_OBSERVATION.json', result)
        record({'event': 'checkpoint', 'name': name})
    def launch_worker(url, index):
        process = Process([HERE / 'worker.py', '--arm', arm, '--db', folder / 'client.sqlite', '--url', url],
                          folder / f'worker-{index}.log')
        processes.append(process)
        record(process.event())
        return process
    try:
        service = Process([S8 / 'legacy_snapshot/service.py', '--db', folder / 'sink.sqlite'], folder / 'service.log')
        processes.append(service)
        ready = service.event()
        upstream = 'http://127.0.0.1:' + str(ready['port'])
        record({'event': 'service_ready', **ready})
        proxy = Process([HERE / 'proxy.py', '--upstream', upstream, '--job-hash', jobs()[1]['job_hash'],
                         '--condition', condition, '--log', folder / 'PROXY.jsonl'], folder / 'proxy.log')
        processes.append(proxy)
        proxy_ready = proxy.event()
        url = 'http://127.0.0.1:' + str(proxy_ready['port'])
        worker = launch_worker(url, 0)
        send('issue_only', 'A', T0)
        if condition == 'normal':
            for name, at in [('A', T0), ('B', TB), ('C', TB), ('D', TB)]:
                send('send', name, at)
            checkpoint('normal_final')
        else:
            checkpoint('A_issued_or_queued')
            first = send('send', 'B', TB)
            if first['status'] != 'transport_unknown':
                raise RuntimeError('declared B response loss did not occur')
            descriptor = first['descriptor']
            # Shared queue stores its unacknowledged delivery envelope, never the hidden ACK.
            write(folder / 'QUEUE_REDELIVERY.json', {'job': 'B', 'descriptor': descriptor, 'acknowledged': False})
            checkpoint('B_unknown_before_restart')
            record({'event': 'client_killed_while_B_unknown', **worker.kill()})
            worker = launch_worker(url, 1)
            checkpoint('restarted_before_cleanup')
            send('expire_A', 'A', EXPIRY)
            checkpoint('A_expired_B_still_unknown')
            send('send', 'C', TC)
            send('send', 'D', TD)
            checkpoint('after_C_D_before_B_recovery')
            # Fixed fault schedule: release does not depend on sink DB or an arm's results.
            req = urllib.request.Request(url + '/release', data=b'', method='POST')
            with urllib.request.urlopen(req, timeout=5) as response:
                response.read()
            record({'event': 'fixed_response_window_released'})
            envelope = read(folder / 'QUEUE_REDELIVERY.json')
            send('recover', 'B', TR, descriptor=envelope['descriptor'])
            checkpoint('mixed_final')
    except Exception as exc:
        failure = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        for process in reversed(processes):
            process.kill()
        write(folder / 'TRACE.json', {'events': events, 'failure': failure})
    from audit_run import audit
    try:
        audited = audit(folder)
    except Exception as exc:
        audited = {'audit_failed': True, 'error': type(exc).__name__ + ': ' + str(exc)}
    write(folder / 'AUDIT.json', audited)
    result = {'arm': arm, 'condition': condition, 'failure': failure, 'audit': audited}
    write(folder / 'RESULT.json', result)
    print(canonical({'completed': folder.name, 'execution_failure': failure,
                     'audit_keys': list(audited)}), flush=True)
    return result


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    before = manifest()
    qa = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-v', 'test_direct_adapter'], cwd=HERE,
                        capture_output=True, text=True, encoding='utf-8', creationflags=FLAGS)
    (out / 'QA_LOG.txt').write_text(qa.stdout + '\n' + qa.stderr, encoding='utf-8')
    if qa.returncode:
        raise RuntimeError('QA failed; retained in ' + str(out))
    if manifest() != before:
        raise RuntimeError('sources changed during preparation')
    freeze = {'sources': before, 'python': sys.version, 'sqlite': sqlite3.sqlite_version,
              'cases': [{'arm': arm, 'condition': condition} for condition in ('normal', 'mixed')
                        for arm in (ARMS if condition == 'normal' else tuple(reversed(ARMS)))],
              'qa_returncode': qa.returncode, 'jobs': jobs(), 'external_limit': LIMIT,
              'scope': 'controlled synthetic development, not application efficacy'}
    write(out / 'FREEZE.json', freeze)
    for path in HERE.glob('*.py'):
        (out / path.name).write_bytes(path.read_bytes())
    print(canonical({'frozen_files': len(before), 'cells': len(freeze['cases']), 'qa_returncode': qa.returncode}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--freeze', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command == 'prepare':
        prepare(out)
        return
    freeze = read(args.freeze)
    if manifest() != freeze['sources']:
        raise RuntimeError('frozen source mismatch')
    out.mkdir(parents=True, exist_ok=False)
    write(out / 'FREEZE.json', freeze)
    results = []
    for cell in freeze['cases']:
        results.append(run_cell(out / (cell['condition'] + '__' + cell['arm']), **cell))
    unchanged = manifest() == freeze['sources']
    write(out / 'SUMMARY.json', {'cells': results, 'sources_unchanged': unchanged,
                                'model_calls': 0, 'model_api_cost_usd': 0, 'paper_changed': False,
                                'stage': 'bounded_synthetic_development_complete'})
    print(canonical({'completed_cells': len(results), 'sources_unchanged': unchanged}))


if __name__ == '__main__':
    main()
