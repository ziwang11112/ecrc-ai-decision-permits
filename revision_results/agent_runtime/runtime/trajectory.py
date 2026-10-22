"""Formal CMC budget/metadata study using the existing autonomous actor loop.

The trusted backend assigns predeclared metadata without changing actor dispatch.
No candidate code is executed in this host process.
"""
from pathlib import Path
import hashlib
import json
import os
import time
from transport_contract import BudgetDenied, ProviderFailure
from budget_metrics import validate_budget, metric_fields
from prompts import TOOLS, messages_for

CONFIG = {'max_actor_calls': 16, 'max_completion_tokens': 4096,
          'common_new_job_safety_cap': 8}
STOP_STATUSES = {'budget_stop', 'provider_failure', 'model_response_error',
                 'usage_audit_failure', 'infrastructure_error', 'interrupted'}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def write(path, value, *, replace=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w' if replace else 'x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def budget_snapshot(budget, episode=None):
    try:
        return budget.summary(episode)
    except Exception as exc:
        return {'budget_audit_error': type(exc).__name__, 'usage_and_balance_known': False}


def dispatch(backend, call):
    from batch_backend import InvalidRequest
    name = call.get('function', {}).get('name')
    expected = {'register_candidate': {'task_id', 'code'}, 'verify': {'candidate_id'},
        'recover': {'operation_id'}, 'finish': {'candidate_ids'}}
    try:
        def unique(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError('duplicate argument')
                result[key] = value
            return result
        args = json.loads(call.get('function', {}).get('arguments', ''), object_pairs_hook=unique)
        if name not in expected or type(args) is not dict or set(args) != expected[name]:
            raise ValueError('tool schema mismatch')
        if name == 'finish':
            refs = args['candidate_ids']
            if (type(refs) is not list or len(refs) > 4 or any(type(x) is not str for x in refs)
                    or len(set(refs)) != len(refs)):
                raise ValueError('invalid candidate selection')
        elif any(type(value) is not str or not value for value in args.values()):
            raise ValueError('nonempty strings required')
        if name == 'register_candidate' and len(args['code'].encode('utf-8')) > 50000:
            raise ValueError('code too large')
    except (ValueError, TypeError, KeyError):
        return {'status': 'invalid_request', 'feedback': 'Tool arguments do not match the supplied schema.'}, False
    # Only explicit actor mistakes become tool feedback. Internal failures must
    # escape and stop execution, not be disguised as ordinary tool feedback.
    try:
        if name == 'register_candidate':
            feedback = backend.register_candidate(args['task_id'], args['code'])
        elif name == 'verify':
            feedback = backend.verify(args['candidate_id'])
        elif name == 'recover':
            feedback = backend.recover(args['operation_id'])
        else:
            feedback = backend.finish(args['candidate_ids'])
    except InvalidRequest as exc:
        return {'status': 'invalid_request', 'feedback': str(exc)}, False
    return feedback, name == 'finish' and feedback.get('status') == 'finished'


def run_episode(row, batch, out, client, *, offline_backend_factory=None, stop_requested=None):
    from acceptance import evaluate
    from batch_backend import Backend
    study_budget = validate_budget(row['study_budget'])
    if len(batch['tasks']) != 4:
        raise ValueError('pilot requires exactly four eligible tasks')
    if row.get('development_only') is not False or row.get('formal_study') is not True:
        raise ValueError('this wrapper requires an explicitly formal assignment')
    if stop_requested is not None and not callable(stop_requested):
        raise ValueError('global stop callback must be supplied by trusted orchestration')
    out = Path(out).resolve()
    if offline_backend_factory is not None and not out.is_relative_to(Path(__file__).resolve().parent / 'tests'):
        raise ValueError('offline backend injection is restricted to tests')
    out.mkdir(parents=True, exist_ok=False)
    write(out / 'assignment.json', row)
    messages = messages_for(batch, study_budget)
    write(out / 'initial_messages.json', messages)
    start = time.perf_counter()
    backend = None
    status, error, selections = 'turn_limit', None, None
    workflow_seconds = None
    returned_ids, attempted_ids, acceptance = [], [], []

    class GlobalStudyStop(Exception):
        pass

    def check_stop():
        if stop_requested is not None and stop_requested():
            raise GlobalStudyStop('Trusted study coordinator stopped further work')

    def event(kind, **body):
        record = {'event': kind, 'elapsed_seconds': time.perf_counter() - start, **body}
        with (out / 'actor_events.jsonl').open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(canonical(record) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    try:
        backend_type = offline_backend_factory or Backend
        backend = backend_type(run_dir=out / 'execution', tasks=batch['tasks'], arm=row['arm'],
            condition=row['condition'], study_budget=study_budget,
            safety_job_cap=CONFIG['common_new_job_safety_cap'], model_id=row['model'])
        for turn in range(CONFIG['max_actor_calls']):
            check_stop()
            backend.set_turn(turn)
            event('model_call_started', turn=turn)
            try:
                message, call_id = client.chat(messages=messages, tools=TOOLS, episode=row['episode'],
                    max_tokens=CONFIG['max_completion_tokens'])
            except BudgetDenied:
                status = 'budget_stop'
                break
            except ProviderFailure as exc:
                status = getattr(exc, 'category', 'provider_failure')
                if status not in STOP_STATUSES:
                    status = 'provider_failure'
                error = {'type': 'ProviderFailure', 'stage': getattr(exc, 'stage', None),
                    'call_id': getattr(exc, 'call_id', None)}
                if error['call_id']:
                    attempted_ids.append(error['call_id'])
                event('api_attempt_not_dispatchable', turn=turn, error=error)
                break
            returned_ids.append(call_id)
            attempted_ids.append(call_id)
            event('model_response', turn=turn, call_id=call_id, message=message)
            safe_message = {k: v for k, v in message.items() if k in ('role', 'content', 'tool_calls')}
            safe_message['role'] = 'assistant'
            messages.append(safe_message)
            # A response can arrive after another worker stops the shared study.
            # Retain that paid response and its call ID, but do not dispatch it.
            check_stop()
            calls = message.get('tool_calls') or []
            if not calls:
                messages.append({'role': 'user', 'content': 'The batch is not finished. Use the tools, or finish with your selected candidate IDs (possibly an empty list). There are no extra turns beyond sixteen.'})
                write(out / 'conversation.json', messages, replace=True)
                continue
            if len(calls) != 1:
                for call in calls:
                    feedback = {'status': 'invalid_request', 'feedback': 'Exactly one tool call per turn. No calls in this batch were executed.'}
                    messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': canonical(feedback)})
                    event('tool_result', turn=turn, tool_call=call, feedback=feedback)
                write(out / 'conversation.json', messages, replace=True)
                continue
            call = calls[0]
            check_stop()
            feedback, finished = dispatch(backend, call)
            backend.snapshot(f't{turn:02}')
            event('tool_result', turn=turn, tool_call=call, feedback=feedback)
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': canonical(feedback)})
            write(out / 'conversation.json', messages, replace=True)
            if finished:
                selections = feedback['selected_candidate_ids']
                status = 'finished'
                break
        workflow_seconds = time.perf_counter() - start
        write(out / 'endpoint_execution.json', backend.summary())
        # Strictly post-endpoint fresh executions, never returned to the model.
        if selections is not None:
            bindings = []
            for i, ref in enumerate(selections):
                check_stop()
                job = backend.get_job(ref)
                bindings.append({'candidate_ref': ref, **{k: job[k] for k in
                    ('task_id', 'candidate_id', 'solution_sha256', 'test_sha256', 'runner_sha256', 'job_hash')}})
                check_stop()
                record = evaluate(job, out / 'acceptance' / f'a{i}')
                acceptance.append({'candidate_ref': ref, 'task_id': job['task_id'], 'record': record})
                if record['status'] == 'infrastructure_error' or record.get('actual_start_known') is not True:
                    raise RuntimeError('independent acceptance infrastructure failure')
            write(out / 'selected_bindings.json', bindings)
    except GlobalStudyStop:
        status, error = 'interrupted', {'type': 'GlobalStudyStop'}
        if workflow_seconds is None:
            workflow_seconds = time.perf_counter() - start
        event('global_study_stop', error=error)
        write(out / 'conversation.json', messages, replace=True)
    except KeyboardInterrupt:
        status, error = 'interrupted', {'type': 'KeyboardInterrupt'}
        workflow_seconds = time.perf_counter() - start
    except Exception as exc:
        status, error = 'infrastructure_error', {'type': type(exc).__name__}
        workflow_seconds = time.perf_counter() - start
        event('infrastructure_error', error=error)
    finally:
        execution = {}
        if backend is not None:
            try:
                execution = backend.summary()
                backend.close()
            except Exception as exc:
                status, error = 'infrastructure_error', {'type': type(exc).__name__, 'previous': error}
    write(out / 'acceptance_results.json', acceptance)
    usage = budget_snapshot(client.budget, row['episode'])
    if usage.get('budget_audit_error'):
        status, error = 'infrastructure_error', {'type': 'BudgetAuditError', 'previous': error}
    result = {**row, 'status': status, 'error': error, 'eligible_tasks': len(batch['tasks']),
        'workflow_verified_pass_tasks': execution.get('known_verified_pass_tasks', []),
        'workflow_verified_pass_count': execution.get('known_verified_pass_count'),
        'verification_budget_compliant': (execution['actual_starts'] <= study_budget
            if execution.get('execution_start_count_known') is True else None),
        'selected_candidate_refs': selections, 'actor_calls_returned': len(returned_ids),
        'actor_call_ids': attempted_ids, 'returned_call_ids': returned_ids,
        'workflow_seconds': workflow_seconds, 'total_seconds_including_acceptance': time.perf_counter() - start,
        'execution': execution, 'acceptance': acceptance,
        'independent_accepted_selected_tasks': sum(a['record']['status'] == 'pass' for a in acceptance),
        'api_usage': usage}
    result.update(metric_fields(result, study_budget))
    write(out / 'summary.json', result)
    return result
