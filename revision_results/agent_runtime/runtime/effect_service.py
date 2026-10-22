"""Same-process durable effect service for the offline shared-budget fixture.

The trusted runner launches candidates only in the copied sandbox. This module
does not simulate results, inject faults, enforce the three-job study quota, or
retry an unresolved execution. Its independent safety cap counts durable launch
attempts, including attempts whose start state remains unknown.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sqlite3
import threading


HERE = Path(__file__).resolve().parent
IDENTITY_FIELDS = ('task_id', 'candidate_id', 'solution_sha256', 'test_sha256', 'runner_sha256')
PAYLOAD_FIELDS = {'decision_id', 'route', 'permitted_claim_ids', 'used_evidence_ids'}
SCHEMA = 'offline-shared-effect-service-v1'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def save(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(canonical(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def valid_key(key):
    if type(key) is not str or not 0 < len(key.encode('utf-8')) <= 512:
        raise ValueError('invalid idempotency key')


def finite_nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


class EffectService:
    """One database gives all tasks globally unique effect identifiers.

    Uniqueness is per idempotency key, not per job: a caller that changes the key
    may cause a duplicate job, and audit reports that duplicate honestly.
    """
    def __init__(self, run_dir, safety_cap=8):
        if type(safety_cap) is not int or safety_cap <= 0:
            raise ValueError('safety_cap must be a positive integer')
        self.directory = Path(run_dir).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'service.sqlite'
        self.safety_cap = safety_cap
        self.lock = threading.RLock()
        spec = importlib.util.spec_from_file_location('_shared_trusted_runner', HERE / 'workload/job_runner.py')
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        self.runner_hash = self.runner.runner_sha256()
        # Fail before any job is accepted if ordinary Windows path handling
        # cannot reliably collect the longest generated runner artifact.
        longest = self.directory / 'j00000001/work/sandbox_output/launcher_receipt.json'
        if os.name == 'nt' and len(str(longest)) >= 240:
            raise ValueError('service run path is too long for verified artifact collection')
        with closing(self.connect()) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS config(singleton INTEGER PRIMARY KEY CHECK(singleton=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts(
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
                    job_hash TEXT NOT NULL, job_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('running','complete','aborted')),
                    run_dir TEXT NOT NULL, accepted_at TEXT NOT NULL,
                    result_json TEXT, error_json TEXT);
                CREATE TABLE IF NOT EXISTS effects(
                    effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE REFERENCES attempts(idempotency_key),
                    ack_json TEXT NOT NULL);
            ''')
            body = canonical({'schema': SCHEMA, 'safety_cap': safety_cap, 'runner_sha256': self.runner_hash})
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT body FROM config WHERE singleton=1').fetchone()
            if old and old['body'] != body:
                raise ValueError('service configuration changed across restart')
            if not old:
                db.execute('INSERT INTO config VALUES (1,?)', (body,))
            db.commit()

    def connect(self, readonly=False):
        target = self.path.as_uri() + '?mode=ro' if readonly else str(self.path)
        db = sqlite3.connect(target, uri=readonly, timeout=30.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        if readonly:
            db.execute('PRAGMA query_only=ON')
        else:
            db.execute('PRAGMA synchronous=FULL')
        return db

    def validate_job(self, key, payload, job):
        valid_key(key)
        if type(payload) is not dict or set(payload) != PAYLOAD_FIELDS or type(job) is not dict:
            raise ValueError('incorrect job or payload fields')
        # Round-tripping snapshots the caller's mutable dictionaries and rejects
        # non-finite values before durable acceptance or sandbox dispatch.
        job = json.loads(canonical(job))
        payload = json.loads(canonical(payload))
        required = IDENTITY_FIELDS + ('solution', 'test', 'entry_point', 'job_hash', 'decision_id')
        if any(type(job.get(field)) is not str or not job[field] for field in required):
            raise ValueError('missing or invalid immutable job field')
        for field in ('solution', 'test'):
            if hashlib.sha256(job[field].encode('utf-8')).hexdigest() != job[field + '_sha256']:
                raise ValueError(field + ' hash mismatch')
        if job['runner_sha256'] != self.runner_hash or self.runner.runner_sha256() != self.runner_hash:
            raise ValueError('trusted runner bundle hash mismatch')
        job_hash = digest({field: job[field] for field in IDENTITY_FIELDS})
        if job['job_hash'] != job_hash or job['decision_id'] != 'verify:' + job_hash:
            raise ValueError('full job identity hash mismatch')
        expected = {'decision_id': job['decision_id'], 'route': 'alert',
                    'permitted_claim_ids': ['run_verification'], 'used_evidence_ids': ['job:' + job_hash]}
        if payload != expected:
            raise ValueError('payload does not bind the exact job, route and claim')
        return payload, job

    @staticmethod
    def validate_result(result, job):
        if type(result) is not dict or result.get('status') not in ('pass', 'fail', 'timeout'):
            raise ValueError('sandbox did not return a completed finite-suite result')
        canonical(result)
        if result.get('actual_start_known') is not True or type(result.get('actual_starts')) is not int or result['actual_starts'] != 1:
            raise ValueError('sandbox actual start count is unknown or invalid')
        if result.get('job_digest') != job['job_hash']:
            raise ValueError('sandbox returned the wrong full job digest')
        if any(result.get(field) != job[field] for field in IDENTITY_FIELDS):
            raise ValueError('sandbox returned the wrong task/candidate/source/test/runner identity')
        if any(not finite_nonnegative(result.get(field)) for field in ('cpu_seconds', 'wall_seconds', 'launcher_wall_seconds')):
            raise ValueError('sandbox returned an invalid measured duration')

    @staticmethod
    def read_ack(db, key):
        row = db.execute('''SELECT e.effect_id,e.ack_json,a.* FROM effects e
            JOIN attempts a ON a.idempotency_key=e.idempotency_key WHERE e.idempotency_key=?''', (key,)).fetchone()
        if row is None:
            return None
        ack = json.loads(row['ack_json'])
        result = json.loads(row['result_json'])
        if (row['state'] != 'complete' or ack.get('effect_id') != row['effect_id']
                or ack.get('idempotency_key') != key or ack.get('job_hash') != row['job_hash']
                or ack.get('payload') != json.loads(row['payload_json'])
                or ack.get('payload_hash') != row['payload_hash'] or digest(ack['payload']) != row['payload_hash']
                or ack.get('job_result') != result or ack.get('result_hash') != digest(result)):
            raise ValueError('stored effect acknowledgement failed integrity checks')
        EffectService.validate_result(result, json.loads(row['job_json']))
        return ack

    def post(self, key, payload, job):
        payload, job = self.validate_job(key, payload, job)
        payload_text, job_text = canonical(payload), canonical(job)
        with self.lock, closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM attempts WHERE idempotency_key=?', (key,)).fetchone()
            if old:
                if old['payload_json'] != payload_text or old['job_json'] != job_text:
                    raise ValueError('idempotency key bound to a different payload or job')
                ack = self.read_ack(db, key)
                if ack is None:
                    raise RuntimeError('unresolved service attempt; automatic retry is forbidden')
                db.commit()
                return ack
            count = db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
            if count >= self.safety_cap:
                raise RuntimeError('independent service safety cap reached')
            run_dir = self.directory / ('j' + format(count + 1, '08d'))
            run_dir.mkdir(exist_ok=False)
            save(run_dir / 'bound_job.json', job)
            save(run_dir / 'payload.json', {'idempotency_key': key, 'payload': payload})
            db.execute('''INSERT INTO attempts(idempotency_key,payload_hash,payload_json,
                job_hash,job_json,state,run_dir,accepted_at) VALUES (?,?,?,?,?,'running',?,?)''',
                (key, digest(payload), payload_text, job['job_hash'], job_text, str(run_dir), now()))
            db.commit()  # The safety hold is durable before invoking any sandbox.
            result = None
            try:
                result = self.runner.run_job(job, run_dir / 'work')
                save(run_dir / 'raw_result.json', result)
                self.validate_result(result, job)
                db.execute('BEGIN IMMEDIATE')
                effect_id = db.execute('INSERT INTO effects(idempotency_key,ack_json) VALUES (?,?)', (key, '{}')).lastrowid
                ack = {'effect_id': effect_id, 'idempotency_key': key,
                       'payload_hash': digest(payload), 'payload': payload, 'committed_at': now(),
                       'job_result': result, 'result_hash': digest(result), 'job_hash': job['job_hash']}
                db.execute('UPDATE effects SET ack_json=? WHERE effect_id=?', (canonical(ack), effect_id))
                db.execute("UPDATE attempts SET state='complete',result_json=? WHERE idempotency_key=?", (canonical(result), key))
                self.read_ack(db, key)
                db.commit()  # No ACK is returned before its complete result commits.
                return ack
            except BaseException as exc:
                if db.in_transaction:
                    db.rollback()
                # A malformed/unknown result is retained, never replaced with a
                # synthetic zero-start observation. Raw runner artifacts remain.
                try:
                    result_text = canonical(result) if type(result) is dict else None
                except (ValueError, TypeError):
                    result_text = None
                error = {'error_type': type(exc).__name__, 'message': str(exc),
                         'automatic_retry_permitted': False}
                try:
                    db.execute("UPDATE attempts SET state='aborted',result_json=?,error_json=? WHERE idempotency_key=? AND state='running'",
                               (result_text, canonical(error), key))
                    db.commit()
                    save(run_dir / 'service_error.json', error)
                except Exception as recording_error:
                    exc.add_note('Failure recording also failed: ' + type(recording_error).__name__)
                raise

    def get(self, key):
        """Read a durable ACK; absence never authorizes another sandbox start."""
        valid_key(key)
        with closing(self.connect(readonly=True)) as db:
            return self.read_ack(db, key)

    def audit(self):
        """Observed execution counts; unknown starts are explicitly not zeros.

        pass_count counts completed passing jobs; passed_task_ids additionally
        supports unique-task counting. completed_job_hashes is unique and sorted.
        Duration totals are observed sums and marked incomplete if any unknown.
        """
        with closing(self.connect(readonly=True)) as db:
            db.execute('BEGIN')
            rows = [dict(row) for row in db.execute('SELECT * FROM attempts ORDER BY attempt_id')]
            for row in rows:
                if row['state'] == 'complete':
                    self.read_ack(db, row['idempotency_key'])
        summaries, started_jobs, completed_jobs, passed_tasks = [], set(), set(), set()
        actual_starts = unknown = passed = 0
        cpu = wall = 0.0
        durations_known = True
        for row in rows:
            result = json.loads(row['result_json']) if row['result_json'] else {}
            count = result.get('actual_starts')
            count_valid = type(count) is int and count >= 0
            known = result.get('actual_start_known') is True and count_valid
            if not known:
                unknown += 1
            observed = count if count_valid else 0
            actual_starts += observed
            if observed:
                started_jobs.add(row['job_hash'])
            if row['state'] == 'complete':
                completed_jobs.add(row['job_hash'])
                if result['status'] == 'pass':
                    passed += 1
                    passed_tasks.add(result['task_id'])
            for field in ('cpu_seconds', 'wall_seconds'):
                if not finite_nonnegative(result.get(field)):
                    durations_known = False
            if finite_nonnegative(result.get('cpu_seconds')):
                cpu += result['cpu_seconds']
            if finite_nonnegative(result.get('wall_seconds')):
                wall += result['wall_seconds']
            summaries.append({'attempt_id': row['attempt_id'], 'idempotency_key': row['idempotency_key'],
                'job_hash': row['job_hash'], 'task_id': json.loads(row['job_json'])['task_id'],
                'state': row['state'], 'run_dir': row['run_dir'], 'status': result.get('status'),
                'actual_starts': count if count_valid else None, 'actual_start_known': known,
                'error': json.loads(row['error_json']) if row['error_json'] else None})
        return {'attempt_count': len(rows), 'actual_starts': actual_starts,
                'actual_start_count_known': unknown == 0, 'actual_starts_is_lower_bound': unknown != 0,
                'unknown_start_count': unknown, 'duplicate_starts': actual_starts - len(started_jobs),
                'duplicate_start_count_known': unknown == 0, 'pass_count': passed,
                'completed_job_hashes': sorted(completed_jobs), 'passed_task_ids': sorted(passed_tasks),
                'passed_task_count': len(passed_tasks), 'cpu_seconds': cpu, 'wall_seconds': wall,
                'duration_totals_complete': durations_known, 'safety_cap': self.safety_cap,
                'attempts': summaries, 'execution_scope': 'same-process trusted control; actual isolated sandbox jobs'}
