"""Feedback-loop regressions with fabricated transports and inert candidates."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from batch_backend import InvalidRequest
from prompts import messages_for
from trajectory import dispatch, run_episode
from transport_contract import ProviderFailure
import trajectory_external


class StubBackend:
    instances = []

    def __init__(self, **kwargs):
        self.calls = []
        self.instances.append(self)

    def set_turn(self, turn):
        self.turn = turn

    def summary(self):
        return {'actual_starts': 0, 'execution_start_count_known': True,
                'known_verified_pass_tasks': [], 'known_verified_pass_count': 0}

    def close(self):
        pass

    def snapshot(self, label):
        pass

    def register_candidate(self, task_id, code):
        self.calls.append(('register', task_id, code))
        return {'candidate_id': 'c1', 'task_id': task_id, 'deduplicated': False}

    def finish(self, candidates):
        self.calls.append(('finish', candidates))
        return {'status': 'finished', 'selected_candidate_ids': candidates}


class BudgetStub:
    def summary(self, episode=None):
        return {'unit_fixture_only': True}


def tool(name, arguments):
    return {'id': 'fixture-tool', 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments)}}


class FeedbackClient:
    budget = BudgetStub()

    def __init__(self):
        self.calls = 0

    def chat(self, *, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            call = tool('register_candidate', {'task_id': 'UnitTask/0', 'code': 'INERT FIXTURE'})
        else:
            feedback = json.loads(messages[-1]['content'])
            if feedback.get('candidate_id') != 'c1':
                raise AssertionError('Actor did not receive the previous tool result')
            call = tool('finish', {'candidate_ids': []})
        return {'role': 'assistant', 'content': None, 'tool_calls': [call]}, f'fixture-{self.calls}'


class FailedClient:
    budget = BudgetStub()

    def __init__(self, category):
        self.category = category

    def chat(self, **kwargs):
        error = ProviderFailure('unit fixture only')
        error.category = self.category
        error.stage = 'unit_stage'
        error.call_id = 'unit-uncertain-call'
        raise error


class FeedbackTests(unittest.TestCase):
    row = {'episode': 'unit-episode', 'arm': 'ecrc', 'condition': 'normal', 'model': 'unit-model'}
    batch = {'tasks': [{'task_id': 'UnitTask/0', 'entry_point': 'f', 'prompt': 'UNIT',
                        'test': 'SUITE_SENTINEL', 'canonical_solution': 'REFERENCE_SENTINEL'}]}

    def test_feedback_reaches_next_actor_call_and_finish_stops_loop(self):
        with tempfile.TemporaryDirectory(prefix='online-public-') as directory, \
             patch('batch_backend.Backend', StubBackend), \
             patch('acceptance.evaluate', side_effect=AssertionError('empty selection must not execute')):
            client = FeedbackClient()
            result = run_episode(self.row, self.batch, Path(directory) / 'episode', client)
            self.assertEqual(result['status'], 'finished')
            self.assertEqual(result['actor_calls_returned'], 2)
            self.assertEqual(len(StubBackend.instances[-1].calls), 2)
            self.assertEqual(result['acceptance'], [])

    def test_provider_failures_keep_attempt_and_category_without_retry(self):
        with tempfile.TemporaryDirectory(prefix='online-public-') as directory:
            for category in ('provider_failure', 'model_response_error', 'usage_audit_failure'):
                with self.subTest(category=category), patch('batch_backend.Backend', StubBackend):
                    result = run_episode(self.row, self.batch, Path(directory) / category, FailedClient(category))
                    self.assertEqual(result['status'], category)
                    self.assertEqual(result['actor_call_ids'], ['unit-uncertain-call'])
                    self.assertEqual(result['returned_call_ids'], [])
                    self.assertEqual(result['acceptance'], [])
                    self.assertEqual(StubBackend.instances[-1].calls, [])

    def test_supplemental_loop_preserves_native_history_metadata(self):
        class NativeClient(FeedbackClient):
            def chat(self, *, messages, **kwargs):
                if self.calls:
                    previous = messages[-2]
                    if previous.get('_provider_content') != [{'type': 'fixture_marker'}]:
                        raise AssertionError('Native history was dropped')
                    if previous.get('reasoning_content') != 'fabricated fixture marker':
                        raise AssertionError('Provider continuation metadata was dropped')
                message, call_id = super().chat(messages=messages, **kwargs)
                message.update(_provider_content=[{'type': 'fixture_marker'}],
                               reasoning_content='fabricated fixture marker')
                return message, call_id
        with tempfile.TemporaryDirectory(prefix='online-public-') as directory, \
             patch('batch_backend.Backend', StubBackend):
            result = trajectory_external.run_episode(self.row, self.batch, Path(directory) / 'episode', NativeClient())
            self.assertEqual(result['status'], 'finished')
            self.assertEqual(result['actor_calls_returned'], 2)

    def test_model_inputs_exclude_tests_and_reference_solutions(self):
        encoded = json.dumps(messages_for(self.batch))
        self.assertNotIn('SUITE_SENTINEL', encoded)
        self.assertNotIn('REFERENCE_SENTINEL', encoded)

    def test_malformed_calls_never_dispatch(self):
        for raw in ('not-json', '{"candidate_id":"c1","candidate_id":"c2"}',
                    '{"candidate_id":true}', '{"candidate_id":"c1","extra":"x"}'):
            backend = StubBackend()
            call = {'function': {'name': 'verify', 'arguments': raw}}
            self.assertEqual(dispatch(backend, call)[0]['status'], 'invalid_request')
            self.assertEqual(backend.calls, [])

    def test_actor_mistake_and_internal_corruption_are_distinct(self):
        class RejectingBackend:
            def __init__(self, error):
                self.error = error
            def verify(self, candidate_id):
                raise self.error
        call = tool('verify', {'candidate_id': 'c404'})
        self.assertEqual(dispatch(RejectingBackend(InvalidRequest('unknown candidate')), call)[0]['status'], 'invalid_request')
        with self.assertRaisesRegex(ValueError, 'corrupted'):
            dispatch(RejectingBackend(ValueError('corrupted ACK')), call)
