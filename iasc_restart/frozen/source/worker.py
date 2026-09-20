"""One persistent client process; shared control messages contain no sink truth."""
import argparse
from http.client import HTTPException
import json
import os
import sys
import urllib.error
import urllib.request
from common import LIMIT, SCOPE, canonical, digest, jobs, load_core, load_direct, request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--url', required=True)
    args = parser.parse_args()
    records = {j['name']: j for j in jobs()}
    if args.arm == 'ecrc':
        backend = load_core()(args.db)
    elif args.arm == 'durable_count':
        from direct_adapter import DurableDirectCount
        backend = DurableDirectCount(args.db, SCOPE, LIMIT)
    else:
        backend = load_direct()(LIMIT if args.arm == 'volatile_count' else None)

    def issue(job, at):
        if args.arm != 'ecrc':
            return {'state': 'upstream_queued', 'counted': False}
        old = backend.get_request(job['decision_id'])
        if old is None:
            raw = request(job, at)
            from agentic_eeg_dm.governance import PolicyManifest
            backend.ledger.register_policy(PolicyManifest.from_dict(raw['policy']))
            backend.ingest(raw, at)
        return backend.issue(job['decision_id'], at)

    def prepare(job, at):
        if args.arm == 'ecrc':
            permit = issue(job, at)
            if permit is None or permit['route'] not in ('alert', 'review'):
                return None
            stored = backend.arm(permit, at)
            return {'idempotency_key': stored['idempotency_key'], 'payload': json.loads(stored['payload_json'])}
        if args.arm == 'durable_count':
            return backend.prepare(job)
        return backend.submit_descriptor(job)

    def post(job, descriptor, at):
        value = {'descriptor': descriptor}
        if descriptor is None:
            return {**value, 'status': 'not_admitted'}
        req = urllib.request.Request(args.url + '/effects', data=canonical(descriptor).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                ack = json.loads(response.read())
                value['http_code'] = response.status
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace')
            raise RuntimeError('service_http_error ' + str(exc.code) + ': ' + body) from exc
        except (OSError, HTTPException) as exc:
            return {**value, 'status': 'transport_unknown', 'error_type': type(exc).__name__}
        if (ack.get('idempotency_key') != descriptor['idempotency_key']
                or ack.get('payload_hash') != digest(descriptor['payload'])
                or ack.get('payload') != descriptor['payload']):
            raise ValueError('public response binding mismatch')
        if args.arm == 'ecrc':
            permit = backend.get_permit(job['decision_id'])
            backend.finish(permit['permit_id'], ack, at)
        elif args.arm == 'durable_count':
            backend.finish(job, ack)
        return {**value, 'status': 'acknowledged', 'ack': ack}

    def recover(job, descriptor, at):
        # This is redelivery of an already-dispatched queue message, not new admission.
        if args.arm == 'ecrc':
            permit = backend.get_permit(job['decision_id'])
            if permit is None:
                raise ValueError('missing durable ECRC permission')
            stored = backend.get_job(permit['permit_id'])
            if stored is None:
                raise ValueError('missing durable ECRC intent')
            expected = {'idempotency_key': stored['idempotency_key'], 'payload': json.loads(stored['payload_json'])}
            origin = 'ecrc_durable_outbox'
        elif args.arm == 'durable_count':
            persisted = [op['descriptor'] for op in backend.snapshot()['operations']
                         if op['descriptor']['payload']['job_hash'] == job['job_hash']]
            if len(persisted) != 1:
                raise ValueError('missing durable direct intent')
            expected, origin = persisted[0], 'direct_durable_log'
        else:
            # Validate deterministic identity using the unchanged original function.
            expected = load_direct()().submit_descriptor(job)
            origin = 'shared_upstream_unacknowledged_message'
        if descriptor != expected:
            raise ValueError('queue redelivery differs from original operation')
        return {**post(job, expected, at), 'recovery_origin': origin}

    print(canonical({'event': 'ready', 'pid': os.getpid(), 'arm': args.arm}), flush=True)
    for line in sys.stdin:
        command = json.loads(line)
        op, at = command['op'], command.get('at')
        job = records.get(command.get('job'))
        try:
            if op == 'issue_only':
                result = {'status': 'issued_or_queued', 'issue_result': issue(job, at)}
            elif op == 'send':
                result = post(job, prepare(job, at), at)
            elif op == 'recover':
                result = recover(job, command['descriptor'], at)
            elif op == 'expire_A':
                # A's independent queue deadline has passed in every arm.
                result = {'status': 'queue_A_expired', 'cleanup': backend.cleanup(at) if args.arm == 'ecrc' else None}
            elif op == 'snapshot':
                result = {'status': 'snapshot', 'state': backend.snapshot()}
            else:
                raise ValueError('unknown operation')
            print(canonical({'event': 'result', 'op': op, 'job': command.get('job'), **result}), flush=True)
        except Exception as exc:
            print(canonical({'event': 'error', 'op': op, 'error_type': type(exc).__name__, 'message': str(exc)}), flush=True)


if __name__ == '__main__':
    main()
