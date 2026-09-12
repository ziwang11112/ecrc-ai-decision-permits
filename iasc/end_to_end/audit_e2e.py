"""Independent stdlib audit of authoritative SQLite state and raw requests.

No adapter or issuer imports. Capacity-denied outcomes are checked as possible
ordered routes, not inferred retrospectively from final counters. Exact phase
inventory is optional in audit() and mandatory in final CLI checks.
"""
import argparse, hashlib, json, sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canon(value).encode('utf-8')).hexdigest()


def time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None: raise ValueError('timezone missing')
    return result


def read_db(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: [dict(r) for r in db.execute('SELECT * FROM "' + name.replace('"', '""') + '"')] for name in names}
    finally: db.close()


def scope(policy, proposal):
    if policy['capacity_scope'] == 'subject': return proposal['subject_id']
    if policy['capacity_scope'] == 'session': return proposal['session_id']
    if policy['capacity_scope'] in ('subject_session', 'participant_segment'):
        return proposal['subject_id'] + '::' + proposal['session_id']
    raise ValueError('unsupported scope')


def binding(raw):
    return digest(dict(policy_hash=digest(raw['policy']), proposal_hash=digest(raw['proposal']),
                       evidence_hash=digest(raw['evidence']), scope_key=scope(raw['policy'], raw['proposal'])))


def membership(raw):
    policy, proposal, envelope = (raw[k] for k in ('policy', 'proposal', 'evidence'))
    rules = {r['evidence_type']: r for r in policy['evidence_rules']}
    admitted, used, excluded, types = [], [], [], set()
    for item in envelope['items']:
        rule = rules.get(item['evidence_type'])
        age = (time(proposal['proposed_at']) - time(item['observed_at'])).total_seconds()
        good = bool(rule and item['source'] in rule['allowed_sources'] and item['schema_version'] in rule['allowed_schema_versions'] and
                    time(item['observed_at']) <= time(item['available_at']) <= time(proposal['proposed_at']) and 0 <= age <= rule['max_age_seconds'])
        (admitted if good else excluded).append(item['evidence_id'])
        if good and rule['use_allowed'] and item['requested_for_use']:
            used.append(item['evidence_id']); types.add(item['evidence_type'])
    return sorted(admitted), sorted(used), sorted(excluded), types


def claims(policy, route, reason, types):
    return sorted(r['claim_id'] for r in policy['claim_rules'] if route in r['routes'] and
                  (not r['reason_codes'] or reason in r['reason_codes']) and set(r['required_evidence_types']) <= types)


def possible_outcomes(raw, used, types):
    p, x = raw['policy'], raw['proposal']
    if not used: initial = [('abstain', 'no_policy_admitted_evidence_for_use', None)]
    elif x['uncertainty'] >= p['uncertainty_threshold']: initial = [('abstain', 'uncertainty_gate', None)]
    elif abs(x['score'] - p['score_threshold']) <= p['review_band_width']:
        initial = [('review', 'score_within_review_band', 'review'), ('abstain', 'review_capacity_exhausted', None)]
    elif x['score'] > p['score_threshold'] + p['review_band_width']:
        initial = [('alert', 'score_above_review_band', 'alert'), ('no_action', 'alert_capacity_exhausted', None)]
    else: initial = [('no_action', 'score_below_threshold', None)]
    result = []
    for route, reason, resource in initial:
        if route not in p['allowed_routes']:
            if 'no_action' not in p['allowed_routes']: continue
            route, reason = 'no_action', 'route_not_authorized_by_policy'
        if route in ('alert', 'review') and not claims(p, route, reason, types):
            if 'abstain' in p['allowed_routes']: route = 'abstain'
            elif 'no_action' in p['allowed_routes']: route = 'no_action'
            else: continue
            reason = 'no_claim_supported_by_used_evidence'
        result.append((route, reason, resource))
    return result


def audit(client, sink, arm, input_file, expected_decisions=None):
    failures, checks, summary = [], 0, {}
    def check(ok, message):
        nonlocal checks
        checks += 1
        if not ok: failures.append(message)
    def equal_fields(left, right, fields):
        return all(left[k] == right[k] for k in fields)
    try:
        if arm not in ('ecrc', 'ordinary'): raise ValueError('unknown arm')
        c, s = read_db(client), read_db(sink)
        with open(input_file, encoding='utf-8') as stream: supplied = json.load(stream)['requests']
        original = {r['proposal']['decision_id']: r for r in supplied}
        check(len(original) == len(supplied), 'unique-original-decision-ids')
        requests = c['requests']; request_rows = {r['decision_id']: r for r in requests}
        check(len(request_rows) == len(requests), 'unique-request-ids')
        check(set(request_rows) <= set(original), 'request-inventory-is-input-subset')
        if expected_decisions is not None:
            check(len(expected_decisions) == len(set(expected_decisions)), 'unique-expected-decision-ids')
            check(set(request_rows) == set(expected_decisions), 'exact-checkpoint-request-inventory')
        permits = {r['decision_id']: json.loads(r['permit_json']) for r in requests if r['permit_json'] is not None}
        by_permit = {p['permit_id']: p for p in permits.values()}
        check(len(by_permit) == len(permits), 'unique-permit-identities')
        jobs = c['delivery_outbox' if arm == 'ecrc' else 'delivery']
        job_by_key = {j['idempotency_key']: j for j in jobs}; job_by_permit = {j['permit_id']: j for j in jobs}
        check(len(job_by_key) == len(jobs) == len(job_by_permit), 'unique-job-keys-and-permits')
        effects = s['effects']; effect_by_key = {e['idempotency_key']: e for e in effects}
        check(len(effects) == len(effect_by_key), 'unique-sink-keys')
        check(len({e['effect_id'] for e in effects}) == len(effects), 'unique-sink-effect-ids')
        policies = {digest(raw['policy']): raw['policy'] for raw in supplied}
        check(len(policies) == 1, 'fixed-single-policy-input'); policy = next(iter(policies.values()))
        check(policy['alert_capacity'] == 2 and policy['review_capacity'] == 1, 'fixed-protocol-two-one-budgets')
        check(len({scope(r['policy'], r['proposal']) for r in supplied}) == 1, 'fixed-single-input-scope')
        trusted = c['active_policies' if arm == 'ecrc' else 'policy']; check(len(trusted) == 1, 'one-trusted-policy-row')
        for row in trusted:
            check(canon(json.loads(row['manifest_json' if arm == 'ecrc' else 'document'])) == canon(policy), 'trusted-policy-equals-raw-policy')
            check(row['policy_id' if arm == 'ecrc' else 'id'] == policy['policy_id'] and row['revision'] == policy['revision'] and
                  row['policy_hash' if arm == 'ecrc' else 'digest'] == digest(policy), 'trusted-policy-binding')
            check(row['revoked'] in (0, 1), 'trusted-revocation-state')
            if arm == 'ecrc':
                check(time(row['effective_from']) == time(policy['effective_from']) and time(row['expires_at']) == time(policy['expires_at']), 'trusted-policy-time-columns')
        if arm == 'ecrc':
            holds, budgets, registrations, authority = c['reservations'], c['capacity_state'], c['issued_permits'], c['receipt_log']
        else:
            holds, registrations = [], []
            for row in c['holds']:
                hold = json.loads(row['document'])
                check(row['id'] == hold['reservation_id'] and row['status'] == hold['status'], 'hold-column-document-binding'); holds.append(hold)
            budgets = [{**r, 'capacity_limit': r['ceiling'], 'reserved': r['held'], 'committed': r['spent']} for r in c['budgets']]
            for row in c['permit_registry']:
                doc, reg = json.loads(row['document']), json.loads(row['registration'])
                check(row['id'] == doc['permit_id'] == reg['permit_id'] and row['digest'] == digest(doc) == reg['permit_hash'], 'registry-column-document-binding')
                check(by_permit.get(row['id']) == doc, 'registry-full-permit-equals-journal'); registrations.append(reg)
            authority = c['receipts']
        registry = {r['permit_id']: r for r in registrations}
        check(len(registry) == len(registrations) and set(registry) == set(by_permit), 'exact-registry-permit-inventory')
        for permit_id, reg in registry.items():
            p = by_permit.get(permit_id)
            if p is None: continue
            check(reg['permit_hash'] == digest(p), 'registered-content-' + permit_id)
            check(equal_fields(reg, p, ('decision_id', 'policy_id', 'policy_revision', 'policy_hash', 'request_hash', 'reservation_id', 'route', 'reason_code', 'issued_at')), 'registered-all-bindings-' + permit_id)
        bound_raw, outcomes_by_decision = {}, {}
        for decision, raw in original.items(): bound_raw.setdefault(binding(raw), []).append((decision, raw))
        for row in requests:
            decision = row['decision_id']; raw = json.loads(row['request_json'])
            check(canon(raw) == canon(original.get(decision)), 'raw-input-' + decision); check(row['request_hash'] == digest(raw), 'raw-hash-' + decision)
            check(raw['proposal']['decision_id'] == raw['evidence']['decision_id'] == decision, 'raw-decision-binding-' + decision)
            check(row['state'] in ('received', 'issued', 'nonaction', 'cancelled'), 'request-state-' + decision)
            check((row['cancelled_at'] is not None) == (row['state'] == 'cancelled'), 'request-cancel-time-presence-' + decision)
            if row['permit_json'] is None:
                check(row['state'] in ('received', 'cancelled'), 'missing-permit-state-' + decision)
                if row['state'] == 'cancelled': check(time(row['cancelled_at']) >= time(row['received_at']) + timedelta(seconds=60), 'raw-cleanup-lease-' + decision)
                continue
            p = permits[decision]; pol, proposal, env = (raw[k] for k in ('policy', 'proposal', 'evidence'))
            check(p['decision_id'] == decision, 'permit-decision-binding-' + decision)
            check(p['policy_id'] == pol['policy_id'] and p['policy_revision'] == pol['revision'], 'permit-policy-identity-' + decision)
            check(p['policy_hash'] == digest(pol) and p['proposal_hash'] == digest(proposal) and p['evidence_hash'] == digest(env) and p['request_hash'] == binding(raw), 'all-input-bindings-' + decision)
            check(any(m['model_id'] == proposal['model_id'] and m['model_hash'] == proposal['model_hash'] for m in pol['approved_models']), 'approved-model-pair-' + decision)
            check(time(row['received_at']) <= time(p['issued_at']) and time(proposal['proposed_at']) <= time(p['issued_at']) and time(env['created_at']) <= time(p['issued_at']), 'issuance-input-time-order-' + decision)
            check(time(pol['effective_from']) <= time(p['issued_at']) < time(pol['expires_at']) and time(p['expires_at']) == min(time(p['issued_at']) + timedelta(seconds=3600), time(pol['expires_at'])), 'permit-policy-interval-and-ttl-' + decision)
            admitted, used, excluded, types = membership(raw)
            check(p['admitted_evidence_ids'] == admitted and p['used_evidence_ids'] == used and p['excluded_evidence_ids'] == excluded, 'evidence-membership-' + decision)
            matching = [o for o in possible_outcomes(raw, used, types) if o[:2] == (p['route'], p['reason_code'])]
            outcomes_by_decision[decision] = matching; check(bool(matching), 'score-uncertainty-ordered-route-reason-' + decision)
            allowed_claims = claims(pol, p['route'], p['reason_code'], types)
            check(p['permitted_claim_ids'] == allowed_claims, 'claim-closure-' + decision)
            check(p['blocked_claim_ids'] == sorted(set(pol['blocked_claim_ids']) | ({r['claim_id'] for r in pol['claim_rules']} - set(allowed_claims))), 'blocked-claim-closure-' + decision)
            check(p['route'] in pol['allowed_routes'], 'route-allowed-' + decision)
            if p['route'] in ('alert', 'review'):
                check(bool(used) and bool(allowed_claims) and p['reserved_resource'] == p['route'] and p['reservation_id'] is not None, 'action-support-reservation-' + decision)
                check(type(p['pre_state_revision']) is int and p['pre_state_revision'] >= 0 and p['post_state_revision'] == p['pre_state_revision'] + 1, 'action-state-transition-' + decision)
                check(row['state'] in ('issued', 'cancelled'), 'action-journal-state-' + decision)
            else:
                check(p['reservation_id'] is None and p['reserved_resource'] is None and p['pre_state_revision'] == p['post_state_revision'] == 0 and row['state'] == 'nonaction', 'nonaction-reservation-state-' + decision)
            if row['state'] == 'cancelled': check(time(row['cancelled_at']) >= time(p['expires_at']), 'issued-cleanup-expiry-' + decision)
            if row['state'] == 'cancelled' or p['route'] not in ('alert', 'review'):
                check(p['permit_id'] not in job_by_permit and p['permit_id'] not in effect_by_key, 'no-dispatch-' + decision)
        keys = ('policy_id', 'policy_revision', 'scope_key', 'resource')
        budget_by_key = {tuple(b[k] for k in keys): b for b in budgets}; check(len(budget_by_key) == len(budgets), 'unique-budget-keys')
        check(len({h['reservation_id'] for h in holds}) == len(holds), 'unique-hold-identities')
        holds_by_decision = {}; expected_scope = scope(policy, supplied[0]['proposal'])
        for b in budgets:
            key = tuple(b[k] for k in keys)
            check(key[:3] == (policy['policy_id'], policy['revision'], expected_scope) and b['resource'] in ('alert', 'review'), 'budget-policy-scope-resource')
            check(b['capacity_limit'] == policy.get(b['resource'] + '_capacity'), 'budget-ceiling-from-raw-policy')
            check(all(type(b[k]) is int and b[k] >= 0 for k in ('reserved', 'committed', 'capacity_limit', 'state_revision')) and b['reserved'] + b['committed'] <= b['capacity_limit'], 'capacity-bound-' + str(key))
            same = [h for h in holds if tuple(h[k] for k in keys) == key]
            check(b['reserved'] == sum(h['amount'] for h in same if h['status'] == 'reserved'), 'held-reconstruction')
            check(b['committed'] == sum(h['amount'] for h in same if h['status'] == 'committed'), 'spent-reconstruction')
            check(b['state_revision'] == sum(1 + (h['status'] in ('committed', 'released')) for h in same), 'budget-revision-reconstruction')
        for hold in holds:
            label = hold['reservation_id']; key = tuple(hold[k] for k in keys)
            check(key in budget_by_key, 'every-hold-has-budget-' + label)
            check(type(hold['amount']) is int and hold['amount'] == 1, 'unit-hold-amount-' + label)
            check(hold['status'] in ('reserved', 'committed', 'released'), 'hold-status-' + label)
            matches = bound_raw.get(hold['request_hash'], []); check(len(matches) == 1, 'hold-unique-raw-request-' + label)
            if len(matches) != 1: continue
            decision, raw = matches[0]; holds_by_decision.setdefault(decision, []).append(hold); pol = raw['policy']
            check(decision in request_rows and decision in permits, 'hold-has-durable-issued-request-' + label)
            check(hold['policy_id'] == pol['policy_id'] and hold['policy_revision'] == pol['revision'] and hold['policy_hash'] == digest(pol) and hold['scope_key'] == scope(pol, raw['proposal']), 'hold-policy-scope-binding-' + label)
            check(type(hold['pre_state_revision']) is int and hold['pre_state_revision'] >= 0 and hold['post_state_revision'] == hold['pre_state_revision'] + 1 and key in budget_by_key and hold['post_state_revision'] <= budget_by_key[key]['state_revision'], 'hold-state-transition-' + label)
            check(time(hold['created_at']) <= time(hold['lease_expires_at']), 'hold-lease-time-order-' + label)
            p = permits.get(decision)
            if p is None: continue
            check(time(hold['created_at']) == time(p['issued_at']), 'hold-issuance-time-' + label)
            if hold['permit_id'] is None:
                check(hold['permit_hash'] is None and hold['status'] == 'released' and p['route'] not in ('alert', 'review') and p['reason_code'] in ('no_claim_supported_by_used_evidence', 'route_not_authorized_by_policy'), 'released-provisional-hold-' + label)
            else:
                check(hold['permit_id'] == p['permit_id'] and hold['permit_hash'] == digest(p) and hold['reservation_id'] == p['reservation_id'] and hold['resource'] == p['route'] and hold['pre_state_revision'] == p['pre_state_revision'] and hold['post_state_revision'] == p['post_state_revision'], 'hold-full-permit-binding-' + label)
                row, job = request_rows.get(decision), job_by_permit.get(p['permit_id'])
                status = 'released' if row and row['state'] == 'cancelled' else 'committed' if job and job['state'] == 'receipted' else 'reserved'
                check(hold['status'] == status, 'hold-lifecycle-state-' + label)
        for decision, matching in outcomes_by_decision.items():
            actual = holds_by_decision.get(decision, [])
            check(any((len(actual) == 0 if resource is None else len(actual) == 1 and actual[0]['resource'] == resource) for _, _, resource in matching), 'ordered-outcome-provisional-hold-' + decision)
        decisions = []
        for effect in effects:
            key = effect['idempotency_key']; p, job = by_permit.get(key), job_by_key.get(key)
            check(type(effect['effect_id']) is int and effect['effect_id'] > 0, 'positive-sink-effect-id')
            check(p is not None and job is not None, 'effect-has-issued-intent-' + key)
            payload = json.loads(effect['payload_json']); check(digest(payload) == effect['payload_hash'], 'sink-payload-hash-' + key); time(effect['committed_at'])
            if p:
                expected = {k: p[k] for k in ('decision_id', 'route', 'permitted_claim_ids', 'used_evidence_ids')}
                check(payload == expected and p['route'] in ('alert', 'review'), 'sink-payload-' + key); decisions.append(p['decision_id'])
            if job: check(job['payload_hash'] == effect['payload_hash'] and json.loads(job['payload_json']) == payload, 'effect-intent-payload-' + key)
        check(len(decisions) == len(set(decisions)), 'unique-business-decisions-in-this-policy-revision')
        receipt_by_permit = {}; previous_hash = '0' * 64
        for sequence, row in enumerate(sorted(authority, key=lambda r: r['sequence_no']) if arm == 'ecrc' else authority, 1):
            doc = json.loads(row['receipt_json' if arm == 'ecrc' else 'document'])
            check(row['permit_id'] == doc['permit_id'] and row['receipt_id'] == doc['receipt_id'], 'authoritative-receipt-column-document')
            check(doc['permit_id'] not in receipt_by_permit, 'one-authoritative-receipt-per-permit'); receipt_by_permit[doc['permit_id']] = doc
            if arm == 'ecrc':
                check(row['sequence_no'] == doc['sequence_no'] == sequence and row['previous_receipt_hash'] == doc['previous_receipt_hash'] == previous_hash and row['receipt_hash'] == digest(doc), 'authoritative-ecrc-receipt-chain')
                previous_hash = digest(doc)
            else: check(row['effect_id'] == doc['service_effect_id'], 'ordinary-receipt-effect-column')
        check(len({r['receipt_id'] for r in receipt_by_permit.values()}) == len(receipt_by_permit), 'unique-authoritative-receipt-ids')
        receipted_ids = {j['permit_id'] for j in jobs if j['state'] == 'receipted'}
        check(set(receipt_by_permit) == receipted_ids, 'exact-authoritative-receipt-inventory')
        for job in jobs:
            permit_id = job['permit_id']; p = by_permit.get(permit_id)
            check(p is not None and job['permit_hash'] == digest(p) and job['idempotency_key'] == permit_id, 'intent-permit-key-hash')
            if p is None: continue
            pol = original[p['decision_id']]['policy']; expected = {k: p[k] for k in ('decision_id', 'route', 'permitted_claim_ids', 'used_evidence_ids')}
            check(json.loads(job['payload_json']) == expected and job['payload_hash'] == digest(expected), 'intent-payload-before-or-after-effect')
            check(p['route'] in ('alert', 'review') and time(p['issued_at']) <= time(job['armed_at']) < time(p['expires_at']) and time(pol['effective_from']) <= time(job['armed_at']) < time(pol['expires_at']), 'intent-authorization-policy-clock')
            if arm == 'ecrc': check(json.loads(job['permit_json']) == p, 'outbox-full-permit-document')
            matching = [h for h in holds if h['permit_id'] == permit_id]
            check(len(matching) == 1 and matching[0]['reservation_id'] == p['reservation_id'], 'intent-single-reservation')
            if job['state'] == 'armed':
                check(job['receipt_json'] is None and job['ack_json'] is None and all(h['status'] == 'reserved' for h in matching), 'unknown-retains-capacity'); continue
            check(job['state'] == 'receipted', 'known-job-state')
            if job['state'] != 'receipted': continue
            effect = effect_by_key.get(job['idempotency_key']); check(effect is not None, 'receipt-real-effect')
            receipt, ack = json.loads(job['receipt_json']), json.loads(job['ack_json'])
            check(ack['idempotency_key'] == job['idempotency_key'] and ack['payload'] == expected and ack['payload_hash'] == digest(ack['payload']) == job['payload_hash'], 'ack-entire-payload-key-binding')
            check(type(ack['effect_id']) is int and ack['effect_id'] > 0, 'ack-positive-effect-id')
            check(equal_fields(receipt, p, ('permit_id', 'route', 'reservation_id')) and receipt['permit_hash'] == digest(p) and receipt['execution_status'] == 'executed', 'receipt-permit-reservation-binding')
            authoritative = receipt_by_permit.get(permit_id); check(authoritative is not None, 'outbox-has-authoritative-receipt')
            if arm == 'ecrc':
                check(authoritative is not None and all(receipt.get(k) == v for k, v in authoritative.items()), 'ecrc-base-receipt-equals-outbox')
                check(receipt['policy_id'] == p['policy_id'] and receipt['policy_revision'] == p['policy_revision'] and receipt['failure_reason'] is None and receipt['enforcement_point_id'] == 'ecrc_http_delivery_adapter' and receipt['delivery_schema_version'] == 1 and time(receipt['authorized_at']) == time(job['armed_at']), 'ecrc-receipt-policy-extension')
            else:
                check(authoritative == receipt, 'ordinary-authoritative-receipt-equals-outbox')
                check(receipt['service_ack'] == ack and receipt['effect_id'] == receipt['service_effect_id'] and receipt['idempotency_key'] == job['idempotency_key'] and receipt['payload_hash'] == job['payload_hash'] and time(receipt['armed_at']) == time(job['armed_at']), 'ordinary-receipt-ack-extension')
            if effect:
                check(ack['effect_id'] == receipt['service_effect_id'] == effect['effect_id'] and receipt['side_effect_id'] == str(effect['effect_id']), 'receipt-effect-identity')
                check(ack['payload_hash'] == effect['payload_hash'] == job['payload_hash'], 'receipt-effect-hash')
                check(time(receipt['executed_at']) == time(effect['committed_at']) == time(ack['committed_at']) and time(receipt['service_committed_at' if arm == 'ecrc' else 'committed_at']) == time(effect['committed_at']), 'receipt-service-time')
                check(time(receipt['reconciled_at']) >= time(effect['committed_at']), 'actual-reconciliation-order')
            check(time(receipt['reconciliation_policy_clock']) >= time(job['armed_at']), 'reconciliation-policy-clock-order')
            check(all(h['status'] == 'committed' for h in matching), 'receipt-commits-reservation')
        if arm == 'ecrc':
            executions = c['executions']
            check(len(executions) == len(receipted_ids) and {r['permit_id'] for r in executions} == receipted_ids, 'exact-execution-inventory')
            for row in executions:
                p, receipt, job = by_permit.get(row['permit_id']), receipt_by_permit.get(row['permit_id']), job_by_permit.get(row['permit_id'])
                check(p is not None and receipt is not None and job is not None and row['permit_hash'] == digest(p) and row['receipt_id'] == receipt['receipt_id'] and row['execution_status'] == 'executed', 'execution-permit-authoritative-receipt-link')
                if job and job['receipt_json']: check(time(row['created_at']) == time(json.loads(job['receipt_json'])['reconciliation_policy_clock']), 'execution-policy-clock')
        summary = dict(requests=len(requests), permits=len(permits), effects=len(effects), receipts=len(authority),
                       reserved=sum(b['reserved'] for b in budgets), committed=sum(b['committed'] for b in budgets),
                       released=sum(h['status'] == 'released' for h in holds), cancelled=sum(r['state'] == 'cancelled' for r in requests),
                       armed=sum(j['state'] == 'armed' for j in jobs), effect_decisions=sorted(decisions),
                       effect_routes={route: sum(json.loads(e['payload_json'])['route'] == route for e in effects) for route in ('alert', 'review')},
                       states={r['decision_id']: r['state'] for r in requests})
    except (KeyError, TypeError, ValueError, IndexError, sqlite3.Error, OSError) as exc:
        check(False, 'audit-structural-error: ' + type(exc).__name__ + ': ' + str(exc))
    return dict(passed=not failures, checks=checks, findings=failures, **summary)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', type=Path, required=True); args = parser.parse_args()
    rows, snapshots = [], []
    for folder in sorted(args.out.glob('*/*/*')):
        if not (folder / 'client.sqlite').exists(): continue
        metadata = json.loads((folder / 'case.json').read_text('utf-8'))
        expected = [r['proposal']['decision_id'] for r in json.loads((folder / 'input.json').read_text('utf-8'))['requests']]
        result = audit(folder / 'client.sqlite', folder / 'sink.sqlite', metadata['arm'], folder / 'input.json', expected_decisions=expected)
        result.update(case=str(folder.relative_to(args.out)), arm=metadata['arm']); rows.append(result)
        for snap in sorted((folder / 'snapshots').glob('*')):
            meta_file = snap / 'snapshot_meta.json'
            if meta_file.exists():
                meta = json.loads(meta_file.read_text('utf-8')); expected_snap = meta['expected_decisions']; provenance = 'snapshot_meta'
            elif (snap / 'audit.json').exists():
                old = json.loads((snap / 'audit.json').read_text('utf-8')); expected_snap = list(old['states']); provenance = 'legacy_development_audit_states'
            else:
                snapshots.append(dict(case=str(snap.relative_to(args.out)), passed=False, checks=1, findings=['missing-snapshot-metadata'])); continue
            result = audit(snap / 'client.sqlite', snap / 'sink.sqlite', metadata['arm'], folder / 'input.json', expected_decisions=expected_snap)
            result.update(case=str(snap.relative_to(args.out)), arm=metadata['arm'], inventory_source=provenance); snapshots.append(result)
    result = dict(passed=bool(rows) and all(r['passed'] for r in rows + snapshots), cases=len(rows), snapshots=len(snapshots),
                  checks=sum(r['checks'] for r in rows + snapshots), results=rows, snapshot_results=snapshots)
    (args.out / 'INDEPENDENT_AUDIT.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('results', 'snapshot_results')}))


if __name__ == '__main__': main()
