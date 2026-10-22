"""Unchanged-adapter, stdlib-only CMC boundary checks and issuance measurements."""
from __future__ import annotations

import argparse
from contextlib import closing
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
import threading
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VENDOR = ROOT / 'online_agent/runtime/vendor'
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('_cmc_frozen_loader', VENDOR / 'adapters.py')
LOADER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LOADER)
ADAPTERS = {arm: LOADER.load_adapter(arm) for arm in ('ordinary', 'ecrc')}
BASE = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def stamp(value=None):
    return (value or datetime.now(timezone.utc)).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def observation():
    return {'utc': stamp(), 'monotonic_ns': time.perf_counter_ns()}


def write(path, body):
    Path(path).write_text(json.dumps(body, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def csvwrite(path, rows):
    if not rows:
        return
    with Path(path).open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sources():
    files = sorted(p for p in VENDOR.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    files += [Path(__file__), HERE / 'PROTOCOL.md']
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in files}


def environment():
    clock = time.get_clock_info('perf_counter')
    return {'python': sys.version, 'executable': sys.executable, 'sqlite': sqlite3.sqlite_version,
            'platform': platform.platform(), 'machine': platform.machine(), 'processor': platform.processor(),
            'logical_cpu_count': os.cpu_count(), 'processor_identifier': os.environ.get('PROCESSOR_IDENTIFIER'),
            'hostname': platform.node(), 'perf_counter': vars(clock), 'command': sys.argv,
            'cwd': str(Path.cwd()), 'started_at': stamp(), 'dependencies': 'Python standard library only',
            'scope': 'local synthetic authorization/issuance checks; no model, sandbox or service calls'}


def policy(capacity, expires=None, base=BASE):
    value = deepcopy(LOADER.TEMPLATE['policy'])
    value.update(policy_id='cmc-local-runtime-v1', issuer_id='trusted-local-cmc-test',
                 capacity_scope='session', alert_capacity=capacity, review_capacity=0,
                 effective_from=stamp(base - timedelta(days=1)),
                 expires_at=stamp(expires or base + timedelta(days=30)))
    return value


def request(pol, decision, scope, base=BASE):
    raw = deepcopy(LOADER.TEMPLATE)
    raw['policy'] = deepcopy(pol)
    raw['proposal'].update(decision_id=decision, subject_id='synthetic-subject', session_id=scope,
                           input_hash=digest({'decision': decision}), proposed_at=stamp(base),
                           score=0.8, uncertainty=0.2)
    raw['evidence'].update(decision_id=decision, created_at=stamp(base))
    raw['evidence']['items'][0].update(evidence_id='e-' + decision, observed_at=stamp(base),
                                      available_at=stamp(base), provenance_hash=digest({'evidence': decision}))
    return raw


def conn(adapter, arm):
    return adapter.ledger._connect() if arm == 'ecrc' else adapter._connect()


def pragmas(adapter, arm):
    with closing(conn(adapter, arm)) as db:
        return {name: db.execute('PRAGMA ' + name).fetchone()[0]
                for name in ('journal_mode', 'synchronous', 'busy_timeout', 'page_size')}


def audit(path, arm):
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        rows = lambda sql: [dict(r) for r in db.execute(sql)]
        requests = rows('SELECT decision_id,state,request_hash,permit_json FROM requests ORDER BY decision_id')
        if arm == 'ecrc':
            budgets = rows('SELECT policy_id,policy_revision,scope_key,resource,capacity_limit,reserved,committed FROM capacity_state')
            holds = rows('SELECT reservation_id,scope_key,resource,amount,status,permit_id,permit_hash FROM reservations')
            permits = rows('SELECT permit_id,permit_hash FROM issued_permits')
            jobs = rows('SELECT permit_id,idempotency_key,state,armed_at,permit_hash FROM delivery_outbox')
            receipts = db.execute('SELECT count(*) FROM receipt_log').fetchone()[0]
        else:
            budgets = [{**r, 'capacity_limit': r['ceiling'], 'reserved': r['held'], 'committed': r['spent']}
                       for r in rows('SELECT * FROM budgets')]
            holds = [dict(json.loads(r['document']), status=r['status']) for r in rows('SELECT document,status FROM holds')]
            permits = [{'permit_id': r['id'], 'permit_hash': r['digest']}
                       for r in rows('SELECT id,digest FROM permit_registry')]
            jobs = rows('SELECT permit_id,idempotency_key,state,armed_at,permit_hash FROM delivery')
            receipts = db.execute('SELECT count(*) FROM receipts').fetchone()[0]
        for budget in budgets:
            matching = [h for h in holds if h['scope_key'] == budget['scope_key'] and h['resource'] == budget['resource']]
            assert sum(h['amount'] for h in matching if h['status'] == 'reserved') == budget['reserved']
            assert sum(h['amount'] for h in matching if h['status'] == 'committed') == budget['committed']
            assert 0 <= budget['reserved'] + budget['committed'] <= budget['capacity_limit']
        issued = {p['permit_id']: p['permit_hash'] for p in permits}
        for row in requests:
            if row['permit_json']:
                permit = json.loads(row['permit_json'])
                assert issued[permit['permit_id']] == digest(permit)
                matching = [h for h in holds if h['permit_id'] == permit['permit_id']]
                assert len(matching) == 1 and matching[0]['permit_hash'] == digest(permit)
        for job in jobs:
            assert issued[job['permit_id']] == job['permit_hash']
            assert job['idempotency_key'] == job['permit_id']
        return {'request_count': len(requests), 'permit_count': len(permits), 'hold_count': len(holds),
                'held': sum(b['reserved'] for b in budgets), 'spent': sum(b['committed'] for b in budgets),
                'intent_count': len(jobs), 'receipt_count': receipts, 'budgets': budgets, 'jobs': jobs,
                'request_states': {state: sum(r['state'] == state for r in requests)
                                   for state in sorted({r['state'] for r in requests})},
                'hold_statuses': {state: sum(h['status'] == state for h in holds)
                                  for state in sorted({h['status'] for h in holds})},
                'checks_passed': True}


def validate_permit(permit):
    assert permit['route'] == 'alert'
    assert permit['permitted_claim_ids'] == ['notify']
    assert len(permit['used_evidence_ids']) == 1 and permit['reservation_id']


class ObservedConnection:
    """Observation only: unchanged SQL, parameters and original connection/commit."""
    def __init__(self, raw, events, attempted):
        self.raw, self.events, self.attempted = raw, events, attempted

    def execute(self, sql, parameters=()):
        sql_text = sql.strip().upper()
        if threading.current_thread().name == 'observed-arm' and sql_text == 'BEGIN IMMEDIATE':
            self.events['begin_attempt'] = observation()
            self.attempted.set()
            result = self.raw.execute(sql, parameters)
            self.events['lock_acquired'] = observation()
            return result
        result = self.raw.execute(sql, parameters)
        if threading.current_thread().name == 'observed-arm' and sql_text.startswith('INSERT INTO DELIVERY'):
            self.events['intent_inserted'] = observation()
        return result

    def commit(self):
        value = self.raw.commit()
        if threading.current_thread().name == 'observed-arm':
            self.events['commit_returned'] = observation()
        return value

    def __getattr__(self, name):
        return getattr(self.raw, name)


def boundary_case(folder, arm, case, repetition):
    folder.mkdir(parents=True, exist_ok=False)
    base = datetime.now(timezone.utc) if case == 'lock_crosses_expiry' else BASE
    expires = base + timedelta(seconds=2)
    pol = policy(1, expires, base)
    raw = request(pol, 'target', 'boundary', base)
    write(folder / 'fixture.json', raw)
    path = folder / 'client.sqlite'
    adapter = ADAPTERS[arm](path, pol)
    at = stamp() if case == 'lock_crosses_expiry' else stamp(base + timedelta(milliseconds=10))
    adapter.ingest(raw, at)
    permit = adapter.issue('target', at)
    validate_permit(permit)
    assert instant(permit['expires_at']) == expires
    write(folder / 'permit.json', permit)
    events, error, cleanup = {}, None, None
    if case == 'lock_crosses_expiry':
        attempted, done = threading.Event(), threading.Event()
        target = adapter.ledger if arm == 'ecrc' else adapter
        original = target._connect
        target._connect = lambda: ObservedConnection(original(), events, attempted)
        with closing(sqlite3.connect(path, isolation_level=None, timeout=30)) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            events['blocker_acquired'] = observation()
            def work():
                try:
                    events['invoked'] = observation()
                    events['supplied_at'] = stamp()
                    events['job'] = adapter.arm(permit, events['supplied_at'])
                    events['returned'] = observation()
                except BaseException:
                    events['worker_error'] = traceback.format_exc()
                finally:
                    done.set()
            worker = threading.Thread(target=work, name='observed-arm')
            worker.start()
            assert attempted.wait(5), 'worker did not attempt BEGIN'
            assert instant(events['supplied_at']) < expires
            assert not done.is_set() and 'lock_acquired' not in events
            while datetime.now(timezone.utc) < expires + timedelta(milliseconds=50):
                time.sleep(0.005)
            events['release_started'] = observation()
            blocker.commit()
            events['release_returned'] = observation()
            assert done.wait(10), 'worker did not complete after lock release'
            worker.join()
        target._connect = original
        assert 'worker_error' not in events, events.get('worker_error')
        for name in ('release_started', 'lock_acquired', 'intent_inserted', 'commit_returned', 'returned'):
            assert instant(events[name]['utc']) > expires
        ordered = ['invoked', 'begin_attempt', 'release_started', 'lock_acquired', 'intent_inserted', 'commit_returned', 'returned']
        for left, right in zip(ordered, ordered[1:]):
            assert events[left]['monotonic_ns'] <= events[right]['monotonic_ns']
            assert instant(events[left]['utc']) <= instant(events[right]['utc']), 'wall-clock regression'
        assert instant(events['job']['armed_at']) == instant(events['supplied_at'])
        expected_held, expected_jobs = 1, 1
    elif case == 'at_expiry_rejected':
        try:
            adapter.arm(permit, stamp(expires))
        except Exception as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)}
        assert error is not None
        expected_held, expected_jobs = 1, 0
    elif case == 'revocation_before_arm':
        adapter.revoke()
        try:
            adapter.arm(permit, at)
        except Exception as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)}
        assert error is not None
        expected_held, expected_jobs = 1, 0
    elif case == 'cleanup_before_arm':
        cleanup = adapter.cleanup(stamp(expires))
        try:
            adapter.arm(permit, at)
        except Exception as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)}
        assert error is not None
        expected_held, expected_jobs = 0, 0
    elif case == 'arm_before_cleanup_revocation':
        first = adapter.arm(permit, at)
        cleanup = adapter.cleanup(stamp(expires))
        adapter.revoke()
        repeated = adapter.arm(permit, stamp(expires + timedelta(seconds=1)))
        assert first == repeated
        events['original_job'], events['repeated_job'] = first, repeated
        expected_held, expected_jobs = 1, 1
    else:
        raise ValueError(case)
    state = audit(path, arm)
    assert (state['held'], state['spent'], state['intent_count'], state['receipt_count']) == (expected_held, 0, expected_jobs, 0)
    assert state['request_count'] == state['permit_count'] == 1
    snapshot = adapter.snapshot()
    assert (snapshot['reserved'], snapshot['committed'], snapshot['n_jobs'], snapshot['n_receipts']) == (expected_held, 0, expected_jobs, 0)
    trace = {'arm': arm, 'case': case, 'repetition': repetition, 'expiry': stamp(expires),
             'events': events, 'expected_error': error, 'cleanup': cleanup, 'state': state,
             'pragmas': pragmas(adapter, arm), 'passed': True, 'service_dispatch_performed': False}
    write(folder / 'trace.json', trace)
    result = {'arm': arm, 'case': case, 'repetition': repetition, 'passed': True, 'held': expected_held,
              'spent': 0, 'intents': expected_jobs, 'receipts': 0, 'lock_wait_ms': None,
              'commit_return_after_expiry_ms': None, 'supplied_before_expiry_ms': None}
    if case == 'lock_crosses_expiry':
        result.update(lock_wait_ms=(events['lock_acquired']['monotonic_ns']-events['begin_attempt']['monotonic_ns'])/1e6,
                      commit_return_after_expiry_ms=(instant(events['commit_returned']['utc'])-expires).total_seconds()*1000,
                      supplied_before_expiry_ms=(expires-instant(events['supplied_at'])).total_seconds()*1000)
    return result


def quantile(values, q):
    ordered = sorted(values)
    position = (len(ordered)-1)*q
    lower = int(position)
    upper = min(lower+1, len(ordered)-1)
    return ordered[lower] + (ordered[upper]-ordered[lower])*(position-lower)


def benchmark_phase(folder, arm, run, phase, count, warmups):
    folder.mkdir(parents=True, exist_ok=False)
    pol = policy(count + warmups)
    raws = [request(pol, f'measure-{i:04}', 'measured') for i in range(count)]
    warms = [request(pol, f'warm-{i:04}', 'warmup') for i in range(warmups)]
    at = stamp(BASE + timedelta(seconds=1))
    write(folder / 'fixture.json', {'policy_clock': at, 'requests': raws, 'warmups': warms})
    path = folder / 'client.sqlite'
    adapter = ADAPTERS[arm](path, pol)
    for raw in warms:
        adapter.ingest(raw, at)
        p = adapter.issue(raw['proposal']['decision_id'], at)
        validate_permit(p)
        if phase == 'issue_cached':
            assert adapter.issue(raw['proposal']['decision_id'], at) == p
    originals = {}
    if phase in ('issue_new', 'issue_cached'):
        for raw in raws:
            decision = raw['proposal']['decision_id']
            adapter.ingest(raw, at)
            if phase == 'issue_cached':
                originals[decision] = adapter.issue(decision, at)
                validate_permit(originals[decision])
    before = audit_before(adapter, arm)
    records, permits = [], []
    try:
        for i, raw in enumerate(raws):
            decision = raw['proposal']['decision_id']
            started = time.perf_counter_ns()
            if phase == 'ingest_issue_new':
                adapter.ingest(raw, at)
            permit = adapter.issue(decision, at)
            ended = time.perf_counter_ns()
            validate_permit(permit)
            if phase == 'issue_cached':
                assert permit == originals[decision]
            permits.append(permit)
            records.append({'arm': arm, 'run': run, 'phase': phase, 'request_index': i,
                            'decision_id': decision, 'permit_id': permit['permit_id'],
                            'started_ns': started, 'ended_ns': ended, 'latency_ms': (ended-started)/1e6})
    finally:
        csvwrite(folder / 'request_timings.csv', records)
        write(folder / 'returned_permits.json', permits)
    state = audit(path, arm)
    assert state['request_count'] == state['permit_count'] == state['hold_count'] == state['held'] == count+warmups
    assert state['spent'] == state['intent_count'] == state['receipt_count'] == 0
    assert len({p['permit_id'] for p in permits}) == count
    measured = [b for b in state['budgets'] if b['scope_key'] == 'measured']
    assert len(measured) == 1 and measured[0]['reserved'] == count
    snapshot = adapter.snapshot()
    assert snapshot['reserved'] == state['held'] and snapshot['committed'] == 0 and snapshot['n_jobs'] == 0
    if phase == 'issue_cached':
        assert before == audit_before(adapter, arm)
    pgs = pragmas(adapter, arm)
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        checkpoint = list(db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())
    state.update(pragmas=pgs, pre_timing_counts=before, checkpoint_result=checkpoint,
                 database_bytes=path.stat().st_size, wal_bytes=(Path(str(path)+'-wal').stat().st_size
                     if Path(str(path)+'-wal').exists() else 0))
    write(folder / 'state_audit.json', state)
    latencies = [r['latency_ms'] for r in records]
    return {'arm': arm, 'run': run, 'phase': phase, 'n_requests': count, 'warmups': warmups,
            'request_p50_ms': quantile(latencies, .5), 'request_p95_ms': quantile(latencies, .95),
            'request_min_ms': min(latencies), 'request_max_ms': max(latencies),
            'database_bytes': state['database_bytes'], 'held': state['held'], 'spent': 0,
            'intents': 0, 'receipts': 0, 'state_checks_passed': True}, records


def audit_before(adapter, arm):
    with closing(conn(adapter, arm)) as db:
        tables = ('requests', 'issued_permits', 'reservations', 'delivery_outbox', 'receipt_log') if arm == 'ecrc' else (
            'requests', 'permit_registry', 'holds', 'delivery', 'receipts')
        return {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in tables}


def execute(args):
    out = HERE / args.output
    assert out.parent.resolve() == HERE and not out.exists(), 'fresh child output directory required'
    out.mkdir()
    initial_sources = sources()
    write(out / 'SOURCE_HASHES.json', initial_sources)
    write(out / 'ENVIRONMENT.json', environment())
    started = time.perf_counter()
    bounds, runs, requests = [], [], []
    plan = {'mode': args.mode, 'count': args.count, 'warmups': args.warmups, 'benchmark_runs_per_arm': args.runs,
            'lock_repetitions_per_arm': args.lock_repetitions, 'arms': ['ordinary','ecrc'],
            'planned_boundaries': 2*(args.lock_repetitions+4), 'planned_benchmark_phases': 2*args.runs*3,
            'planned_timed_calls': 2*args.runs*3*args.count, 'source_hashes_sha256': sha(out/'SOURCE_HASHES.json')}
    write(out / 'PLAN.json', plan)
    current = 'initialization'
    try:
        for arm in ('ordinary','ecrc'):
            for rep in range(1,args.lock_repetitions+1):
                current = f'boundary/lock_crosses_expiry-{arm}-{rep}'
                bounds.append(boundary_case(out/current,arm,'lock_crosses_expiry',rep))
            for case in ('at_expiry_rejected','revocation_before_arm','cleanup_before_arm','arm_before_cleanup_revocation'):
                current = f'boundary/{case}-{arm}'
                bounds.append(boundary_case(out/current,arm,case,1))
        csvwrite(out/'boundary_summary.csv',bounds)
        print(json.dumps({'event':'boundaries_complete','passed':len(bounds),'output':str(out)}),flush=True)
        for run in range(1,args.runs+1):
            order = ('ordinary','ecrc') if run%2 else ('ecrc','ordinary')
            for arm in order:
                for phase in ('issue_new','ingest_issue_new','issue_cached'):
                    current = f'benchmark/run-{run}-{arm}-{phase}'
                    summary, raw = benchmark_phase(out/current,arm,run,phase,args.count,args.warmups)
                    runs.append(summary);requests.extend(raw)
                    csvwrite(out/'benchmark_runs.csv',runs)
                    csvwrite(out/'request_timings.csv',requests)
                    print(json.dumps({'event':'benchmark_phase_complete',**summary}),flush=True)
        grouped=[]
        for arm in ('ordinary','ecrc'):
            for phase in ('issue_new','ingest_issue_new','issue_cached'):
                values=[r for r in runs if r['arm']==arm and r['phase']==phase]
                row={'arm':arm,'phase':phase,'runs':len(values),'requests_per_run':args.count}
                for field in ('request_p50_ms','request_p95_ms'):
                    data=[r[field] for r in values]
                    row.update({field+'_across_run_median':statistics.median(data),field+'_across_run_min':min(data),field+'_across_run_max':max(data)})
                grouped.append(row)
        csvwrite(out/'benchmark_summary.csv',grouped)
        assert sources()==initial_sources,'source files changed during run'
        assert len(bounds)==plan['planned_boundaries'] and len(runs)==plan['planned_benchmark_phases'] and len(requests)==plan['planned_timed_calls']
        final={'status':'passed','planned':plan,'completed_boundaries':len(bounds),'completed_benchmark_phases':len(runs),
               'completed_timed_calls':len(requests),'unexpected_failures':0,'expected_rejections':6,
               'elapsed_seconds':time.perf_counter()-started,'completed_at':stamp(),'sources_unchanged':True}
        write(out/'RESULTS.json',final)
        write(out/'FAILURES.json',[])
        print(json.dumps(final),flush=True)
    except BaseException:
        failure={'status':'failed','case':current,'traceback':traceback.format_exc(),'completed_boundaries':len(bounds),
                 'completed_benchmark_phases':len(runs),'completed_at':stamp()}
        write(out/'FAILURES.json',[failure]);write(out/'RESULTS.json',failure)
        csvwrite(out/'boundary_summary.csv',bounds);csvwrite(out/'benchmark_runs.csv',runs)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=('smoke','formal'),required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--runs',type=int,default=5)
    parser.add_argument('--count',type=int,default=200)
    parser.add_argument('--warmups',type=int,default=10)
    parser.add_argument('--lock-repetitions',type=int,default=3)
    execute(parser.parse_args())
