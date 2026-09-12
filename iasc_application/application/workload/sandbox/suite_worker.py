"""Trusted one-suite supervisor. Candidate code runs only in a strict child."""
import base64
import hashlib
import json
import os
import random
import resource
import runpy
import select
import signal
import sys
import tempfile
import time


def emit(value):
    print(json.dumps(value, sort_keys=True, separators=(',', ':')), flush=True)


def main():
    with open('/in/payload.json', encoding='utf-8') as handle:
        payload = json.load(handle)
    for field in ('solution', 'test'):
        if hashlib.sha256(payload[field].encode('utf-8')).hexdigest() != payload[field + '_sha256']:
            raise RuntimeError('input hash mismatch: ' + field)
    if payload['suite_timeout_seconds'] != 3.0:
        raise RuntimeError('unexpected suite timeout')
    if os.path.isdir('/opt/site-packages'):
        sys.path.append('/opt/site-packages')
    guard = runpy.run_path('/runner/sandbox_guard.py')
    result_reader, result_writer = os.pipe()
    start_reader, start_writer = os.pipe()
    suite_start = time.monotonic()
    with tempfile.TemporaryFile() as candidate_stdout, tempfile.TemporaryFile() as candidate_stderr:
        pid = os.fork()
        if pid == 0:
            os.close(result_reader)
            os.close(start_writer)
            os.dup2(candidate_stdout.fileno(), 1)
            os.dup2(candidate_stderr.fileno(), 2)
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
                guard['install_candidate_filter'](allow_fork=False)
                if os.read(start_reader, 1) != b'1':
                    raise RuntimeError('missing parent start handshake')
                os.close(start_reader)
            except BaseException as exc:
                os.write(result_writer, json.dumps({'status': 'infrastructure_error', 'error_type': type(exc).__name__}).encode())
                os._exit(70)
            try:
                random.seed(0)
                candidate_namespace = {'__name__': 'candidate'}
                # Official HumanEval tests reference helpers defined in the
                # prompt/program (HE32/33/38/50). Preserve those globals in a
                # separate dictionary before loading the unchanged test suite.
                exec(compile(payload['solution'], '<candidate>', 'exec'), candidate_namespace)
                check_namespace = dict(candidate_namespace)
                check_namespace['__name__'] = 'official_tests'
                exec(compile(payload['test'], '<official_humaneval_test>', 'exec'), check_namespace)
                check_namespace['check'](candidate_namespace[payload['entry_point']])
                child_result = {'status': 'pass', 'error_type': None}
            except BaseException as exc:
                child_result = {'status': 'fail', 'error_type': type(exc).__name__}
            # Candidate stdout is never used as the result channel.
            os.write(result_writer, json.dumps(child_result, separators=(',', ':')).encode())
            os.close(result_writer)
            os._exit(0)
        os.close(result_writer)
        os.close(start_reader)
        emit({'kind': 'suite_started', 'pid': pid, 'candidate_id': payload['candidate_id'],
              'task_id': payload['task_id'], 'job_digest': payload['job_digest'],
              'solution_sha256': payload['solution_sha256'], 'test_sha256': payload['test_sha256']})
        os.write(start_writer, b'1')
        os.close(start_writer)
        timed_out = False
        deadline = suite_start + 3.0
        while True:
            done, wait_status, usage = os.wait4(pid, os.WNOHANG)
            if done == pid:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                _, wait_status, usage = os.wait4(pid, 0)
                break
            select.select([result_reader], [], [], min(remaining, 0.01))
        raw = os.read(result_reader, 4096)
        os.close(result_reader)
        if timed_out:
            result = {'status': 'timeout', 'error_type': 'SuiteTimeout'}
        elif os.WIFEXITED(wait_status) and os.WEXITSTATUS(wait_status) == 0:
            try:
                result = json.loads(raw)
                if result.get('status') not in ('pass', 'fail'):
                    raise ValueError('invalid child status')
            except (ValueError, TypeError):
                result = {'status': 'fail', 'error_type': 'ChildResultInvalid'}
        elif os.WIFEXITED(wait_status) and os.WEXITSTATUS(wait_status) == 70 and raw:
            result = {'status': 'infrastructure_error', 'error_type': 'ChildSandboxSetup'}
        else:
            reason = 'ProcessSignal_' + str(os.WTERMSIG(wait_status)) if os.WIFSIGNALED(wait_status) else 'ProcessExit_' + str(os.WEXITSTATUS(wait_status))
            result = {'status': 'fail', 'error_type': reason}
        result.update({'kind': 'suite_result', 'candidate_id': payload['candidate_id'],
                       'task_id': payload['task_id'], 'job_digest': payload['job_digest'],
                       'actual_starts': 1, 'actual_start_known': True,
                       'child_pid': pid, 'cpu_seconds': usage.ru_utime + usage.ru_stime,
                       'wall_seconds': time.monotonic() - suite_start,
                       'solution_sha256': payload['solution_sha256'], 'test_sha256': payload['test_sha256'],
                       'suite_timeout_seconds': 3.0, 'wait_status': wait_status})
        for name, stream in (('stdout', candidate_stdout), ('stderr', candidate_stderr)):
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(0)
            result['candidate_' + name + '_bytes'] = size
            result['candidate_' + name + '_base64'] = base64.b64encode(stream.read(65536)).decode('ascii')
            result['candidate_' + name + '_truncated'] = size > 65536
        emit(result)


if __name__ == '__main__':
    main()
