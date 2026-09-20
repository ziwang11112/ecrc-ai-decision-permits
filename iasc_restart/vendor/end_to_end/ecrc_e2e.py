"""NEW atomic raw-request issuance wrapper around the frozen ECRC runtime.

The original runtime files are unchanged. Only inside issue(), original
per-method transaction calls are contained by a new outer transaction.
"""
from contextlib import closing
from datetime import timedelta
import json
import threading

from legacy_snapshot.ecrc_adapter import Adapter as DeliveryAdapter
from agentic_eeg_dm.governance import (
    SQLiteCapacityLedger, OrderedAdjudicator, PolicyManifest, ProposalEnvelope,
    EvidenceEnvelope, canonical_json, canonical_hash,
)
from agentic_eeg_dm.governance.canonical import normalize_timestamp, parse_timestamp


class ContainedConnection:
    """An inner operation cannot commit/close/rollback its enclosing issuance."""
    def __init__(self, raw): self.raw = raw
    def execute(self, sql, params=()):
        if sql.strip().upper().startswith('BEGIN'):
            return self.raw.execute('SELECT 1')
        return self.raw.execute(sql, params)
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass
    def __getattr__(self, key): return getattr(self.raw, key)


class JournalLedger(SQLiteCapacityLedger):
    def __init__(self, path):
        self.context = threading.local()
        super().__init__(path)
    def _connect(self):
        raw = getattr(self.context, 'raw', None)
        if raw is not None: return ContainedConnection(raw)
        conn = super()._connect()
        conn.execute('PRAGMA synchronous=FULL')
        return conn
    def reserve(self, *args, **kwargs):
        result = super().reserve(*args, **kwargs)
        callback = getattr(self.context, 'hook', None)
        if callback: callback('after_reservation')
        return result
    def release(self, *args, **kwargs):
        result = super().release(*args, **kwargs)
        callback = getattr(self.context, 'hook', None)
        if callback: callback('after_release')
        return result


class Adapter(DeliveryAdapter):
    def __init__(self, db_path, policy=None):
        super().__init__(db_path)
        self.ledger = JournalLedger(db_path)
        with closing(self.ledger._connect()) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS requests(
                decision_id TEXT PRIMARY KEY, request_json TEXT NOT NULL,
                request_hash TEXT NOT NULL, received_at TEXT NOT NULL,
                state TEXT NOT NULL, permit_json TEXT, cancelled_at TEXT)''')
        if policy is not None:
            obj = PolicyManifest.from_dict(policy)
            if canonical_json(obj.to_dict()) != canonical_json(policy):
                raise ValueError('noncanonical policy input')
            self.ledger.register_policy(obj)

    def ingest(self, request, at):
        if set(request) != {'policy', 'proposal', 'evidence'}:
            raise ValueError('invalid raw request envelope')
        decision = request['proposal']['decision_id']
        data, fingerprint = canonical_json(request), canonical_hash(request)
        with closing(self.ledger._connect()) as db:
            try:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT * FROM requests WHERE decision_id=?', (decision,)).fetchone()
                if old:
                    if old['request_hash'] != fingerprint: raise ValueError('conflicting raw request')
                    db.commit(); return dict(old)
                active = db.execute('SELECT manifest_json FROM active_policies WHERE policy_id=?',
                                    (request['policy']['policy_id'],)).fetchone()
                if active is None or active['manifest_json'] != canonical_json(request['policy']):
                    raise ValueError('request policy not registered')
                db.execute('INSERT INTO requests VALUES(?,?,?,?,?,NULL,NULL)',
                           (decision, data, fingerprint, normalize_timestamp(at), 'received'))
                db.commit()
            except BaseException:
                db.rollback(); raise
        return self.get_request(decision)

    def get_request(self, decision_id):
        with closing(self.ledger._connect()) as db:
            row = db.execute('SELECT * FROM requests WHERE decision_id=?', (decision_id,)).fetchone()
            return dict(row) if row else None

    def get_permit(self, decision_id):
        row = self.get_request(decision_id)
        return json.loads(row['permit_json']) if row and row['permit_json'] else None

    def issue(self, decision_id, at, hook=None):
        hook = hook or (lambda name: None)
        db = self.ledger._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM requests WHERE decision_id=?', (decision_id,)).fetchone()
            if row is None: raise ValueError('raw request was not durably received')
            if row['state'] == 'cancelled': db.commit(); return None
            if row['permit_json']:
                permit = json.loads(row['permit_json']); db.commit(); return permit
            raw = json.loads(row['request_json'])
            policy = PolicyManifest.from_dict(raw['policy'])
            proposal = ProposalEnvelope.from_dict(raw['proposal'])
            evidence = EvidenceEnvelope.from_dict(raw['evidence'])
            if any(canonical_json(raw[k]) != canonical_json(v.to_dict()) for k,v in
                   [('policy',policy),('proposal',proposal),('evidence',evidence)]):
                raise ValueError('raw input is not canonical')
            self.ledger.context.raw = db
            self.ledger.context.hook = hook
            permit = OrderedAdjudicator(self.ledger, permit_ttl_seconds=3600).adjudicate(
                policy, proposal, evidence, at=at).to_dict()
            state = 'issued' if permit['route'] in ('alert','review') else 'nonaction'
            db.execute('UPDATE requests SET state=?,permit_json=? WHERE decision_id=?',
                       (state,canonical_json(permit),decision_id))
            hook('before_issue_commit')
            db.commit()
            self.ledger.context.raw = None
            self.ledger.context.hook = None
            hook('after_issue_commit')
            return permit
        except BaseException:
            db.rollback(); raise
        finally:
            self.ledger.context.raw = None
            self.ledger.context.hook = None
            db.close()

    def arm(self, permit, at):
        row = self.get_request(permit['decision_id'])
        if row is None or row['state'] == 'cancelled': raise ValueError('request is absent/cancelled')
        # A cleanup race cannot create a new grant: inherited arm checks the
        # held reservation under BEGIN IMMEDIATE; cleanup checks job absence
        # while holding the same writer serialization boundary.
        return super().arm(permit, at)

    def cleanup(self, at):
        now = parse_timestamp(at)
        cancelled, retained = [], []
        with closing(self.ledger._connect()) as db:
            try:
                db.execute('BEGIN IMMEDIATE')
                rows = db.execute("SELECT * FROM requests WHERE state IN ('received','issued')").fetchall()
                for row in rows:
                    permit = json.loads(row['permit_json']) if row['permit_json'] else None
                    if permit:
                        job = db.execute('SELECT 1 FROM delivery_outbox WHERE permit_id=?',(permit['permit_id'],)).fetchone()
                        if job: retained.append(row['decision_id']); continue
                        eligible = now >= parse_timestamp(permit['expires_at'])
                    else:
                        eligible = now >= parse_timestamp(row['received_at']) + timedelta(seconds=60)
                    if not eligible: continue
                    if permit and permit['reservation_id']:
                        self.ledger._release_reservation_conn(db,permit['reservation_id'],at=normalize_timestamp(at))
                    db.execute("UPDATE requests SET state='cancelled',cancelled_at=? WHERE decision_id=?",
                               (normalize_timestamp(at),row['decision_id']))
                    cancelled.append(row['decision_id'])
                db.commit()
            except BaseException:
                db.rollback(); raise
        return {'cancelled':cancelled,'armed_or_completed_retained':retained}

    def snapshot(self):
        result = super().snapshot()
        with closing(self.ledger._connect()) as db:
            result['requests'] = [dict(row) for row in db.execute('SELECT * FROM requests ORDER BY decision_id')]
            result['permits'] = [json.loads(row['permit_json']) for row in result['requests'] if row['permit_json']]
        return result
