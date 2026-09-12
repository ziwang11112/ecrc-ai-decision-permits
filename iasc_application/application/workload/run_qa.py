"""Trusted QA only: harmless selftests, official references, or development jobs.

No mode permits execution of evaluation-partition candidate code.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import time
from job_runner import digest_for, run_job, runner_sha256, save_json

ROOT = Path(__file__).resolve().parent


def make_job(candidate_id, task_id, solution, test, entry_point):
    job = {'candidate_id': candidate_id, 'task_id': task_id, 'solution': solution,
           'test': test, 'entry_point': entry_point,
           'solution_sha256': hashlib.sha256(solution.encode('utf-8')).hexdigest(),
           'test_sha256': hashlib.sha256(test.encode('utf-8')).hexdigest(),
           'runner_sha256': runner_sha256(), 'partition': 'qa_reference'}
    job['job_digest'] = digest_for(job)
    job['decision_id'] = 'verify:' + job['job_digest']
    return job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['selftest', 'reference', 'development'])
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    expected = {}
    if args.mode == 'selftest':
        examples = [
            ('pass', "import sys\ndef f(x):\n    print('candidate stdout')\n    print('candidate stderr', file=sys.stderr)\n    return x\n", 'def check(candidate):\n    assert candidate(7) == 7\n', 'pass'),
            ('fail', 'def f(x):\n    return x + 1\n', 'def check(candidate):\n    assert candidate(7) == 7\n', 'fail'),
            ('timeout', 'def f(x):\n    while True:\n        pass\n', 'def check(candidate):\n    candidate(7)\n', 'timeout'),
            ('isolation', "def f(x):\n    import os, socket\n    rejected = []\n    for action in (os.fork, socket.socket, lambda: os.execve('/usr/bin/true', ['/usr/bin/true'], {})):\n        try:\n            action()\n        except PermissionError:\n            rejected.append(True)\n        else:\n            rejected.append(False)\n    return (os.getuid(), os.path.exists('/home/zwang'), os.path.exists('/mnt/d'), tuple(rejected))\n", 'def check(candidate):\n    assert candidate(0) == (65534, False, False, (True, True, True))\n', 'pass'),
        ]
        jobs = []
        for name, solution, test, status in examples:
            job = make_job('qa_selftest::' + name, 'qa_selftest/' + name, solution, test, 'f')
            jobs.append(job)
            expected[job['candidate_id']] = status
    elif args.mode == 'reference':
        records = [json.loads(line) for line in gzip.decompress((ROOT / 'sources/HumanEval.jsonl.gz').read_bytes()).decode('utf-8').splitlines()]
        jobs = [make_job('canonical::' + item['task_id'], item['task_id'], item['prompt'] + item['canonical_solution'], item['test'], item['entry_point']) for item in records]
        expected = {job['candidate_id']: 'pass' for job in jobs}
    else:
        catalog = json.loads((ROOT / 'catalog.json').read_text(encoding='utf-8'))
        jobs = [job for job in catalog['jobs'] if job['partition'] == 'development']
        if len(jobs) != 80 or any(job['partition'] != 'development' for job in jobs):
            raise RuntimeError('development-only fence failed')
    started = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        pending = {executor.submit(run_job, job, out / f'job_{index:04d}'): job for index, job in enumerate(jobs)}
        for future in as_completed(pending):
            job = pending[future]
            result = future.result()
            results.append(result)
            print(json.dumps({'done': len(results), 'of': len(jobs), 'candidate_id': result['candidate_id'], 'status': result['status'], 'launcher_wall_seconds': result['launcher_wall_seconds']}), flush=True)
    counts = {status: sum(item['status'] == status for item in results) for status in ['pass', 'fail', 'timeout', 'infrastructure_error']}
    failures = [{'candidate_id': item['candidate_id'], 'expected': expected[item['candidate_id']], 'observed': item['status'], 'error_type': item.get('error_type')} for item in results if item['candidate_id'] in expected and item['status'] != expected[item['candidate_id']]]
    walls = [item['launcher_wall_seconds'] for item in results]
    summary = {'mode': args.mode, 'workers': args.workers, 'jobs': len(results), 'counts': counts,
               'expected_mismatches': failures, 'runner_sha256': runner_sha256(),
               'actual_starts': sum(item['actual_starts'] for item in results),
               'all_start_states_known': all(item['actual_start_known'] for item in results),
               'evaluation_candidates_executed': 0, 'elapsed_seconds': time.monotonic() - started,
               'launcher_wall_median_seconds': statistics.median(walls),
               'launcher_wall_p95_seconds': sorted(walls)[max(0, int(0.95 * len(walls) + 0.999) - 1)],
               'launcher_wall_max_seconds': max(walls),
               'note': 'Launcher timing includes WSL/namespace startup; reference and development are separate QA runs, not formal application outcomes.'}
    save_json(out / 'results.json', results)
    save_json(out / 'summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)
    if failures or counts['infrastructure_error']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
