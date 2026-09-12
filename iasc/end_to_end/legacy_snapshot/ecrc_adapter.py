"""NEW ECRC HTTP-delivery adapter. Never describes original simulator as HTTP-capable.

Authorization is committed at arm; an accepted durable intent survives expiry
or revocation. Unknown outcomes retain reservations. See PROTOCOL.md.
"""
from pathlib import Path
import sys,json,sqlite3
from contextlib import closing
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'source_snapshot'))
from agentic_eeg_dm.governance import SQLiteCapacityLedger,DecisionPermit,PolicyManifest,ExecutionReceipt,canonical_hash,canonical_json,stable_id
from agentic_eeg_dm.governance.canonical import normalize_timestamp,parse_timestamp,utc_now
from agentic_eeg_dm.governance.models import GENESIS_RECEIPT_HASH

class Adapter:
    def __init__(self,db_path):
        self.db_path=str(db_path);self.ledger=SQLiteCapacityLedger(db_path)
        with closing(self.ledger._connect()) as c:
            c.execute('CREATE TABLE IF NOT EXISTS delivery_outbox (permit_id TEXT PRIMARY KEY,permit_hash TEXT NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,permit_json TEXT NOT NULL,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL,state TEXT NOT NULL,receipt_json TEXT,ack_json TEXT,armed_at TEXT NOT NULL)')

    def seed(self,fixture):
        self.ledger.register_policy(PolicyManifest.from_dict(fixture['policy']))
        c=self.ledger._connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            assert c.execute('SELECT count(*) FROM issued_permits').fetchone()[0]==0
            for table in ['capacity_state','reservations','issued_permits']:
                for row in fixture[table]:
                    cols=list(row);c.execute(f'INSERT INTO {table} ({",".join(cols)}) VALUES ({",".join("?" for _ in cols)})',[row[k] for k in cols])
            c.commit()
        except: c.rollback();raise
        finally:c.close()

    def get_job(self,permit_id):
        c=self.ledger._connect()
        try:
            row=c.execute('SELECT * FROM delivery_outbox WHERE permit_id=?',(permit_id,)).fetchone()
            return dict(row) if row else None
        finally:c.close()

    def arm(self,permit,at):
        p=DecisionPermit.from_dict(permit);now=normalize_timestamp(at)
        if canonical_json(permit)!=canonical_json(p.to_dict()):raise ValueError('noncanonical permit input')
        c=self.ledger._connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            self.ledger._assert_issued_permit_conn(c,p)
            old=c.execute('SELECT * FROM delivery_outbox WHERE permit_id=?',(p.permit_id,)).fetchone()
            if old:
                if old['permit_hash']!=p.content_hash:raise ValueError('intent content conflict')
                c.commit();return dict(old)
            stored=c.execute('SELECT manifest_json FROM active_policies WHERE policy_id=?',(p.policy_id,)).fetchone()
            if not stored:raise ValueError('unknown policy')
            policy=PolicyManifest.from_dict(json.loads(stored['manifest_json']))
            self.ledger._assert_policy_usable_conn(c,policy,now)
            if (p.policy_hash,p.policy_revision)!=(policy.policy_hash,policy.revision):raise ValueError('policy mismatch')
            if not parse_timestamp(p.issued_at)<=parse_timestamp(now)<parse_timestamp(p.expires_at):raise ValueError('invalid permit time')
            if p.route not in ('alert','review') or p.route not in policy.allowed_routes:raise ValueError('not an allowed action')
            if c.execute('SELECT 1 FROM executions WHERE permit_id=?',(p.permit_id,)).fetchone():raise ValueError('permit already consumed')
            r=c.execute('SELECT * FROM reservations WHERE reservation_id=?',(p.reservation_id,)).fetchone()
            if r is None or r['status']!='reserved':raise ValueError('reservation not held')
            for key,value in {'permit_id':p.permit_id,'permit_hash':p.content_hash,'request_hash':p.request_hash,'policy_hash':p.policy_hash,'resource':p.route}.items():
                if r[key]!=value:raise ValueError('reservation binding mismatch '+key)
            state=c.execute('SELECT * FROM capacity_state WHERE policy_id=? AND policy_revision=? AND scope_key=? AND resource=?',(r['policy_id'],r['policy_revision'],r['scope_key'],r['resource'])).fetchone()
            if state is None or not 0<state['reserved'] or state['reserved']+state['committed']>state['capacity_limit']:raise ValueError('invalid capacity state')
            canonical_permit=p.to_dict()
            payload={k:canonical_permit[k] for k in ['decision_id','route','permitted_claim_ids','used_evidence_ids']}
            c.execute('INSERT INTO delivery_outbox VALUES (?,?,?,?,?,?,?,NULL,NULL,?)',(p.permit_id,p.content_hash,p.permit_id,canonical_json(p),canonical_json(payload),canonical_hash(payload),'armed',now))
            row=dict(c.execute('SELECT * FROM delivery_outbox WHERE permit_id=?',(p.permit_id,)).fetchone());c.commit();return row
        except:c.rollback();raise
        finally:c.close()

    def finish(self,permit_id,ack,at,before_commit=None):
        now=normalize_timestamp(at);c=self.ledger._connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            job=c.execute('SELECT * FROM delivery_outbox WHERE permit_id=?',(permit_id,)).fetchone()
            if job is None:raise ValueError('no durable authorization')
            if ack.get('idempotency_key')!=job['idempotency_key'] or ack.get('payload_hash')!=job['payload_hash'] or type(ack.get('effect_id')) is not int or ack['effect_id']<1:raise ValueError('ack binding mismatch')
            if not isinstance(ack.get('payload'),dict) or canonical_hash(ack['payload'])!=job['payload_hash']:raise ValueError('ack payload mismatch')
            if job['state']=='receipted':
                old=json.loads(job['ack_json'])
                if old['effect_id']!=ack['effect_id']:raise ValueError('effect identity conflict')
                receipt=json.loads(job['receipt_json']);c.commit();return receipt
            p=DecisionPermit.from_dict(json.loads(job['permit_json']))
            self.ledger._assert_issued_permit_conn(c,p)
            # No fresh policy grant here: completion reconciles the already armed intent.
            self.ledger._commit_reservation_conn(c,p.reservation_id,permit_id=p.permit_id,permit_hash=p.content_hash,at=now)
            tail=c.execute('SELECT sequence_no,receipt_hash FROM receipt_log ORDER BY sequence_no DESC LIMIT 1').fetchone()
            seq=1 if tail is None else tail['sequence_no']+1
            effect_time=normalize_timestamp(ack['committed_at'])
            receipt=ExecutionReceipt(receipt_id=stable_id('receipt',{'permit_id':p.permit_id,'effect_id':ack['effect_id']}),sequence_no=seq,permit_id=p.permit_id,permit_hash=p.content_hash,policy_id=p.policy_id,policy_revision=p.policy_revision,route=p.route,execution_status='executed',side_effect_id=str(ack['effect_id']),reservation_id=p.reservation_id,executed_at=effect_time,enforcement_point_id='ecrc_http_delivery_adapter',previous_receipt_hash=GENESIS_RECEIPT_HASH if tail is None else tail['receipt_hash'])
            c.execute('INSERT INTO receipt_log VALUES (?,?,?,?,?,?)',(seq,receipt.receipt_id,p.permit_id,receipt.previous_receipt_hash,receipt.content_hash,canonical_json(receipt)))
            c.execute('INSERT INTO executions VALUES (?,?,?,?,?)',(p.permit_id,p.content_hash,'executed',receipt.receipt_id,now))
            delivery_receipt={**receipt.to_dict(),'authorized_at':job['armed_at'],'service_effect_id':ack['effect_id'],'service_committed_at':effect_time,'reconciled_at':utc_now(),'reconciliation_policy_clock':now,'delivery_schema_version':1}
            c.execute("UPDATE delivery_outbox SET state='receipted',receipt_json=?,ack_json=? WHERE permit_id=?",(canonical_json(delivery_receipt),canonical_json(ack),p.permit_id))
            if before_commit:before_commit()
            c.commit();return delivery_receipt
        except:c.rollback();raise
        finally:c.close()

    def revoke(self):
        with closing(self.ledger._connect()) as c:
            c.execute('UPDATE active_policies SET revoked=1');c.commit()

    def snapshot(self):
        c=self.ledger._connect()
        try:
            cap=[dict(r) for r in c.execute('SELECT * FROM capacity_state')]
            jobs=[dict(r) for r in c.execute('SELECT * FROM delivery_outbox ORDER BY permit_id')]
            return {'n_receipts':c.execute('SELECT count(*) FROM receipt_log').fetchone()[0],'n_armed':sum(r['state']=='armed' for r in jobs),'n_receipted':sum(r['state']=='receipted' for r in jobs),'n_jobs':len(jobs),'reserved':sum(r['reserved'] for r in cap),'committed':sum(r['committed'] for r in cap),'capacity_limit':sum(r['capacity_limit'] for r in cap),'capacity_rows':cap,'jobs':jobs}
        finally:c.close()
