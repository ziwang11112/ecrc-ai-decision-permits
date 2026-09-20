"""Synthetic scope-adapter QA, not native benchmark episodes."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scope_gate import G, PREVIOUS_BUSINESS, ScopeGate, core_files, source_manifest


AT = 1715799600.0


def candidate(rid="eligible", insured=True):
    action = {"name": "cancel_reservation", "arguments": {"reservation_id": rid}}
    request = {"user_id": "customer", "cancellation": {
        "selector": {"kind": "ids", "ids": ["eligible", "ineligible"]}, "reason": "health"}}
    user = {"user_id": "customer", "reservations": ["eligible", "ineligible"]}
    reservation = {"reservation_id": rid, "user_id": "customer", "status": None,
                   "created_at": "2024-05-01T12:00:00", "cabin": "economy",
                   "insurance": "yes" if insured else "no",
                   "flights": [{"flight_number": "F1", "date": "2024-05-20"}],
                   "passengers": [{"first_name": "Example", "last_name": "Person"}]}
    display = {**deepcopy(action), "reservation_id": rid, "scope": "whole_reservation",
               "flights": deepcopy(reservation["flights"]), "passengers": deepcopy(reservation["passengers"])}
    basis, denial = PREVIOUS_BUSINESS.cancel_basis(reservation, ["available"], "health")
    context = {"request": request, "user": user, "reservation": reservation,
               "confirmation": {"user_id": "customer", "actions": [display]},
               "flight_statuses": ["available"],
               "eligibility": {"allowed": bool(basis), "basis": basis, "denial": denial}}
    return action, context


class ScopeGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.gate = ScopeGate(Path(self.directory.name) / "permits.sqlite")

    def authorize(self, rid="eligible", insured=True, **overrides):
        action, context = candidate(rid, insured)
        args = {"decision_id": "decision-" + rid, "action": action, "context": context, "at": AT}
        args.update(overrides)
        return self.gate.authorize_candidate(**args)

    def test_two_candidates_reach_core_with_only_one_armed_and_no_forged_completion(self):
        before = source_manifest()
        good = self.authorize()
        bad = self.authorize("ineligible", False)
        self.assertTrue(good["authorization"]["allowed"])
        self.gate.assert_action_binding(good["authorization"], good["input"]["action"])
        self.assertIn("cancellation_eligible", good["bodies"])
        self.assertNotIn("cancellation_eligible", bad["bodies"])
        self.assertEqual(len(good["input"]["evidence"]), 4)
        self.assertEqual(len(bad["input"]["evidence"]), 3)
        denied = bad["authorization"]
        self.assertFalse(denied["allowed"])
        self.assertFalse(denied["armed"])
        self.assertEqual(denied["permit"]["route"], "abstain")
        self.assertEqual(denied["permit"]["reason_code"], "no_claim_supported_by_used_evidence")
        self.assertEqual(denied["permit"]["permitted_claim_ids"], [])
        self.assertIn("cancel_booking", denied["permit"]["blocked_claim_ids"])
        self.assertEqual(denied["permit"]["excluded_evidence_ids"], [])
        state = self.gate.snapshot()
        self.assertEqual(len(state["requests"]), 2)
        self.assertEqual(len(state["permits"]), 2)
        self.assertEqual((state["n_jobs"], state["reserved"], state["committed"], state["n_receipts"]), (1, 1, 0, 0))
        self.assertEqual(before, source_manifest())

    def test_wrong_reservation_or_account_binding_fails_before_issuance(self):
        for field, value in (("reservation_id", "ineligible"), ("user_id", "other-user")):
            action, context = candidate()
            context["reservation"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "binding mismatch"):
                self.authorize(action=action, context=context)
        self.assertEqual(len(self.gate.snapshot()["requests"]), 0)

    def test_negative_body_cannot_be_relabelled_positive(self):
        action, context = candidate("ineligible", False)
        context["eligibility"] = {"allowed": True, "basis": "insured_covered_reason", "denial": None}
        with self.assertRaisesRegex(ValueError, "eligibility does not match"):
            self.authorize("ineligible", False, action=action, context=context)
        self.assertEqual(len(self.gate.snapshot()["requests"]), 0)

    def test_negative_candidate_is_not_rejected_by_wrapper_or_armable_by_boolean(self):
        result = self.authorize("ineligible", False)
        raw = self.gate.core.get_request("decision-ineligible")
        self.assertEqual(raw["state"], "nonaction")
        self.assertEqual(len(json.loads(raw["request_json"])["evidence"]["items"]), 3)
        auth = deepcopy(result["authorization"])
        auth.update(allowed=True, armed=True)
        with self.assertRaises(ValueError):
            self.gate.assert_action_binding(auth, result["input"]["action"])

    def test_changed_native_action_after_authorization_is_rejected(self):
        result = self.authorize()
        changed = deepcopy(result["input"]["action"])
        changed["arguments"]["reservation_id"] = "ineligible"
        with self.assertRaises(ValueError):
            self.gate.assert_action_binding(result["authorization"], changed)

    def test_confirmation_must_bind_exact_whole_reservation(self):
        action, context = candidate()
        context["confirmation"]["actions"][0]["passengers"] = []
        with self.assertRaisesRegex(ValueError, "confirmation scope"):
            self.authorize(action=action, context=context)
        self.assertEqual(len(self.gate.snapshot()["requests"]), 0)

    def test_request_must_actually_include_candidate(self):
        action, context = candidate()
        context["request"]["cancellation"]["selector"]["ids"] = ["ineligible"]
        with self.assertRaisesRegex(ValueError, "explicitly requested"):
            self.authorize(action=action, context=context)

    def test_extra_action_parameters_and_other_operations_are_rejected(self):
        action, context = candidate()
        action["arguments"]["amount"] = 100
        with self.assertRaisesRegex(ValueError, "exactly reservation_id"):
            self.authorize(action=action, context=context)
        action = {"name": "send_certificate", "arguments": {"user_id": "customer", "amount": 100}}
        with self.assertRaisesRegex(ValueError, "only cancel_reservation"):
            self.authorize(action=action, context=context)

    def test_body_hashes_and_timestamp_are_traceable_without_metadata_mutation(self):
        result = self.authorize()
        for record in result["input"]["evidence"]:
            self.assertEqual(record["body_hash"], G.canonical_hash(result["bodies"][record["type"]]))
            self.assertEqual((record["observed_at"], record["available_at"]), (AT, AT))
        self.assertTrue(all(Path(path).is_file() for path in core_files()))

    def test_repeated_same_candidate_does_not_issue_another_unit(self):
        first = self.authorize()
        self.assertEqual(first, self.authorize())
        state = self.gate.snapshot()
        self.assertEqual((state["n_jobs"], state["reserved"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
