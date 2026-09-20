"""Pure controls of the new metadata adapter with unchanged paper ECRC sources."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from ecrc_adapter import EVIDENCE_SOURCES, G, PermissionGate, SOURCE_FILES, core_files, source_manifest


AT = datetime(2026, 9, 15, 12, tzinfo=timezone.utc).timestamp()


def evidence():
    return [{"id": "e-" + kind, "type": kind, "source": source,
             "observed_at": AT - 1, "available_at": AT - 1,
             "body_hash": hashlib.sha256(kind.encode()).hexdigest()}
            for kind, source in EVIDENCE_SOURCES.items()]


class PermissionGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.gate = PermissionGate(Path(self.directory.name) / "permit.sqlite")
        self.action = {"name": "send_certificate", "arguments": {"user_id": "u1", "amount": 100}}

    def run_gate(self, records=None, **overrides):
        args = {"decision_id": "case-1", "action": self.action,
                "evidence": evidence() if records is None else records,
                "at": AT, "requested_claim": "issue_compensation"}
        args.update(overrides)
        return self.gate.authorize(**args)

    def assert_nonaction(self, result):
        self.assertFalse(result["allowed"])
        self.assertFalse(result["armed"])
        self.assertEqual(self.gate.snapshot()["n_jobs"], 0)
        self.assertEqual(self.gate.snapshot()["reserved"], 0)

    def test_good_typed_evidence_issues_and_arms_but_never_fakes_receipt(self):
        result = self.run_gate()
        self.assertTrue(result["allowed"])
        self.assertEqual(result["permit"]["permitted_claim_ids"], ["issue_compensation"])
        self.assertEqual(result["permit"]["route"], "alert")
        self.assertEqual(result["permit"]["expires_at"], "2026-09-15T13:00:00.000000Z")
        self.gate.assert_action_binding(result, self.action)
        state = self.gate.snapshot()
        self.assertEqual((state["reserved"], state["committed"], state["n_receipts"]), (1, 0, 0))

    def test_cancel_claim_is_separate_from_compensation(self):
        action = {"name": "cancel_reservation", "arguments": {"reservation_id": "r1"}}
        result = self.run_gate(action=action, requested_claim="cancel_booking")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["permit"]["permitted_claim_ids"], ["cancel_booking"])
        self.assertIn("issue_compensation", result["permit"]["blocked_claim_ids"])

    def test_missing_policy_eligibility_recomputes_claim_then_releases(self):
        result = self.run_gate([row for row in evidence() if row["type"] != "policy_eligibility"])
        self.assert_nonaction(result)
        self.assertEqual(result["permit"]["reason_code"], "no_claim_supported_by_used_evidence")
        self.assertEqual(result["permit"]["permitted_claim_ids"], [])

    def test_stale_reservation_evidence_excluded(self):
        records = evidence()
        row = next(row for row in records if row["type"] == "reservation_record")
        row["observed_at"] = AT - 301
        result = self.run_gate(records)
        self.assert_nonaction(result)
        self.assertIn(row["id"], result["permit"]["excluded_evidence_ids"])

    def test_age_boundary_300_seconds_is_accepted(self):
        records = evidence()
        for row in records:
            row["observed_at"] = AT - 300
        self.assertTrue(self.run_gate(records)["allowed"])

    def test_source_is_bound_to_evidence_type(self):
        records = evidence()
        records[0]["source"] = "native_airline"
        result = self.run_gate(records)
        self.assert_nonaction(result)
        self.assertIn(records[0]["id"], result["permit"]["excluded_evidence_ids"])

    def test_untrusted_source_cannot_admit_policy_eligibility(self):
        records = evidence()
        records[-1]["source"] = "model_self_report"
        self.assert_nonaction(self.run_gate(records))

    def test_future_availability_is_not_used(self):
        records = evidence()
        records[-1]["available_at"] = AT + 1
        self.assert_nonaction(self.run_gate(records))

    def test_disallowed_claim_is_wrapper_nonaction_without_reservation(self):
        result = self.run_gate(requested_claim="cancel_booking")
        self.assert_nonaction(result)
        self.assertEqual(result["reason"], "requested_claim_not_allowed_for_action")
        self.assertEqual(result["permit"]["route"], "no_action")

    def test_missing_requested_claim_is_safe_nonaction(self):
        self.assert_nonaction(self.run_gate(requested_claim=None))

    def test_empty_evidence_has_no_fake_core_permit(self):
        result = self.run_gate([])
        self.assert_nonaction(result)
        self.assertIsNone(result["permit"])
        self.assertEqual(result["boundary"], "wrapper_schema_rejection")

    def test_same_request_is_idempotent_authorization_only(self):
        first = self.run_gate()
        self.assertEqual(first, self.run_gate())
        self.assertEqual(self.gate.snapshot()["n_jobs"], 1)
        self.assertEqual(self.gate.snapshot()["reserved"], 1)

    def test_changed_action_same_identity_is_rejected(self):
        self.run_gate()
        action = deepcopy(self.action)
        action["arguments"]["amount"] = 200
        with self.assertRaisesRegex(ValueError, "conflicting raw request"):
            self.run_gate(action=action)

    def test_before_dispatch_binding_rejects_changed_arguments_and_result(self):
        result = self.run_gate()
        action = deepcopy(self.action)
        action["arguments"]["user_id"] = "another-user"
        with self.assertRaises(ValueError):
            self.gate.assert_action_binding(result, action)
        result["permit"]["permitted_claim_ids"].append("cancel_booking")
        with self.assertRaises(ValueError):
            self.gate.assert_action_binding(result, self.action)

    def test_forged_allowed_boolean_cannot_arm_denied_claim(self):
        result = self.run_gate(requested_claim="cancel_booking")
        result.update(allowed=True, armed=True)
        with self.assertRaises(ValueError):
            self.gate.assert_action_binding(result, self.action)

    def test_invalid_time_and_duplicate_evidence_rejected(self):
        for value in (True, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_gate(at=value)
        records = evidence()
        records.append(deepcopy(records[0]))
        with self.assertRaisesRegex(ValueError, "evidence IDs must be unique"):
            self.run_gate(records)

    def test_no_evidence_truth_or_money_policy_is_invented(self):
        records = evidence()
        records[-1]["body_hash"] = "0" * 64
        action = deepcopy(self.action)
        action["arguments"]["amount"] = 987654
        result = self.run_gate(records, action=action)
        self.assertTrue(result["allowed"])
        # Eligibility/amount correctness belongs to the shared business checker.

    def test_authoritative_sources_are_read_only_and_identifiable(self):
        before = source_manifest()
        self.run_gate()
        self.assertEqual(before, source_manifest())
        self.assertEqual(core_files(), SOURCE_FILES)
        self.assertTrue(all(Path(path).is_file() for path in SOURCE_FILES))
        self.assertTrue(str(G.OrderedAdjudicator.__module__).startswith("agentic_eeg_dm.governance"))


if __name__ == "__main__":
    unittest.main()
