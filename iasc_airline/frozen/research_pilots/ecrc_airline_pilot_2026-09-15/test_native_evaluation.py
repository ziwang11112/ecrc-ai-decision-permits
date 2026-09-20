"""Integrity checks for the offline evaluator adapter, never actor answer rules."""

from copy import deepcopy
import unittest

from bootstrap import install

install()

from tau2.data_model.message import AssistantMessage, ToolCall
from tau2.domains.airline.environment import get_environment, get_tasks

from native_evaluation import evaluate


class NativeEvaluationTests(unittest.TestCase):
    def oracle_wiring_control(self, task_id):
        """Evaluator-private positive control; NEVER an actor performance run.

        Using reference actions here verifies only that the wiring accepts its
        own native target. It does not establish policy correctness (task 39 has
        a documented reference/policy conflict), agent reasoning, or task skill.
        """
        task = next(task for task in get_tasks(None) if task.id == task_id)
        self.assertIsNone(task.initial_state)
        env = get_environment()
        actions, messages = [], []
        for index, reference in enumerate(task.evaluation_criteria.actions or []):
            call = ToolCall(
                id=f"oracle_wiring_control_{index}",
                name=reference.name,
                arguments=reference.arguments,
                requestor=reference.requestor,
            )
            response = env.get_response(call)
            self.assertFalse(response.error)
            actions.append({
                **call.model_dump(mode="json"),
                "response": response.model_dump(mode="json"),
            })
            messages.extend([
                AssistantMessage(role="assistant", tool_calls=[call]).model_dump(mode="json"),
                response.model_dump(mode="json"),
            ])
        return evaluate(
            task_id,
            actions,
            messages,
            actor_final_db_hash=env.get_db_hash(),
        )

    def test_task39_reference_oracle_wiring_only(self):
        result = self.oracle_wiring_control("39")
        self.assertEqual(result["adapter_composed_native_reward"], 1.0)
        self.assertEqual(result["reward_breakdown"], {"DB": 1.0, "COMMUNICATE": 1.0})
        self.assertTrue(result["all_recorded_tool_responses_reproduced"])
        self.assertTrue(result["actor_final_db_match_verified"])
        self.assertEqual(result["actor_final_db_hash"], result["replay_final_db_hash"])

    def test_task42_reference_oracle_wiring_only(self):
        result = self.oracle_wiring_control("42")
        self.assertEqual(result["adapter_composed_native_reward"], 1.0)
        self.assertEqual(result["reward_breakdown"], {"DB": 1.0, "COMMUNICATE": 1.0})
        self.assertTrue(result["all_recorded_tool_responses_reproduced"])
        self.assertTrue(result["actor_final_db_match_verified"])
        self.assertEqual(result["actor_final_db_hash"], result["replay_final_db_hash"])

    def read_only_trace(self):
        env = get_environment()
        # A public tool read, deliberately unrelated to hidden expected actions.
        call = ToolCall(id="read_airports", name="list_all_airports", arguments={})
        response = env.get_response(call)
        actions = [{**call.model_dump(mode="json"), "response": response.model_dump(mode="json")}]
        messages = [
            AssistantMessage(role="assistant", tool_calls=[call]).model_dump(mode="json"),
            response.model_dump(mode="json"),
        ]
        return actions, messages, env.get_db_hash()

    def test_empty_actions_do_not_complete_repair_task(self):
        result = evaluate("39", [], [])
        self.assertEqual(result["adapter_composed_native_reward"], 0.0)
        self.assertEqual(result["reward_breakdown"], {"DB": 0.0, "COMMUNICATE": 1.0})
        self.assertTrue(result["communication_score_vacuous"])
        self.assertFalse(result["actor_final_db_match_verified"])

    def test_native_read_response_replay_and_live_hash(self):
        actions, messages, final_hash = self.read_only_trace()
        result = evaluate("42", actions, messages, actor_final_db_hash=final_hash)
        self.assertTrue(result["all_recorded_tool_responses_reproduced"])
        self.assertTrue(result["actor_final_db_match_verified"])
        self.assertEqual(result["recorded_tool_call_count"], 1)
        self.assertEqual(result["adapter_composed_native_reward"], 0.0)

    def test_reject_missing_recorded_transcript(self):
        actions, _, _ = self.read_only_trace()
        with self.assertRaisesRegex(ValueError, "chronological"):
            evaluate("39", actions)

    def test_reject_action_log_transcript_disagreement(self):
        actions, messages, _ = self.read_only_trace()
        actions[0]["name"] = "calculate"
        with self.assertRaisesRegex(ValueError, "differs from transcript"):
            evaluate("39", actions, messages)

    def test_reject_fabricated_read_response_even_if_both_logs_match(self):
        actions, messages, _ = self.read_only_trace()
        actions[0]["response"]["content"] = "invented tool output"
        messages[1]["content"] = "invented tool output"
        with self.assertRaisesRegex(ValueError, "response replay differs"):
            evaluate("39", actions, messages)

    def test_reject_final_live_hash_mismatch(self):
        actions, messages, _ = self.read_only_trace()
        with self.assertRaisesRegex(ValueError, "Live actor final DB"):
            evaluate("42", actions, messages, actor_final_db_hash="not-the-live-state")

    def test_reject_duplicated_call_ids(self):
        actions, messages, _ = self.read_only_trace()
        with self.assertRaisesRegex(ValueError, "unique"):
            evaluate("42", actions + deepcopy(actions), messages + deepcopy(messages))

    def test_reject_orphan_response(self):
        _, messages, _ = self.read_only_trace()
        with self.assertRaisesRegex(ValueError, "Orphan"):
            evaluate("42", [], [messages[1]])

    def test_unknown_task_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "one native task"):
            evaluate("does-not-exist", [], [])


if __name__ == "__main__":
    unittest.main()
