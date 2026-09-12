"""Independent corruption QA on cloned development SQLite databases only."""
import hashlib
import json
import sqlite3
from pathlib import Path

from audit_e2e import audit, canon, digest

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'dev_smoke_01/distinct_contenders/rep-0/ecrc'
OUT = HERE / 'audit_corruption_qa'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clone(source, target):
    origin = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)
    copied = sqlite3.connect(target)
    try:
        origin.backup(copied)
    finally:
        copied.close(); origin.close()


def corrupt_receipt(db):
    row = db.execute('SELECT * FROM receipt_log ORDER BY sequence_no DESC LIMIT 1').fetchone()
    receipt = json.loads(row['receipt_json']); receipt['side_effect_id'] = '999'
    # Preserve the authority row's own hash: comparison to the outbox is still required.
    db.execute('UPDATE receipt_log SET receipt_json=?,receipt_hash=? WHERE sequence_no=?',
               (canon(receipt), digest(receipt), row['sequence_no']))


def orphan_hold(db):
    row = dict(db.execute('SELECT * FROM reservations LIMIT 1').fetchone())
    row.update(reservation_id='corrupt-orphan-hold', idempotency_key='corrupt-orphan-key',
               scope_key='orphan-scope', status='released', permit_id=None, permit_hash=None)
    columns = list(row)
    db.execute('INSERT INTO reservations (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')',
               [row[k] for k in columns])


def wrong_ordered_route(db):
    row = db.execute("SELECT * FROM requests WHERE state='nonaction' LIMIT 1").fetchone()
    permit = json.loads(row['permit_json'])
    permit.update(route='review', reason_code='score_within_review_band', permitted_claim_ids=['review_request'],
                  blocked_claim_ids=['clinical_benefit', 'notify'])
    db.execute('UPDATE requests SET permit_json=? WHERE decision_id=?', (canon(permit), row['decision_id']))


def unacknowledged_bad_payload(db):
    last = db.execute('SELECT * FROM receipt_log ORDER BY sequence_no DESC LIMIT 1').fetchone()
    permit_id = last['permit_id']
    job = db.execute('SELECT * FROM delivery_outbox WHERE permit_id=?', (permit_id,)).fetchone()
    payload = json.loads(job['payload_json']); payload['permitted_claim_ids'] = ['wrong-claim']
    db.execute('DELETE FROM receipt_log WHERE permit_id=?', (permit_id,))
    db.execute('DELETE FROM executions WHERE permit_id=?', (permit_id,))
    db.execute("UPDATE reservations SET status='reserved' WHERE permit_id=?", (permit_id,))
    db.execute('UPDATE capacity_state SET committed=committed-1,reserved=reserved+1,state_revision=state_revision-1')
    db.execute("UPDATE delivery_outbox SET state='armed',receipt_json=NULL,ack_json=NULL,payload_json=?,payload_hash=? WHERE permit_id=?",
               (canon(payload), digest(payload), permit_id))
    return permit_id


def expired_arm(db):
    row = db.execute('SELECT * FROM delivery_outbox LIMIT 1').fetchone()
    permit = json.loads(row['permit_json'])
    db.execute('UPDATE delivery_outbox SET armed_at=? WHERE permit_id=?', (permit['expires_at'], row['permit_id']))


def main():
    if OUT.exists():
        raise FileExistsError('Use a fresh QA directory; existing evidence is retained: ' + str(OUT))
    OUT.mkdir()
    original_files = [p for p in SOURCE.iterdir() if p.name in ('client.sqlite', 'client.sqlite-wal', 'sink.sqlite', 'sink.sqlite-wal')]
    before = {p.name: sha(p) for p in original_files}
    inputs = json.loads((SOURCE / 'input.json').read_text('utf-8'))
    expected = [r['proposal']['decision_id'] for r in inputs['requests']]
    cases = [
        ('unaltered_control', None, None),
        ('authoritative_receipt_changed', corrupt_receipt, 'ecrc-base-receipt-equals-outbox'),
        ('inflated_budget_ceiling', lambda d: d.execute('UPDATE capacity_state SET capacity_limit=99'), 'budget-ceiling-from-raw-policy'),
        ('orphan_released_hold', orphan_hold, 'every-hold-has-budget-'),
        ('wrong_hold_request_hash', lambda d: d.execute("UPDATE reservations SET request_hash=? WHERE reservation_id=(SELECT reservation_id FROM reservations LIMIT 1)", ('b' * 64,)), 'hold-unique-raw-request-'),
        ('wrong_execution_receipt_link', lambda d: d.execute("UPDATE executions SET receipt_id='nonexistent-receipt' WHERE permit_id=(SELECT permit_id FROM executions LIMIT 1)"), 'execution-permit-authoritative-receipt-link'),
        ('high_score_wrong_review_route', wrong_ordered_route, 'score-uncertainty-ordered-route-reason-'),
        ('unknown_intent_wrong_payload', unacknowledged_bad_payload, 'intent-payload-before-or-after-effect'),
        ('armed_at_exact_expiry', expired_arm, 'intent-authorization-policy-clock'),
        ('missing_final_received_request', lambda d: d.execute("DELETE FROM requests WHERE state='nonaction' AND decision_id=(SELECT decision_id FROM requests WHERE state='nonaction' LIMIT 1)"), 'exact-checkpoint-request-inventory'),
    ]
    rows = []
    for name, mutation, expected_finding in cases:
        folder = OUT / name; folder.mkdir()
        for file in ('client.sqlite', 'sink.sqlite'): clone(SOURCE / file, folder / file)
        (folder / 'input.json').write_text(json.dumps(inputs, indent=2) + '\n', encoding='utf-8')
        if mutation:
            db = sqlite3.connect(folder / 'client.sqlite'); db.row_factory = sqlite3.Row
            try:
                key = mutation(db); db.commit()
            finally: db.close()
            if name == 'unknown_intent_wrong_payload':
                db = sqlite3.connect(folder / 'sink.sqlite')
                try:
                    db.execute('DELETE FROM effects WHERE idempotency_key=?', (key,)); db.commit()
                finally: db.close()
        result = audit(folder / 'client.sqlite', folder / 'sink.sqlite', 'ecrc', folder / 'input.json', expected_decisions=expected)
        good = result['passed'] if mutation is None else not result['passed'] and any(f.startswith(expected_finding) for f in result['findings'])
        row = dict(case=name, qa_passed=good, expected_finding_prefix=expected_finding, audit=result)
        (folder / 'audit.json').write_text(json.dumps(row, indent=2) + '\n', encoding='utf-8'); rows.append(row)
    after = {p.name: sha(p) for p in original_files}
    report = dict(kind='development_corruption_QA_only', formal_denominator=False, source=str(SOURCE),
                  source_hashes_before=before, source_hashes_after=after, source_unchanged=before == after,
                  passed=before == after and all(r['qa_passed'] for r in rows), cases=len(rows), results=rows)
    (OUT / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('results', 'source_hashes_before', 'source_hashes_after')}))
    if not report['passed']: raise AssertionError('corruption QA failed; retain all clones and findings')


if __name__ == '__main__': main()
