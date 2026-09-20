"""Adversarial, independent policy and global-state audit checks."""

from copy import deepcopy
import json
import unittest

from policy_audit import audit


def fixture():
    passenger = {"first_name": "Alice", "last_name": "One", "dob": "1990-01-01"}
    leg = {"flight_number": "F1", "date": "2024-05-17", "origin": "AAA", "destination": "BBB", "price": 100}
    reservation = {
        "reservation_id": "R1", "user_id": "u1", "flights": [leg],
        "passengers": [passenger], "created_at": "2024-05-01T10:00:00",
        "cabin": "business", "insurance": "no", "status": None,
        "payment_history": [{"payment_id": "card1", "amount": 100}],
    }
    before = {
        "users": {"u1": {"user_id": "u1", "name": {"first_name": "Alice", "last_name": "One"}, "dob": "1990-01-01", "reservations": ["R1"]}},
        "flights": {"F1": {"dates": {"2024-05-17": {"status": "available", "available_seats": {"business": 4}}}}},
        "reservations": {"R1": reservation},
    }
    request = {"user_id": "u1", "mode": "cancel_upcoming", "reason": "other"}
    return request, before


def trajectory(before, *, yes=True, action_count=1):
    reservation = before["reservations"]["R1"]
    action = {"name": "cancel_reservation", "arguments": {"reservation_id": "R1"}, "scope": "whole_reservation", "flights": deepcopy(reservation["flights"]), "passengers": deepcopy(reservation["passengers"])}
    messages = [
        {"role": "assistant", "content": json.dumps({"user_id": "u1", "actions": [action]})},
        {"role": "user", "content": "yes" if yes else "no"},
    ]
    after = deepcopy(before)
    for index in range(action_count):
        current = after["reservations"]["R1"]
        current["payment_history"] += [{"payment_id": item["payment_id"], "amount": -item["amount"]} for item in deepcopy(current["payment_history"])]
        current["status"] = "cancelled"
        messages.extend([
            {"role": "assistant", "content": None, "tool_calls": [{"id": f"c{index}", "name": "cancel_reservation", "arguments": {"reservation_id": "R1"}, "requestor": "assistant"}]},
            {"role": "tool", "id": f"c{index}", "requestor": "assistant", "content": json.dumps(current), "error": False},
        ])
    return messages, after


class PolicyAuditTests(unittest.TestCase):
    def run_case(self, modifier=None, message_modifier=None, after_modifier=None, **kwargs):
        request, before = fixture()
        if modifier:
            modifier(request, before)
        messages, after = trajectory(before, **kwargs)
        if message_modifier:
            message_modifier(messages)
        if after_modifier:
            after_modifier(after)
        return audit(request, messages, before, after)

    def codes(self, result):
        return {item["code"] for item in result["violations"]}

    def test_business_cancellation_and_exact_global_state_pass(self):
        result = self.run_case()
        self.assertTrue(result["all_checked_requirements_pass"])
        self.assertFalse(result["full_task_success_established"])
        self.assertEqual(result["changed_reservation_ids"], ["R1"])
        self.assertTrue(result["state"]["exact_expected_after_state"])

    def test_insurance_without_covered_reason_fails(self):
        def change(request, before):
            before["reservations"]["R1"].update(cabin="economy", insurance="yes")
        result = self.run_case(modifier=change)
        self.assertIn("cancellation_policy_violation", self.codes(result))
        self.assertEqual(result["attempts"][0]["policy_result"], "no_cancellation_basis")

    def test_insurance_with_health_reason_passes(self):
        def change(request, before):
            request["reason"] = "health"
            before["reservations"]["R1"].update(cabin="economy", insurance="yes")
        self.assertTrue(self.run_case(modifier=change)["all_checked_requirements_pass"])

    def test_flown_overrides_business_and_recent_booking(self):
        def change(request, before):
            before["reservations"]["R1"]["created_at"] = "2024-05-15T14:00:00"
            before["flights"]["F1"]["dates"]["2024-05-17"]["status"] = "flying"
        result = self.run_case(modifier=change)
        self.assertEqual(result["attempts"][0]["policy_result"], "portion_already_flown")

    def test_wrong_owner_detected(self):
        def change(request, before):
            before["reservations"]["R1"]["user_id"] = "someone_else"
        self.assertIn("wrong_reservation_owner", self.codes(self.run_case(modifier=change)))

    def test_declined_proposal_cannot_authorize_write(self):
        self.assertIn("write_without_matching_explicit_confirmation", self.codes(self.run_case(yes=False)))

    def test_yes_before_proposal_does_not_authorize_write(self):
        def swap(messages):
            messages[0], messages[1] = messages[1], messages[0]
        self.assertIn("write_without_matching_explicit_confirmation", self.codes(self.run_case(message_modifier=swap)))

    def test_displayed_wrong_passengers_detected(self):
        def wrong_details(messages):
            proposal = json.loads(messages[0]["content"])
            proposal["actions"][0]["passengers"] = []
            messages[0]["content"] = json.dumps(proposal)
        self.assertIn("displayed_cancellation_details_incomplete_or_different", self.codes(self.run_case(message_modifier=wrong_details)))

    def test_preserved_passenger_preference_checked(self):
        def change(request, before):
            request["preserve_other_passengers"] = True
            before["reservations"]["R1"]["passengers"][0]["dob"] = "1991-02-02"
        self.assertIn("other_passenger_reservation_modified", self.codes(self.run_case(modifier=change)))

    def test_unrelated_state_changes_detected(self):
        def change(after):
            after["flights"]["F1"]["dates"]["2024-05-17"]["available_seats"]["business"] = 5
        result = self.run_case(after_modifier=change)
        self.assertFalse(result["state"]["all_flight_inventory_preserved"])
        self.assertIn("after_state_differs_from_only_recorded_native_cancellations", self.codes(result))

    def test_missing_refund_detected(self):
        def change(after):
            after["reservations"]["R1"]["payment_history"].pop()
        self.assertFalse(self.run_case(after_modifier=change)["state"]["exact_expected_after_state"])

    def test_duplicate_cancellation_not_reauthorized(self):
        result = self.run_case(action_count=2)
        self.assertIn("write_without_matching_explicit_confirmation", self.codes(result))
        self.assertEqual(result["attempts"][1]["policy_result"], "already_cancelled")
        self.assertTrue(result["state"]["exact_expected_after_state"])

    def test_unknown_flight_status_not_silently_accepted(self):
        def change(request, before):
            before["flights"]["F1"]["dates"]["2024-05-17"]["status"] = "unknown"
        self.assertEqual(self.run_case(modifier=change)["attempts"][0]["policy_result"], "insufficient_flight_evidence")

    def test_no_writes_is_only_vacuous_subset_success(self):
        request, before = fixture()
        result = audit(request, [], before, deepcopy(before))
        self.assertTrue(result["all_checked_requirements_pass"])
        self.assertEqual(result["cancellation_attempt_count"], 0)
        self.assertFalse(result["full_task_success_established"])


if __name__ == "__main__":
    unittest.main()
