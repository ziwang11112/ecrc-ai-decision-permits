"""Explicit unit fixtures; no model, credential, network or sandbox calls."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
FORMAL = Path(__file__).resolve().parents[1]
RUNTIME = FORMAL / 'runtime'
sys.path.insert(0, str(RUNTIME))
parser = argparse.ArgumentParser()
parser.add_argument('--tag', default='t1')
args = parser.parse_args()
if not re.fullmatch(r'[a-z][a-z0-9]{0,7}', args.tag): raise ValueError('Short fresh test tag required')
OUT = RUNTIME / 'tests' / args.tag
OUT.mkdir(parents=True, exist_ok=False)


def forbidden(*args, **kwargs):
    raise AssertionError('No real networking, provider import, credential lookup or sandbox in unit fixtures')


class BlockProviders:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'providers', 'provider_codec', 'cross_client', 'cross_budget',
                                     'transport', 'formal_budget', 'openai', 'anthropic', 'requests', 'httpx'}:
            forbidden()
        return None


sys.meta_path.insert(0, BlockProviders())
socket.create_connection = forbidden
socket.socket.connect = forbidden
subprocess.Popen = forbidden
from batch_backend import Backend, ARMS
from budget_metrics import metric_fields, validate_budget
from effect_service import IDENTITY_FIELDS
from metadata_profiles import (JOINT_CONDITION, CONDITIONS, VALID, MISSING,
                               assigned_profile, apply_profile, metadata_metrics)
from prompts import TOOLS, messages_for
from trajectory import run_episode
from transport_contract import BudgetDenied, ProviderFailure
from vendor.adapters import load_adapter, verify_frozen
from workload.job_runner import runner_sha256

TASKS = [{'task_id': f'Unit/{i}', 'entry_point': 'unit', 'prompt': 'UNIT FIXTURE',
          'test': f'NEVER EXECUTED TEST {i}'} for i in range(4)]
INERT = 'INERT UNIT FIXTURE NOT EXECUTABLE PYTHON '
OBSERVATIONS = []


class UnitRunner:
    def __init__(self): self.calls = []
    def __call__(self, job, work_dir):
        self.calls.append(deepcopy(job))
        return {**{key: job[key] for key in IDENTITY_FIELDS}, 'job_digest': job['job_hash'],
                'status': 'pass', 'actual_start_known': True, 'actual_starts': 1,
                'cpu_seconds': 0., 'wall_seconds': 0., 'launcher_wall_seconds': 0.,
                'unit_fixture_only': True}


class FakeBudget:
    def summary(self, episode=None): return {'fixture_only': True, 'actual_model_api_calls': 0}


def backend(name, arm, condition='normal', budget=3, runner=None):
    return Backend(OUT / name, deepcopy(TASKS), arm, condition, study_budget=budget,
                   offline_test_runner=runner or UnitRunner())


def register_many(value, n):
    return [value.register_candidate(TASKS[i % 4]['task_id'], INERT + str(i))['candidate_id'] for i in range(n)]


class RuntimeTests(unittest.TestCase):
    def test_01_bundle_and_formal_prompts(self):
        verify_frozen()
        original = FORMAL.parents[1] / 'online_agent/runtime'
        self.assertEqual((RUNTIME / 'effect_service.py').read_bytes(), (original / 'effect_service.py').read_bytes())
        for path in (RUNTIME / 'workload').rglob('*'):
            if path.is_file(): self.assertEqual(path.read_bytes(), (original / path.relative_to(RUNTIME)).read_bytes())
        spec = importlib.util.spec_from_file_location('_pure_old_prompts', original / 'prompts.py')
        old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
        self.assertEqual(TOOLS, old.TOOLS)
        for budget, word in ((1, 'ONE'), (3, 'THREE'), (5, 'FIVE')):
            messages = messages_for({'tasks': TASKS}, budget)
            self.assertIn(word + ' NEW', messages[0]['content'])
            self.assertIn('complete trusted job metadata', messages[0]['content'])
            self.assertNotIn('first operation', json.dumps(messages))
            self.assertNotIn('NEVER EXECUTED TEST', json.dumps(messages))
            # Arm and condition do not enter messages_for at all.
            self.assertEqual(messages, messages_for({'tasks': TASKS, 'arm': 'ordinary', 'condition': JOINT_CONDITION}, budget))

    def test_02_profile_assignment(self):
        for condition in CONDITIONS:
            for slot in (1, 2, 5):
                self.assertEqual(assigned_profile(condition, slot), MISSING if condition == JOINT_CONDITION and slot == 1 else VALID)
        for slot in (0, True, '1', 1.0):
            with self.assertRaises(ValueError): assigned_profile(JOINT_CONDITION, slot)
        raw = {'evidence': {'items': [{'evidence_type': 'verification_job', 'evidence_id': 'job:x', 'provenance_hash': 'x'}]}}
        altered = apply_profile(raw, MISSING)
        self.assertEqual(altered['evidence']['items'][0]['evidence_type'], 'context')
        self.assertEqual(raw['evidence']['items'][0]['evidence_type'], 'verification_job')

    def test_03_all_budget_arm_cells(self):
        for b in (1, 3, 5):
            for index, arm in enumerate(ARMS):
                runner = UnitRunner()
                with backend(f'm{b}{index}', arm, budget=b, runner=runner) as value:
                    refs = register_many(value, b + 1)
                    feedback = [value.verify(ref) for ref in refs]
                    result = value.summary()
                    expected = b + 1 if arm == 'prompt_only' else b
                    self.assertEqual(result['actual_starts'], expected)
                    self.assertEqual(result['capacity_denials'], int(arm != 'prompt_only'))
                    self.assertEqual(result['qualification_denials'], 0)
                    self.assertEqual(result['invalid_metadata_starts'], 0)
                    self.assertEqual(result['duplicate_starts'], 0)
                    for op in result['operations']:
                        self.assertEqual(op['metadata_profile'], VALID)
                        self.assertEqual(json.loads(op['raw_json'])['evidence']['items'][0]['evidence_type'], 'verification_job')
                        if op['payload_json']:
                            payload = json.loads(op['payload_json'])
                            self.assertEqual(len(payload['used_evidence_ids']), 1)
                            self.assertTrue(payload['used_evidence_ids'][0].startswith('job:'))
                    OBSERVATIONS.append({'fixture': 'budget_matrix', 'B': b, 'arm': arm, 'fabricated_starts': expected})

    def test_04_combined_chain_all_arms(self):
        for index, arm in enumerate(ARMS):
            runner = UnitRunner()
            with backend('j' + str(index), arm, JOINT_CONDITION, runner=runner) as value:
                refs = register_many(value, 5)
                value.set_turn(0); first = value.verify(refs[0])
                raw_before = value.summary()['operations'][0]['raw_json']
                count_before = len(runner.calls)
                self.assertEqual(value.verify(refs[0])['status'], 'unknown' if arm == 'prompt_only' else 'denied')
                self.assertEqual(len(runner.calls), count_before)
                self.assertEqual(value.recover(first['operation_id'])['status'], 'unknown' if arm == 'prompt_only' else 'not_found')
                value.set_turn(1); second = value.verify(refs[1])
                hidden_id = first['operation_id'] if arm == 'prompt_only' else second['operation_id']
                value.set_turn(2); value.verify(refs[2])
                value.set_turn(3); value.verify(refs[3])
                self.assertEqual(value.recover(hidden_id)['status'], 'completed' if arm == 'prompt_only' else 'unknown')
                value.set_turn(4); last = value.verify(refs[4])
                before = len(runner.calls); self.assertEqual(value.recover(hidden_id)['status'], 'completed')
                self.assertEqual(value.recover(hidden_id)['status'], 'completed'); self.assertEqual(len(runner.calls), before)
                result = value.summary()
                self.assertEqual(result['actual_starts'], 5 if arm == 'prompt_only' else 3)
                self.assertEqual(result['qualification_denials'], int(arm != 'prompt_only'))
                self.assertEqual(result['capacity_denials'], int(arm != 'prompt_only'))
                self.assertEqual(result['invalid_metadata_starts'], int(arm == 'prompt_only'))
                self.assertTrue(result['invalid_metadata_start_count_known'])
                self.assertEqual(result['held'], 0); self.assertEqual(result['duplicate_starts'], 0)
                self.assertEqual(result['chain_touch']['full_chain'], arm != 'prompt_only')
                self.assertEqual(result['operations'][0]['raw_json'], raw_before)
                self.assertEqual([op['request_slot'] for op in result['operations']], list(range(1, 6)))
                self.assertEqual([op['metadata_profile'] for op in result['operations']], [MISSING] + [VALID] * 4)
                OBSERVATIONS.append({'fixture': 'combined_chain', 'arm': arm, 'summary': result})

    def test_05_restart_preserves_denied_slot_and_raw(self):
        for index, arm in enumerate(('ordinary', 'ecrc')):
            runner = UnitRunner(); value = backend('r' + str(index), arm, JOINT_CONDITION, runner=runner)
            refs = register_many(value, 2)
            value.verify(refs[0]); original = value.summary()['operations'][0]
            self.assertEqual(value.register_candidate(TASKS[0]['task_id'], INERT + '0')['candidate_id'], refs[0])
            value.close()
            with backend('r' + str(index), arm, JOINT_CONDITION, runner=runner) as reopened:
                self.assertEqual(reopened.verify(refs[0])['status'], 'denied')
                reopened.verify(refs[1]); result = reopened.summary()
                self.assertEqual(result['operations'][0]['raw_json'], original['raw_json'])
                self.assertEqual(result['operations'][0]['request_slot'], 1)
                self.assertEqual(result['operations'][1]['metadata_profile'], VALID)
                with reopened.connect() as db:
                    for query in ("UPDATE operations SET metadata_profile='valid_job_metadata' WHERE request_slot=1",
                                  "UPDATE operations SET raw_json='{}' WHERE request_slot=1", 'DELETE FROM operations'):
                        with self.assertRaises(sqlite3.IntegrityError): db.execute(query)

    def test_06_no_qualification_consumption(self):
        for index, arm in enumerate(('ordinary', 'ecrc')):
            with backend('q' + str(index), arm, JOINT_CONDITION) as value:
                ref = register_many(value, 1)[0]
                self.assertEqual(value.verify(ref)['status'], 'denied')
                result = value.summary(); permit = json.loads(result['operations'][0]['permit_json'])
                self.assertEqual(permit['reason_code'], 'no_claim_supported_by_used_evidence')
                self.assertEqual(permit['route'], 'abstain')
                self.assertEqual(result['held'], 0); self.assertEqual(result['actual_starts'], 0)
                self.assertEqual(result['adapter_snapshot']['committed'], 0)
                self.assertFalse(result['hidden_results'])

    def test_07_unknown_invalid_starts_not_zero_certification(self):
        op = {'operation_id': 'o1', 'metadata_profile': MISSING, 'raw_json': '{}',
              'permit_json': None, 'state': 'armed', 'service_key': 'k1'}
        actual = {'attempts': [{'idempotency_key': 'k1', 'actual_starts': None, 'actual_start_known': False}]}
        result = metadata_metrics([op], [], actual, None, set(), 3)
        self.assertEqual(result['invalid_metadata_starts'], 0)
        self.assertFalse(result['invalid_metadata_start_count_known'])
        self.assertEqual(result['invalid_metadata_unknown_start_attempts'], 1)

    def test_08_metric_ceiling_and_unknowns(self):
        for b in (1, 3, 5):
            result = {'eligible_tasks': 4, 'workflow_verified_pass_count': min(b, 4),
                      'execution': {'actual_starts': b, 'execution_start_count_known': True, 'study_budget': b}}
            self.assertEqual(metric_fields(result, b)['compliant_verified_yield_ceiling'], min(b, 4)/4)
        result['execution']['execution_start_count_known'] = False
        self.assertIsNone(metric_fields(result, 5)['verification_budget_compliant'])
        self.assertEqual(metric_fields(result, 5)['compliant_verified_yield'], 0)

    def test_09_actor_failure_classes_and_formal_scope(self):
        special = ProviderFailure('unit'); special.category = 'provider_failure'; special.call_id = 'unit-call'
        for index, (exc, expected) in enumerate(((BudgetDenied('unit'), 'budget_stop'),
                                                (special, 'provider_failure'), (ValueError('unit'), 'infrastructure_error'))):
            class Client:
                budget = FakeBudget()
                calls = 0
                def chat(self, **kw): self.calls += 1; raise exc
            client = Client()
            row = {'episode': 'unit', 'model': 'gpt-4.1-mini-2025-04-14', 'arm': 'ordinary',
                   'condition': JOINT_CONDITION, 'study_budget': 3, 'formal_study': True, 'development_only': False}
            result = run_episode(row, {'tasks': TASKS}, OUT / ('a' + str(index)), client,
                                 offline_backend_factory=lambda **kw: Backend(**kw, offline_test_runner=forbidden))
            self.assertEqual(result['status'], expected); self.assertEqual(client.calls, 1)
            self.assertEqual(result['actor_call_ids'], ['unit-call'] if index == 1 else [])
        row['development_only'] = True
        with self.assertRaises(ValueError): run_episode(row, {'tasks': TASKS}, OUT / 'bad', client)

    def test_10_threaded_instances_have_separate_runner_and_state(self):
        load_adapter('ordinary'); load_adapter('ecrc')  # Same preloading contract as formal driver.
        def worker(index):
            arm = ARMS[index % 3]; runner = UnitRunner()
            with backend('c' + str(index), arm, JOINT_CONDITION, runner=runner) as value:
                refs = register_many(value, 2)
                value.verify(refs[0]); value.verify(refs[1]); result = value.summary()
                return arm, len(runner.calls), result['actual_starts'], result['operations'][0]['metadata_profile']
        with ThreadPoolExecutor(max_workers=8) as pool: results = list(pool.map(worker, range(8)))
        for arm, calls, starts, profile in results:
            self.assertEqual(calls, 2 if arm == 'prompt_only' else 1)
            self.assertEqual(starts, calls); self.assertEqual(profile, MISSING)

    def test_11_same_scripted_feedback_loop_reaches_joint_chain(self):
        # This explicitly scripted actor is only a fixture, never a model sample.
        schedule = [('register', 0), ('verify', 0), ('register', 1), ('verify', 1),
                    ('recover', None), ('register', 2), ('verify', 2), ('register', 3),
                    ('verify', 3), ('register', 4), ('verify', 4), ('recover', None), ('finish', None)]
        for index, arm in enumerate(ARMS):
            class Scripted:
                def __init__(self): self.budget = FakeBudget(); self.turn = 0; self.refs = {}; self.hidden = None
                def chat(self, *, messages, tools, episode, max_tokens):
                    if messages[-1]['role'] == 'tool':
                        feedback = json.loads(messages[-1]['content'])
                        if 'deduplicated' in feedback: self.refs[schedule[self.turn - 1][1]] = feedback['candidate_id']
                        if feedback.get('status') == 'unknown': self.hidden = feedback['operation_id']
                    action, item = schedule[self.turn]
                    if action == 'register': name, args = 'register_candidate', {'task_id': TASKS[item % 4]['task_id'], 'code': INERT + str(item)}
                    elif action == 'verify': name, args = 'verify', {'candidate_id': self.refs[item]}
                    elif action == 'recover': name, args = 'recover', {'operation_id': self.hidden}
                    else: name, args = 'finish', {'candidate_ids': []}
                    self.turn += 1
                    return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'u' + str(self.turn),
                        'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}, 'unit-' + str(self.turn)
            client = Scripted(); runner = UnitRunner()
            row = {'episode': 'unit', 'model': 'gpt-4.1-mini-2025-04-14', 'arm': arm,
                   'condition': JOINT_CONDITION, 'study_budget': 3, 'formal_study': True, 'development_only': False}
            result = run_episode(row, {'tasks': TASKS}, OUT / ('l' + str(index)), client,
                                 offline_backend_factory=lambda **kw: Backend(**kw, offline_test_runner=runner))
            self.assertEqual(result['status'], 'finished'); self.assertEqual(client.turn, 13)
            self.assertEqual(result['execution']['chain_touch']['full_chain'], arm != 'prompt_only')
            self.assertEqual(result['execution']['actual_starts'], 5 if arm == 'prompt_only' else 3)
            self.assertEqual(result['execution']['duplicate_starts'], 0)
            OBSERVATIONS.append({'fixture': 'scripted_feedback_loop', 'arm': arm,
                                 'scripted_calls': 13, 'actual_model_api_calls': 0,
                                 'chain_touch': result['execution']['chain_touch']})

    def test_12_global_stop_preserves_paid_response_without_dispatch(self):
        from threading import Event
        stop = Event()
        class Client:
            budget = FakeBudget()
            def chat(self, **kwargs):
                stop.set()
                return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'u1', 'type': 'function',
                    'function': {'name': 'register_candidate', 'arguments': json.dumps({'task_id': TASKS[0]['task_id'],
                    'code': INERT})}}]}, 'paid-before-shared-stop'
        row = {'episode': 'unit-stop', 'model': 'gpt-4.1-mini-2025-04-14', 'arm': 'ordinary',
               'condition': JOINT_CONDITION, 'study_budget': 3, 'formal_study': True, 'development_only': False}
        result = run_episode(row, {'tasks': TASKS}, OUT / 's1', Client(), stop_requested=stop.is_set,
            offline_backend_factory=lambda **kw: Backend(**kw, offline_test_runner=forbidden))
        self.assertEqual(result['status'], 'interrupted')
        self.assertEqual(result['error']['type'], 'GlobalStudyStop')
        self.assertEqual(result['returned_call_ids'], ['paid-before-shared-stop'])
        self.assertEqual(result['actor_call_ids'], ['paid-before-shared-stop'])
        self.assertEqual(result['execution']['candidates'], [])
        self.assertEqual(result['execution']['actual_starts'], 0)

    def test_13_global_stop_prevents_next_independent_acceptance(self):
        import acceptance
        from threading import Event
        stop = Event()
        class Client:
            budget = FakeBudget()
            turn = 0
            refs = []
            def chat(self, *, messages, **kwargs):
                if messages[-1]['role'] == 'tool': self.refs.append(json.loads(messages[-1]['content'])['candidate_id'])
                if self.turn < 2:
                    name, args = 'register_candidate', {'task_id': TASKS[self.turn]['task_id'], 'code': INERT + str(self.turn)}
                else: name, args = 'finish', {'candidate_ids': self.refs}
                self.turn += 1
                return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'u' + str(self.turn), 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(args)}}]}, 'unit-' + str(self.turn)
        count = []
        def first_only(job, out):
            count.append(job); stop.set()
            return {'status': 'pass', 'actual_start_known': True, 'unit_fixture_only': True}
        row = {'episode': 'unit-accept-stop', 'model': 'gpt-4.1-mini-2025-04-14', 'arm': 'ordinary',
               'condition': 'normal', 'study_budget': 3, 'formal_study': True, 'development_only': False}
        with patch.object(acceptance, 'evaluate', side_effect=first_only):
            result = run_episode(row, {'tasks': TASKS}, OUT / 's2', Client(), stop_requested=stop.is_set,
                offline_backend_factory=lambda **kw: Backend(**kw, offline_test_runner=forbidden))
        self.assertEqual(result['status'], 'interrupted'); self.assertEqual(len(count), 1)
        self.assertEqual(len(result['acceptance']), 1); self.assertEqual(len(result['selected_candidate_refs']), 2)
        self.assertEqual(result['independent_accepted_selected_tasks'], 1)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RuntimeTests))
    hashes = {p.relative_to(FORMAL).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [Path(__file__), *(RUNTIME / n for n in ('batch_backend.py', 'prompts.py', 'trajectory.py',
                                                               'budget_metrics.py', 'metadata_profiles.py'))]}
    report = {'successful': result.wasSuccessful(), 'test_methods': result.testsRun, 'source_hashes': hashes,
              'failures': [{'test': str(t), 'traceback': tb} for t, tb in result.failures + result.errors],
              'actual_model_api_calls': 0, 'actual_sandbox_starts': 0, 'unit_fixture_only': True,
              'runner_sha256': runner_sha256(), 'observations': OBSERVATIONS}
    (OUT / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Artifact: ' + str(OUT / 'RESULTS.json'))
    raise SystemExit(0 if result.wasSuccessful() else 1)
