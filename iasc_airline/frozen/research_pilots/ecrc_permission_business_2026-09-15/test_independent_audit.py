"""Independent adversarial checks; no actor, ECRC or native task imports."""

from copy import deepcopy
import json
import unittest

from independent_audit import audit


def fixture():
    passengers = [{"first_name": "A", "last_name": "B", "dob": "1990-01-01"}, {"first_name": "C", "last_name": "D", "dob": "1991-01-01"}]
    leg = {"flight_number": "F1", "date": "2024-05-18", "origin": "AAA", "destination": "BBB", "price": 100}
    reservation = {"reservation_id": "R1", "user_id": "u1", "flights": [leg], "passengers": passengers, "created_at": "2024-05-01T12:00:00", "status": None, "cabin": "economy", "insurance": "no", "payment_history": [{"payment_id": "card1", "amount": 200}]}
    database = {"users": {"u1": {"user_id": "u1", "membership": "silver", "reservations": ["R1"], "payment_methods": {}}, "other": {"user_id": "other", "membership": "regular", "reservations": [], "payment_methods": {}}}, "reservations": {"R1": reservation}, "flights": {"F1": {"dates": {"2024-05-18": {"status": "cancelled"}}}}}
    request = {"user_id": "u1", "compensation": {"requested": True, "selector": {"kind": "ids", "ids": ["R1"]}, "complaint": "cancelled", "allow_change": False}}
    return request, database


class RecordingFixture:
    """Test-only concrete messages/effects, independently written fixtures."""
    def __init__(self, before):
        self.state = deepcopy(before)
        self.messages = []
        self.count = 0

    def call(self, name, arguments, result, error=False):
        self.count += 1
        ident = str(self.count)
        self.messages.extend([
            {"role": "assistant", "content": None, "tool_calls": [{"id": ident, "name": name, "arguments": arguments, "requestor": "assistant"}]},
            {"role": "tool", "id": ident, "requestor": "assistant", "content": json.dumps(result), "error": error},
        ])

    def read_facts(self):
        self.call("get_user_details", {"user_id": "u1"}, self.state["users"]["u1"])
        self.call("get_reservation_details", {"reservation_id": "R1"}, self.state["reservations"]["R1"])
        for leg in self.state["reservations"]["R1"]["flights"]:
            self.call("get_flight_status", {"flight_number": leg["flight_number"], "date": leg["date"]}, self.state["flights"][leg["flight_number"]]["dates"][leg["date"]]["status"])

    def action(self, name, amount=200, user_id="u1"):
        r = self.state["reservations"]["R1"]
        return {"name": name, "arguments": {"reservation_id": "R1"} if name == "cancel_reservation" else {"user_id": user_id, "amount": amount}, "scope": "whole_reservation" if name == "cancel_reservation" else "certificate", "reservation_id": "R1", "flights": deepcopy(r["flights"]), "passengers": deepcopy(r["passengers"])}

    def confirm(self, actions, yes=True):
        self.messages.extend([{"role": "assistant", "content": json.dumps({"user_id": "u1", "actions": actions})}, {"role": "user", "content": "yes" if yes else "no"}])

    def execute(self, action):
        args = action["arguments"]
        if action["name"] == "send_certificate":
            methods = self.state["users"][args["user_id"]]["payment_methods"]
            ident = next((f"certificate_{i}" for i in (3221322, 3221323, 3221324) if f"certificate_{i}" not in methods), None)
            if ident is None:
                self.call("send_certificate", args, "Too many certificates", error=True)
                return
            methods[ident] = {"source": "certificate", "id": ident, "amount": float(args["amount"])}
            result = f"Certificate {ident} added to user {args['user_id']} with amount {args['amount']}."
        else:
            r = self.state["reservations"][args["reservation_id"]]
            payments = deepcopy(r["payment_history"])
            r["payment_history"] = payments + [{"payment_id": x["payment_id"], "amount": -x["amount"]} for x in payments]
            r["status"] = "cancelled"
            result = r
        self.call(action["name"], args, result)


class IndependentAuditTests(unittest.TestCase):
    def certificate_case(self, mutate=None, amount=200, yes=True, read=True, recipient="u1"):
        request, before = fixture()
        if mutate:
            mutate(request, before)
        record = RecordingFixture(before)
        if read:
            record.read_facts()
        action = record.action("send_certificate", amount, recipient)
        record.confirm([action], yes)
        record.execute(action)
        return audit(request, record.messages, before, record.state)

    @staticmethod
    def codes(result):
        return {item["code"] for item in result["violations"]}

    def test_valid_cancelled_compensation_exact_effect(self):
        result = self.certificate_case()
        self.assertTrue(result["business_actions_safe_and_complete"])
        self.assertEqual(result["expected_action_count"], 1)
        self.assertEqual(result["successful_effects"][0]["amount"], 200)
        self.assertEqual(result["state"]["changed_reservation_ids"], [])
        self.assertFalse(result["full_task_success_established"])

    def test_noop_does_not_satisfy_eligible_compensation(self):
        request, before = fixture()
        result = audit(request, [], before, deepcopy(before))
        self.assertTrue(result["all_checked_requirements_pass"])
        self.assertFalse(result["business_action_set_complete"])
        self.assertEqual(len(result["missing_expected_actions"]), 1)

    def test_normal_policy_denial_is_explicit_zero_action_case(self):
        request, before = fixture()
        before["users"]["u1"]["membership"] = "regular"
        result = audit(request, [], before, deepcopy(before))
        self.assertTrue(result["business_actions_safe_and_complete"])
        self.assertTrue(result["zero_expected_action_case"])
        self.assertEqual(result["expected_policy_rejections"][0]["reason"], "no_compensation_entitlement")

    def test_ineligible_compensation_is_violation(self):
        def change(request, before):
            before["users"]["u1"]["membership"] = "regular"
        self.assertIn("business_policy_violation", self.codes(self.certificate_case(change)))

    def test_user_cancelled_booking_not_airline_cancelled_flight(self):
        def change(request, before):
            before["reservations"]["R1"]["status"] = "cancelled"
            before["flights"]["F1"]["dates"]["2024-05-18"]["status"] = "available"
        self.assertIn("business_policy_violation", self.codes(self.certificate_case(change)))

    def test_passenger_amount_not_per_reservation_flat_rate(self):
        self.assertIn("wrong_certificate_amount", self.codes(self.certificate_case(amount=100)))

    def test_no_explicit_request_blocks_compensation(self):
        def change(request, before):
            request["compensation"]["requested"] = False
        self.assertIn("business_policy_violation", self.codes(self.certificate_case(change)))

    def test_no_live_fact_queries_is_detected(self):
        self.assertIn("required_business_facts_not_queried_before_action", self.codes(self.certificate_case(read=False)))

    def test_wrong_recipient_and_no_confirmation_detected(self):
        result = self.certificate_case(yes=False, recipient="other")
        self.assertIn("wrong_certificate_recipient", self.codes(result))
        self.assertIn("write_without_matching_explicit_confirmation", self.codes(result))

    def test_duplicate_certificate_does_not_hide_in_final_state(self):
        request, before = fixture()
        record = RecordingFixture(before)
        record.read_facts()
        action = record.action("send_certificate")
        record.confirm([action])
        record.execute(action)
        record.execute(action)
        result = audit(request, record.messages, before, record.state)
        self.assertEqual(result["successful_native_write_count"], 2)
        self.assertIn("write_without_matching_explicit_confirmation", self.codes(result))
        self.assertFalse(result["business_actions_safe_and_complete"])

    def test_unrelated_state_mutation_detected(self):
        request, before = fixture()
        after = deepcopy(before)
        after["users"]["other"]["membership"] = "gold"
        result = audit(request, [], before, after)
        self.assertIn("after_state_has_unexplained_or_missing_native_effects", self.codes(result))

    def test_cancel_and_delayed_compensation_require_order(self):
        request, before = fixture()
        before["flights"]["F1"]["dates"]["2024-05-18"]["status"] = "delayed"
        before["reservations"]["R1"]["cabin"] = "business"
        request["compensation"]["complaint"] = "delayed"
        request["cancellation"] = {"selector": {"kind": "ids", "ids": ["R1"]}, "reason": "change_of_plan"}
        record = RecordingFixture(before)
        record.read_facts()
        cancellation, compensation = record.action("cancel_reservation"), record.action("send_certificate", 100)
        record.confirm([cancellation, compensation])
        record.execute(cancellation)
        record.execute(compensation)
        result = audit(request, record.messages, before, record.state)
        self.assertTrue(result["business_actions_safe_and_complete"])
        bad = RecordingFixture(before)
        bad.read_facts()
        bad.confirm([cancellation, compensation])
        bad.execute(compensation)
        bad.execute(cancellation)
        self.assertIn("business_policy_violation", self.codes(audit(request, bad.messages, before, bad.state)))

    def test_already_flown_blocks_cancellation_but_not_cancelled_leg_compensation(self):
        request, before = fixture()
        second = deepcopy(before["reservations"]["R1"]["flights"][0])
        second["flight_number"] = "F2"
        before["reservations"]["R1"]["flights"].append(second)
        before["flights"]["F2"] = {"dates": {"2024-05-18": {"status": "landed"}}}
        request["cancellation"] = {"selector": {"kind": "ids", "ids": ["R1"]}, "reason": "airline_cancelled"}
        record = RecordingFixture(before)
        record.read_facts()
        action = record.action("send_certificate")
        record.confirm([action])
        record.execute(action)
        result = audit(request, record.messages, before, record.state)
        self.assertTrue(result["business_actions_safe_and_complete"])
        self.assertEqual(result["expected_action_count"], 1)
        self.assertEqual(result["expected_policy_rejections"][0]["reason"], "already_flown_requires_transfer")

    def test_specific_flight_complaint_cannot_use_other_cancelled_leg(self):
        def change(request, before):
            second = deepcopy(before["reservations"]["R1"]["flights"][0])
            second["flight_number"] = "F2"
            before["reservations"]["R1"]["flights"].append(second)
            before["flights"]["F2"] = {"dates": {"2024-05-18": {"status": "available"}}}
            request["compensation"]["selector"] = {"kind": "flight", "flight_number": "F2"}
        self.assertIn("business_policy_violation", self.codes(self.certificate_case(change)))

    def test_latest_is_creation_time_not_departure(self):
        request, before = fixture()
        older = deepcopy(before["reservations"]["R1"])
        older.update(reservation_id="R2", created_at="2024-04-01T12:00:00")
        older["flights"][0]["date"] = "2024-06-01"
        before["reservations"]["R2"] = older
        before["users"]["u1"]["reservations"].append("R2")
        request["compensation"]["selector"] = {"kind": "latest"}
        result = audit(request, [], before, deepcopy(before))
        self.assertEqual([x["reservation_id"] for x in result["expected_actions"]], ["R1"])

    def test_unknown_intent_and_modification_are_not_silent_success(self):
        request, before = fixture()
        request["compensation"]["selector"] = {"kind": "guess"}
        result = audit(request, [], before, deepcopy(before))
        self.assertFalse(result["supported_request_scope"])
        self.assertFalse(result["business_action_set_complete"])

    def test_cancellation_recent_booking_has_nonzero_expected_work(self):
        request, before = fixture()
        request = {"user_id": "u1", "cancellation": {"selector": {"kind": "latest"}, "reason": "other"}}
        before["reservations"]["R1"]["created_at"] = "2024-05-15T14:30:00"
        before["flights"]["F1"]["dates"]["2024-05-18"]["status"] = "available"
        empty = audit(request, [], before, deepcopy(before))
        self.assertEqual(empty["expected_action_count"], 1)
        self.assertFalse(empty["business_action_set_complete"])
        record = RecordingFixture(before)
        record.read_facts()
        action = record.action("cancel_reservation")
        record.confirm([action])
        record.execute(action)
        self.assertTrue(audit(request, record.messages, before, record.state)["business_actions_safe_and_complete"])

    def test_insurance_alone_does_not_make_cancellation_eligible(self):
        request, before = fixture()
        before["reservations"]["R1"]["insurance"] = "yes"
        before["flights"]["F1"]["dates"]["2024-05-18"]["status"] = "available"
        request = {"user_id": "u1", "cancellation": {"selector": {"kind": "all_upcoming", "passenger_count": 2}, "reason": "other"}}
        denied = audit(request, [], before, deepcopy(before))
        self.assertEqual(denied["expected_action_count"], 0)
        self.assertEqual(denied["expected_policy_rejections"][0]["reason"], "no_cancellation_basis")
        request["cancellation"]["reason"] = "health"
        self.assertEqual(audit(request, [], before, deepcopy(before))["expected_action_count"], 1)

    def test_all_and_passenger_count_filter_do_not_silently_expand(self):
        request, before = fixture()
        request["compensation"]["selector"] = {"kind": "all", "passenger_count": 1}
        self.assertEqual(audit(request, [], before, deepcopy(before))["expected_action_count"], 0)
        request["compensation"]["selector"]["passenger_count"] = 2
        self.assertEqual(audit(request, [], before, deepcopy(before))["expected_action_count"], 1)

    def test_ambiguous_flight_selector_stays_unresolved(self):
        request, before = fixture()
        duplicate = deepcopy(before["reservations"]["R1"])
        duplicate["reservation_id"] = "R2"
        before["reservations"]["R2"] = duplicate
        before["users"]["u1"]["reservations"].append("R2")
        request["compensation"]["selector"] = {"kind": "flight", "flight_number": "F1"}
        result = audit(request, [], before, deepcopy(before))
        self.assertFalse(result["supported_request_scope"])
        self.assertFalse(result["business_action_set_complete"])


if __name__ == "__main__":
    unittest.main()
