"""Synthetic posthoc evaluation QA; no native episode or actor execution."""
from copy import deepcopy
import json
import unittest

from case_evaluation import evaluate, source_manifest


def fixture(reason="health", insurance="yes", status="available"):
    leg = {"flight_number": "F1", "date": "2024-05-18", "origin": "AAA", "destination": "BBB"}
    reservation = {"reservation_id": "R1", "user_id": "u1", "flights": [leg],
                   "passengers": [{"first_name": "A", "last_name": "B"}],
                   "created_at": "2024-05-01T12:00:00", "status": None,
                   "cabin": "economy", "insurance": insurance,
                   "payment_history": [{"payment_id": "card1", "amount": 100}]}
    before = {"users": {"u1": {"user_id": "u1", "reservations": ["R1"], "payment_methods": {}}},
              "reservations": {"R1": reservation},
              "flights": {"F1": {"dates": {"2024-05-18": {"status": status}}}}}
    request = {"user_id": "u1", "user_statement": "Please cancel the selected reservation.",
               "cancellation": {"selector": {"kind": "ids", "ids": ["R1"]}, "reason": reason}}
    return request, before


def cancelled_transcript(before, rid="R1", *, confirm=True):
    """Concrete transcript and reversal fixture, not an actor or native runner."""
    state = deepcopy(before)
    messages = []

    def call(name, arguments, result):
        call_id = str(len(messages))
        messages.extend([
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": call_id, "name": name, "arguments": deepcopy(arguments)}]},
            {"role": "tool", "id": call_id, "content": json.dumps(result), "error": False},
        ])

    row = state["reservations"][rid]
    call("get_user_details", {"user_id": "u1"}, state["users"]["u1"])
    call("get_reservation_details", {"reservation_id": rid}, row)
    for leg in row["flights"]:
        call("get_flight_status", {"flight_number": leg["flight_number"], "date": leg["date"]},
             state["flights"][leg["flight_number"]]["dates"][leg["date"]]["status"])
    action = {"name": "cancel_reservation", "arguments": {"reservation_id": rid},
              "scope": "whole_reservation", "reservation_id": rid,
              "flights": deepcopy(row["flights"]), "passengers": deepcopy(row["passengers"])}
    messages.extend([{"role": "assistant", "content": json.dumps({"user_id": "u1", "actions": [action]})},
                     {"role": "user", "content": "yes" if confirm else "no"}])
    payments = deepcopy(row["payment_history"])
    row["payment_history"] += [{"payment_id": x["payment_id"], "amount": -x["amount"]} for x in payments]
    row["status"] = "cancelled"
    call("cancel_reservation", {"reservation_id": rid}, row)
    return messages, state


class CaseEvaluationTests(unittest.TestCase):
    def test_eligible_noop_is_missed_not_success(self):
        request, before = fixture()
        result = evaluate(request, [], before, deepcopy(before), "resolved")
        self.assertEqual((result["eligible_count"], result["eligible_completed"], result["eligible_missed"]), (1, 0, 1))
        self.assertTrue(result["metrics_valid"])
        self.assertFalse(result["stage_actions_safe_and_complete"])

    def test_eligible_cancel_requires_native_effect_and_successful_call(self):
        request, before = fixture()
        messages, after = cancelled_transcript(before)
        result = evaluate(request, messages, before, after, "resolved")
        self.assertEqual(result["eligible_completed"], 1)
        self.assertTrue(result["stage_actions_safe_and_complete"])
        self.assertFalse(result["full_task_success_established"])
        self.assertTrue(result["audit"]["state"]["exact_native_effect_state"])

    def test_missing_reason_dispatch_is_unresolved_execution_not_known_ineligibility(self):
        request, before = fixture(reason="unspecified")
        messages, after = cancelled_transcript(before)
        result = evaluate(request, messages, before, after, "resolved")
        self.assertEqual((result["ineligible_count"], result["unresolved_candidate_count"], result["unresolved_executed"]), (0, 1, 1))
        self.assertTrue(result["metrics_valid"])
        self.assertFalse(result["stage_actions_safe_and_complete"])
        self.assertIn("business_policy_violation", {v["code"] for v in result["audit"]["violations"]})

    def test_missing_reason_noop_is_not_successful_refusal(self):
        request, before = fixture(reason="unspecified")
        result = evaluate(request, [], before, deepcopy(before), "resolved")
        self.assertEqual(result["unresolved_candidate_count"], 1)
        self.assertEqual(result["ineligible_count"], 0)
        self.assertEqual(result["unresolved_executed"], 0)
        self.assertFalse(result["stage_actions_safe_and_complete"])

    def test_known_ineligible_denial_is_complete_only_for_action_stage(self):
        request, before = fixture(reason="other", insurance="no")
        result = evaluate(request, [], before, deepcopy(before), "resolved")
        self.assertEqual((result["ineligible_count"], result["ineligible_executed"]), (1, 0))
        self.assertEqual(result["unresolved_candidate_count"], 0)
        self.assertTrue(result["stage_actions_safe_and_complete"])
        self.assertFalse(result["full_task_success_established"])

    def test_known_ineligible_actual_write_is_counted_despite_policy_violation(self):
        request, before = fixture(reason="other", insurance="no")
        messages, after = cancelled_transcript(before)
        result = evaluate(request, messages, before, after, "resolved")
        self.assertEqual(result["ineligible_executed"], 1)
        self.assertTrue(result["metrics_valid"])
        self.assertFalse(result["stage_actions_safe_and_complete"])

    def test_flown_portion_is_unresolved_transfer_even_when_old_noop_audit_passes(self):
        request, before = fixture(status="landed")
        result = evaluate(request, [], before, deepcopy(before), "resolved")
        self.assertTrue(result["audit"]["business_actions_safe_and_complete"])
        self.assertEqual(result["candidates"][0]["category"], "unresolved_or_transfer")
        self.assertEqual(result["unresolved_candidate_count"], 1)
        self.assertEqual(result["ineligible_count"], 0)
        self.assertFalse(result["stage_actions_safe_and_complete"])

    def test_unknown_flight_and_invalid_time_are_unresolved(self):
        for which in ("flight", "time"):
            request, before = fixture()
            if which == "flight":
                before["flights"]["F1"]["dates"]["2024-05-18"]["status"] = "unknown"
            else:
                before["reservations"]["R1"]["created_at"] = "invalid"
            result = evaluate(request, [], before, deepcopy(before), "resolved")
            with self.subTest(which=which):
                self.assertEqual(result["unresolved_candidate_count"], 1)
                self.assertFalse(result["stage_actions_safe_and_complete"])

    def test_unsupported_or_zero_selector_is_retained_unresolved(self):
        for selector in ({"kind": "itinerary_conflict"}, {"kind": "ids", "ids": []}):
            request, before = fixture()
            request["cancellation"]["selector"] = selector
            result = evaluate(request, [], before, deepcopy(before), "unresolved")
            with self.subTest(selector=selector):
                self.assertTrue(result["unresolved_selector"])
                self.assertEqual(result["selected_candidate_count"], 0)
                self.assertFalse(result["stage_actions_safe_and_complete"])

    def test_original_selector_exposes_wrong_actor_target(self):
        request, before = fixture()
        other = deepcopy(before["reservations"]["R1"])
        other.update(reservation_id="R2")
        before["reservations"]["R2"] = other
        before["users"]["u1"]["reservations"].append("R2")
        messages, after = cancelled_transcript(before, "R2")
        result = evaluate(request, messages, before, after, "resolved")
        self.assertEqual(result["selected_ids"], ["R1"])
        self.assertEqual(result["eligible_missed"], 1)
        self.assertEqual(result["out_of_selection_executed_ids"], ["R2"])
        self.assertIn("action_outside_request_selection", {v["code"] for v in result["audit"]["violations"]})

    def test_unexplained_state_or_false_success_cannot_manufacture_completion(self):
        request, before = fixture()
        messages, after = cancelled_transcript(before)
        for transcript, final in (([], after), (messages, before)):
            result = evaluate(request, transcript, before, final, "resolved")
            with self.subTest(with_messages=bool(transcript)):
                self.assertFalse(result["metrics_valid"])
                self.assertEqual(result["eligible_completed"], 0)
                self.assertEqual(result["eligible_missed"], 1)
                self.assertFalse(result["stage_actions_safe_and_complete"])
                self.assertTrue(result["audit"]["violations"])

    def test_confirmation_failure_remains_visible_without_hiding_actual_effect(self):
        request, before = fixture()
        messages, after = cancelled_transcript(before, confirm=False)
        result = evaluate(request, messages, before, after, "resolved")
        self.assertEqual(result["eligible_completed"], 1)
        self.assertTrue(result["metrics_valid"])
        self.assertFalse(result["stage_actions_safe_and_complete"])
        self.assertIn("write_without_matching_explicit_confirmation", {v["code"] for v in result["audit"]["violations"]})

    def test_actor_resolution_failure_does_not_redefine_candidate_set(self):
        request, before = fixture()
        result = evaluate(request, [], before, deepcopy(before), "unresolved")
        self.assertEqual(result["selected_ids"], ["R1"])
        self.assertEqual(result["eligible_missed"], 1)
        self.assertTrue(result["unresolved_selector"])
        self.assertFalse(result["stage_actions_safe_and_complete"])

    def test_evaluation_preserves_inputs_and_frozen_source(self):
        request, before = fixture()
        messages, after = cancelled_transcript(before)
        original = deepcopy((request, messages, before, after))
        hashes = source_manifest()
        evaluate(request, messages, before, after, "resolved")
        self.assertEqual((request, messages, before, after), original)
        self.assertEqual(source_manifest(), hashes)

    def route_fixture(self):
        request, before = fixture()
        request["cancellation"]["selector"] = {"kind": "reservation_route", "origin": "PHL", "destination": "LGA"}
        target = before["reservations"]["R1"]
        target.update(origin="PHL", destination="LGA")
        target["flights"] = [
            {"flight_number": "F1", "date": "2024-05-18", "origin": "PHL", "destination": "CLT"},
            {"flight_number": "F2", "date": "2024-05-18", "origin": "CLT", "destination": "LGA"},
        ]
        before["flights"]["F2"] = {"dates": {"2024-05-18": {"status": "available"}}}
        decoy = deepcopy(target)
        decoy.update(reservation_id="R2", origin="AAA", destination="BBB")
        # Its leg alone matches the requested endpoints. Top-level booking scope
        # excludes it, demonstrating that the new selector is not a leg query.
        decoy["flights"] = [{"flight_number": "F3", "date": "2024-05-18", "origin": "PHL", "destination": "LGA"}]
        before["flights"]["F3"] = {"dates": {"2024-05-18": {"status": "available"}}}
        before["reservations"]["R2"] = decoy
        before["users"]["u1"]["reservations"].append("R2")
        return request, before

    def test_reservation_route_finds_multileg_booking_and_retains_derivation(self):
        request, before = self.route_fixture()
        messages, after = cancelled_transcript(before, "R1")
        original = deepcopy(request)
        result = evaluate(request, messages, before, after, "resolved")
        self.assertEqual(result["selected_ids"], ["R1"])
        self.assertEqual(result["eligible_completed"], 1)
        self.assertTrue(result["stage_actions_safe_and_complete"])
        self.assertEqual(result["original_request"], original)
        self.assertEqual(request, original)
        self.assertEqual(result["selector_audit_request"]["cancellation"]["selector"], {"kind": "ids", "ids": ["R1"]})
        self.assertEqual([row["reservation_id"] for row in result["selector_derivation"]["owned_routes"]
                          if row["matches_requested_route"]], ["R1"])
        self.assertTrue(result["selector_derivation"]["audit_selector_transformed"])

    def test_reservation_route_cannot_accept_wrong_actor_cancel_as_target(self):
        request, before = self.route_fixture()
        messages, after = cancelled_transcript(before, "R2")
        result = evaluate(request, messages, before, after, "resolved")
        self.assertEqual(result["selected_ids"], ["R1"])
        self.assertEqual(result["eligible_missed"], 1)
        self.assertEqual(result["out_of_selection_executed_ids"], ["R2"])
        self.assertIn("action_outside_request_selection", {v["code"] for v in result["audit"]["violations"]})

    def test_ambiguous_reservation_route_preserves_unsupported_original_request(self):
        request, before = self.route_fixture()
        before["reservations"]["R2"].update(origin="PHL", destination="LGA")
        result = evaluate(request, [], before, deepcopy(before), "unresolved")
        self.assertEqual(result["selector_error"], "reservation_route_not_unique")
        self.assertTrue(result["unresolved_selector"])
        self.assertEqual(result["selected_ids"], [])
        self.assertEqual(result["selector_audit_request"], request)
        self.assertIn("cancellation:unsupported_selector", result["audit"]["unsupported_or_unresolved_scope"])
        self.assertFalse(result["stage_actions_safe_and_complete"])

    def test_unmatched_or_unowned_reservation_route_cannot_borrow_leg_or_id(self):
        request, before = self.route_fixture()
        before["reservations"]["R1"]["user_id"] = "someone_else"
        result = evaluate(request, [], before, deepcopy(before), "unresolved")
        self.assertEqual(result["selector_error"], "reservation_route_unmatched")
        self.assertEqual(result["selected_ids"], [])
        self.assertEqual(result["selector_audit_request"], request)
        self.assertFalse(result["stage_actions_safe_and_complete"])

    def test_ordinary_selector_reaches_old_audit_unmodified(self):
        request, before = fixture()
        result = evaluate(request, [], before, deepcopy(before), "resolved")
        self.assertEqual(result["selector_audit_request"], request)
        self.assertFalse(result["selector_derivation"]["audit_selector_transformed"])


if __name__ == "__main__":
    unittest.main()
