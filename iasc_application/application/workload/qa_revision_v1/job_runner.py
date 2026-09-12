"""Cross-platform API for a pinned, isolated official HumanEval verification job.

This module never imports or executes a candidate in the host process.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
RUNNER_FILES = ('job_runner.py', 'sandbox/run_sandbox.sh', 'sandbox/sandbox_bootstrap.py',
                'sandbox/sandbox_guard.py', 'sandbox/suite_worker.py')
IDENTITY_FIELDS = ('task_id', 'candidate_id', 'solution_sha256', 'test_sha256', 'runner_sha256')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def runner_manifest():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in RUNNER_FILES}


def runner_sha256():
    return hashlib.sha256(canonical(runner_manifest())).hexdigest()


def digest_for(job):
    return hashlib.sha256(canonical({key: job[key] for key in IDENTITY_FIELDS})).hexdigest()


def linux_path(path):
    value = str(Path(path).resolve())
    if os.name != 'nt':
        return value
    value = value.replace('\\', '/')
    if len(value) < 3 or value[1:3] != ':/':
        raise ValueError('WSL path must be an absolute Windows drive path')
    return '/mnt/' + value[0].lower() + value[2:]


def save_json(path, value):
    with open(path, 'x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())


def run_job(job_dict, out_dir):
    """Run exactly one suite in a fresh namespace; preserve all raw artifacts.

    Pass/fail/timeout require a trusted supervisor start event. A missing event
    after infrastructure failure has unknown start state and is never a pass.
    cpu_seconds is wait4 child user+system CPU, not end-to-end host CPU.
    wall_seconds is the parent-supervised suite duration; launcher_wall_seconds
    additionally includes WSL/namespace startup and collection.
    """
    job = dict(job_dict)
    output = Path(out_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError('run_job requires an empty fresh output directory')
    for field in ('solution', 'test'):
        actual = hashlib.sha256(job[field].encode('utf-8')).hexdigest()
        if actual != job[field + '_sha256']:
            raise ValueError(field + ' hash mismatch before launch')
    if job['runner_sha256'] != runner_sha256():
        raise ValueError('runner bundle hash mismatch before launch')
    job_digest = digest_for(job)
    if job.get('decision_id', 'verify:' + job_digest) != 'verify:' + job_digest:
        raise ValueError('decision identity mismatch')
    payload = {key: job[key] for key in ('candidate_id', 'task_id', 'solution', 'solution_sha256',
                                       'test', 'test_sha256', 'entry_point')}
    payload.update({'job_digest': job_digest, 'suite_timeout_seconds': 3.0})
    input_dir = output / 'input'
    input_dir.mkdir()
    save_json(input_dir / 'payload.json', payload)
    sandbox_out = output / 'sandbox_output'
    shell_args = ['/usr/bin/env', 'SANDBOX_WALL_SECONDS=15', 'SANDBOX_CPU_SECONDS=10',
                  'SANDBOX_MEMORY_BYTES=536870912', 'SANDBOX_FILE_BYTES=1048576',
                  '/usr/bin/bash', linux_path(ROOT / 'sandbox/run_sandbox.sh'),
                  linux_path(input_dir), linux_path(sandbox_out), linux_path(ROOT / 'sandbox/suite_worker.py')]
    command = ['wsl.exe', '-d', 'Ubuntu-24.04', '--'] + shell_args if os.name == 'nt' else shell_args
    started = time.monotonic()
    invocation = {'job_digest': job_digest, 'candidate_id': job['candidate_id'], 'task_id': job['task_id'],
                  'command': command, 'phase': 'before_host_launch', 'candidate_source_on_host_executed': False}
    save_json(output / 'invocation.json', invocation)
    host_returncode = None
    launch_error = None
    host_launch_perf_counter_ns = None
    host_exit_perf_counter_ns = None
    try:
        with open(output / 'launcher_stdout.log', 'xb') as host_stdout, open(output / 'launcher_stderr.log', 'xb') as host_stderr:
            host_launch_perf_counter_ns = time.perf_counter_ns()
            process = subprocess.Popen(command, stdout=host_stdout, stderr=host_stderr, stdin=subprocess.DEVNULL, close_fds=True)
            launch_record = {'job_digest': job_digest, 'candidate_id': job['candidate_id'],
                      'task_id': job['task_id'], 'host_pid': process.pid, 'process_kind': 'wsl_or_bash_launcher',
                      'phase': 'host_process_started', 'monotonic_seconds': time.monotonic(),
                      'host_launch_perf_counter_ns': host_launch_perf_counter_ns,
                      'host_exit_perf_counter_ns': None}
            save_json(output / 'launch_started.json', launch_record)
            # The copied launcher has its own 15s timeout and 2s kill grace.
            host_returncode = process.wait(timeout=35)
            host_exit_perf_counter_ns = time.perf_counter_ns()
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        host_exit_perf_counter_ns = time.perf_counter_ns()
        launch_error = 'OuterControllerTimeout'
    except OSError as exc:
        launch_error = type(exc).__name__
        host_exit_perf_counter_ns = time.perf_counter_ns()
    if (output / 'launch_started.json').exists():
        launch_record.update({'phase': 'host_process_exited', 'host_exit_perf_counter_ns': host_exit_perf_counter_ns,
                              'returncode': host_returncode, 'launch_error': launch_error})
        save_json(output / 'launch.json', launch_record)
    events = []
    raw_stdout = sandbox_out / 'stdout.log'
    if raw_stdout.exists():
        for line in raw_stdout.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                event = json.loads(line)
                if type(event) is dict:
                    events.append(event)
            except ValueError:
                launch_error = launch_error or 'MalformedSupervisorOutput'
    start_events = [item for item in events if item.get('kind') == 'suite_started']
    result_events = [item for item in events if item.get('kind') == 'suite_result']
    for event in events:
        if event.get('job_digest') != job_digest:
            launch_error = launch_error or 'SupervisorIdentityMismatch'
    save_json(output / 'actual_start_events.json', start_events)
    valid = (not launch_error and host_returncode == 0 and len(start_events) == 1 and len(result_events) == 1)
    if valid:
        result = dict(result_events[0])
        if result.get('status') not in ('pass', 'fail', 'timeout', 'infrastructure_error'):
            valid = False
        for field in ('solution_sha256', 'test_sha256'):
            if result.get(field) != job[field] or start_events[0].get(field) != job[field]:
                valid = False
        if result.get('actual_starts') != 1:
            valid = False
    if not valid:
        result = {'status': 'infrastructure_error', 'error_type': launch_error or 'MissingOrInvalidSupervisorResult',
                  'actual_starts': len(start_events), 'actual_start_known': bool(start_events) or host_returncode is None,
                  'cpu_seconds': None, 'wall_seconds': None,
                  'solution_sha256': job['solution_sha256'], 'test_sha256': job['test_sha256']}
    for channel in ('stdout', 'stderr'):
        encoded = result.pop('candidate_' + channel + '_base64', '')
        with open(output / ('candidate_' + channel + '.log'), 'xb') as stream:
            stream.write(base64.b64decode(encoded))
    result.update({'candidate_id': job['candidate_id'], 'task_id': job['task_id'],
                   'job_digest': job_digest, 'runner_sha256': job['runner_sha256'],
                   'host_launch_perf_counter_ns': host_launch_perf_counter_ns,
                   'host_exit_perf_counter_ns': host_exit_perf_counter_ns,
                   'launcher_returncode': host_returncode, 'launcher_wall_seconds': time.monotonic() - started,
                   'raw_paths': {'output_dir': str(output), 'invocation': str(output / 'invocation.json'),
                                 'host_launch': str(output / 'launch.json'),
                                 'host_launch_started': str(output / 'launch_started.json'),
                                 'start_events': str(output / 'actual_start_events.json'),
                                 'supervisor_stdout': str(raw_stdout),
                                 'supervisor_stderr': str(sandbox_out / 'stderr.log'),
                                 'launcher_receipt': str(sandbox_out / 'launcher_receipt.json'),
                                 'candidate_stdout': str(output / 'candidate_stdout.log'),
                                 'candidate_stderr': str(output / 'candidate_stderr.log')}})
    save_json(output / 'result.json', result)
    return result
