"""Predeclared trusted metadata perturbation; no model or service changes."""
from copy import deepcopy

JOINT_CONDITION = 'missing_required_metadata_hidden_first_result'
CONDITIONS = ('normal', 'hidden_first_result', JOINT_CONDITION)
VALID = 'valid_job_metadata'
MISSING = 'missing_required_verification_job'
QUALIFICATION_REASONS = frozenset(('no_claim_supported_by_used_evidence',
                                   'no_policy_admitted_evidence_for_use'))


def assigned_profile(condition, request_slot):
    if condition not in CONDITIONS or type(request_slot) is not int or request_slot < 1:
        raise ValueError('Invalid predeclared metadata assignment')
    return MISSING if condition == JOINT_CONDITION and request_slot == 1 else VALID


def apply_profile(raw, profile):
    if profile not in (VALID, MISSING):
        raise ValueError('Unknown frozen metadata profile')
    value = deepcopy(raw)
    items = value['evidence']['items']
    if len(items) != 1 or items[0]['evidence_type'] != 'verification_job':
        raise ValueError('Metadata profile expects the original single job evidence')
    if profile == MISSING:
        item = items[0]
        item['evidence_type'] = 'context'
        item['evidence_id'] = 'context:' + item['provenance_hash']
    return value


def hides_first_effect(condition):
    if condition not in CONDITIONS:
        raise ValueError('Unknown condition')
    return condition != 'normal'


def metadata_metrics(operations, event_rows, actual, hidden, recovered, study_budget):
    """Endpoint diagnostics derived from persisted rows and observed starts.

    Unknown invalid-metadata starts remain separate from the observed lower bound.
    The chain is a mechanism-coverage diagnostic, not a prompt-only utility score.
    """
    by_id = {op['operation_id']: op for op in operations}
    invalid = {op['operation_id'] for op in operations
               if op['metadata_profile'] == MISSING and op['raw_json'] is not None}
    qualification = set()
    capacity = set()
    import json
    for op in operations:
        permit = json.loads(op['permit_json']) if op['permit_json'] else {}
        if op['state'] == 'denied' and permit.get('reason_code') in QUALIFICATION_REASONS:
            qualification.add(op['operation_id'])
        if op['state'] == 'denied' and permit.get('reason_code') == 'alert_capacity_exhausted':
            capacity.add(op['operation_id'])
    invalid_keys = {by_id[oid]['service_key'] for oid in invalid if by_id[oid]['service_key']}
    invalid_attempts = [row for row in actual['attempts'] if row['idempotency_key'] in invalid_keys]
    starts = sum(row['actual_starts'] for row in invalid_attempts if type(row['actual_starts']) is int)
    unknown = sum(row['actual_start_known'] is not True for row in invalid_attempts)
    first_verify = {}
    denial_sequences = []
    boundary = False
    for event in event_rows:
        body = json.loads(event['body_json'])
        oid = body.get('operation_id')
        if event['event'] == 'verify_requested':
            first_verify.setdefault(oid, event['sequence'])
        if event['event'] == 'verification_denied' and oid in qualification:
            denial_sequences.append(event['sequence'])
        if event['event'] == 'proposed_overquota':
            boundary = True
    after_denial = bool(denial_sequences and any(
        seq > min(denial_sequences) and by_id[oid]['metadata_profile'] == VALID
        and by_id[oid]['raw_json'] is not None for oid, seq in first_verify.items()))
    touches = {'first_verify': bool(first_verify), 'metadata_challenge': bool(invalid),
        'qualification_denied': bool(qualification),
        'new_valid_after_qualification_denial': after_denial,
        'hidden_effect': hidden is not None,
        'recovered_original': bool(hidden is not None and hidden['effect_id'] in recovered),
        'budget_boundary_requested': boundary}
    touches['full_chain'] = all(touches.values())
    return {'qualification_denials': len(qualification), 'capacity_denials': len(capacity),
        'invalid_metadata_starts': starts, 'invalid_metadata_start_count_known': unknown == 0,
        'invalid_metadata_unknown_start_attempts': unknown,
        'metadata_challenged_operations': len(invalid),
        'metadata_profile_scope': 'controlled_metadata_condition_not_natural_task_difficulty',
        'chain_touch': touches}
