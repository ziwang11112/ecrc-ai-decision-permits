"""Synthetic switch/isolation QA; never native business experiment results."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import ablation_gates as A


AT = 1715799600.0
STAMP = "2024-05-15T19:00:00.000000Z"


def candidate(eligible=True):
    action = {"name": "cancel_reservation", "arguments": {"reservation_id": "booking"}}
    reservation = {"reservation_id": "booking", "user_id": "customer", "status": None,
                   "created_at": "2024-05-01T12:00:00", "cabin": "economy",
                   "insurance": "yes" if eligible else "no",
                   "flights": [{"flight_number": "F1", "date": "2024-05-20"}],
                   "passengers": [{"first_name": "Example", "last_name": "Person"}]}
    request = {"user_id": "customer", "user_statement": "I am sick and want this booking cancelled.",
               "cancellation": {"selector": {"kind": "ids", "ids": ["booking"]}, "reason": "health"}}
    display = {**deepcopy(action), "reservation_id": "booking", "scope": "whole_reservation",
               "flights": deepcopy(reservation["flights"]), "passengers": deepcopy(reservation["passengers"])}
    basis, denial = A.SCOPE.PREVIOUS_BUSINESS.cancel_basis(reservation, ["available"], "health")
    context = {"request": request, "user": {"user_id": "customer", "reservations": ["booking"]},
               "reservation": reservation, "flight_statuses": ["available"],
               "confirmation": {"user_id": "customer", "actions": [display]},
               "eligibility": {"allowed": bool(basis), "basis": basis, "denial": denial}}
    return action, context


class AblationGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.index = 0

    def gate(self, mode):
        self.index += 1
        return A.make_gate(mode, Path(self.directory.name) / f"gate-{self.index}.sqlite")

    def authorize(self, gate, eligible=True):
        action, context = candidate(eligible)
        return gate.authorize_candidate("decision", action, context, AT)

    def raw_positive(self):
        seed = self.gate("full")
        self.authorize(seed)
        return json.loads(seed.core.get_request("decision")["request_json"])

    def issue_raw(self, mode, request):
        gate = self.gate(mode)
        gate.core.ingest(deepcopy(request), STAMP)
        permit = gate.core.issue("decision", STAMP)
        return gate, permit

    def test_full_is_original_class_and_same_authorization(self):
        full = self.gate("full")
        original = A.SCOPE.ScopeGate(Path(self.directory.name) / "original.sqlite")
        self.assertIs(type(full), A.SCOPE.ScopeGate)
        self.assertIs(type(full.core), A.S8.Adapter)
        self.assertEqual(self.authorize(full), self.authorize(original))

    def test_claim_ablation_changes_exactly_one_required_type_and_no_other_policy_field(self):
        full, ablated = self.gate("full"), self.gate("without_claim_evidence_requirement")
        expected = deepcopy(full.policies)
        expected["cancel_reservation"]["claim_rules"][0]["required_evidence_types"].remove("cancellation_eligible")
        self.assertEqual(ablated.policies, expected)
        self.assertEqual(ablated.model_hash, full.model_hash)

    def test_negative_candidate_grants_only_when_claim_evidence_dependency_removed(self):
        full, ablated = self.gate("full"), self.gate("without_claim_evidence_requirement")
        normal, removed = self.authorize(full, False), self.authorize(ablated, False)
        self.assertEqual(normal["input"], removed["input"])
        self.assertEqual(normal["bodies"], removed["bodies"])
        self.assertNotIn("cancellation_eligible", removed["bodies"])
        self.assertFalse(removed["bodies"]["reservation_record"]["eligibility_check"]["allowed"])
        self.assertFalse(normal["authorization"]["allowed"])
        self.assertEqual(normal["authorization"]["permit"]["route"], "abstain")
        self.assertTrue(removed["authorization"]["allowed"])
        self.assertEqual(removed["authorization"]["permit"]["permitted_claim_ids"], ["cancel_booking"])
        ablated.assert_action_binding(removed["authorization"], removed["input"]["action"])
        state = ablated.snapshot()
        self.assertEqual((state["reserved"], state["committed"], state["n_receipts"]), (1, 0, 0))

    def test_claim_ablation_retains_domain_checker_and_before_dispatch_binding(self):
        gate = self.gate("without_claim_evidence_requirement")
        action, context = candidate(False)
        context["eligibility"] = {"allowed": True, "basis": "insured_covered_reason", "denial": None}
        with self.assertRaisesRegex(ValueError, "eligibility does not match"):
            gate.authorize_candidate("decision", action, context, AT)
        result = self.authorize(gate, False)
        action["arguments"]["reservation_id"] = "another-booking"
        with self.assertRaises(ValueError):
            gate.assert_action_binding(result["authorization"], action)

    def test_normal_metadata_variant_matches_full_for_positive_and_negative_inputs(self):
        for eligible in (True, False):
            with self.subTest(eligible=eligible):
                full, removed = self.gate("full"), self.gate("without_metadata_qualification")
                self.assertEqual(full.policies, removed.policies)
                self.assertEqual(self.authorize(full, eligible), self.authorize(removed, eligible))
                self.assertEqual(full.snapshot(), removed.snapshot())

    def test_metadata_switch_actually_bypasses_source_version_and_time_qualification(self):
        seed = self.raw_positive()
        for field, value in (("source", "unqualified-source"), ("schema_version", "2"),
                             ("observed_at", "2024-05-15T18:54:59.000000Z"),
                             ("observed_at", "2024-05-15T19:00:01.000000Z"),
                             ("available_at", "2024-05-15T19:00:01.000000Z")):
            with self.subTest(field=field, value=value):
                raw = deepcopy(seed)
                record = next(item for item in raw["evidence"]["items"] if item["evidence_type"] == "cancellation_eligible")
                record[field] = value
                if field == "observed_at" and value > STAMP:
                    # Retain the structural observed<=available constraint;
                    # this QA targets qualification relative to proposal time.
                    record["available_at"] = value
                _, full = self.issue_raw("full", raw)
                ablated_gate, removed = self.issue_raw("without_metadata_qualification", raw)
                self.assertEqual(full["route"], "abstain")
                self.assertIn(record["evidence_id"], full["excluded_evidence_ids"])
                self.assertEqual(removed["route"], "alert")
                self.assertEqual(removed["permitted_claim_ids"], ["cancel_booking"])
                self.assertIn(record["evidence_id"], removed["used_evidence_ids"])
                self.assertEqual(ablated_gate.snapshot()["n_receipts"], 0)

    def test_metadata_ablation_never_fills_a_missing_positive_type(self):
        result = self.authorize(self.gate("without_metadata_qualification"), False)
        self.assertEqual(len(result["input"]["evidence"]), 3)
        self.assertEqual(result["authorization"]["permit"]["permitted_claim_ids"], [])
        self.assertEqual(result["authorization"]["permit"]["reason_code"], "no_claim_supported_by_used_evidence")

    def test_type_vocabulary_and_request_for_use_still_apply(self):
        for field, value in (("evidence_type", "unknown-type"), ("requested_for_use", False)):
            with self.subTest(field=field):
                raw = self.raw_positive()
                record = next(item for item in raw["evidence"]["items"] if item["evidence_type"] == "cancellation_eligible")
                record[field] = value
                _, permit = self.issue_raw("without_metadata_qualification", raw)
                self.assertEqual(permit["route"], "abstain")
                self.assertNotIn(record["evidence_id"], permit["used_evidence_ids"])

    def test_policy_use_allowed_false_remains_admitted_but_unused(self):
        raw = self.raw_positive()
        raw["policy"]["evidence_rules"].append({"evidence_type": "unused_context", "allowed_sources": ["native_airline"],
                                                "allowed_schema_versions": ["1"], "max_age_seconds": 300, "use_allowed": False})
        extra = deepcopy(raw["evidence"]["items"][0])
        extra.update(evidence_id="unused-context", evidence_type="unused_context", source="native_airline", requested_for_use=True)
        raw["evidence"]["items"].append(extra)
        policy = A.G.PolicyManifest.from_dict(raw["policy"])
        proposal = A.G.ProposalEnvelope.from_dict(raw["proposal"])
        evidence = A.G.EvidenceEnvelope.from_dict(raw["evidence"])
        admitted, used, excluded, types_used = A.NoMetadataAdjudicator._gate_evidence(policy, proposal, evidence)
        self.assertIn("unused-context", admitted)
        self.assertNotIn("unused-context", used)
        self.assertNotIn("unused_context", types_used)

    def test_other_core_validation_is_not_disabled(self):
        raw = self.raw_positive()
        raw["proposal"]["proposed_at"] = "2024-05-15T19:00:01.000000Z"
        for mode in ("full", "without_metadata_qualification"):
            with self.subTest(mode=mode), self.assertRaisesRegex(Exception, "proposal timestamp is in the future"):
                self.issue_raw(mode, raw)

    def test_structurally_inconsistent_evidence_time_remains_rejected(self):
        raw = self.raw_positive()
        record = next(item for item in raw["evidence"]["items"] if item["evidence_type"] == "cancellation_eligible")
        record["observed_at"] = "2024-05-15T19:00:01.000000Z"
        for mode in ("full", "without_metadata_qualification"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "observed_at must not follow available_at"):
                self.issue_raw(mode, raw)

    def test_isolated_issue_never_mutates_full_globals_or_sources(self):
        before = A.source_manifest()
        original_globals = A.S8.Adapter.issue.__globals__
        original_binding = original_globals["OrderedAdjudicator"]
        removed = self.gate("without_metadata_qualification")
        self.authorize(removed)
        self.assertIs(A.NoMetadataAdapter.issue.__code__, A.ORIGINAL_ISSUE.__code__)
        self.assertIsNot(A.NoMetadataAdapter.issue.__globals__, original_globals)
        self.assertIs(A.NoMetadataAdapter.issue.__globals__["OrderedAdjudicator"], A.NoMetadataAdjudicator)
        self.assertIs(A.S8.Adapter.issue.__globals__["OrderedAdjudicator"], original_binding)
        self.assertIs(original_binding, A.G.OrderedAdjudicator)
        after = self.gate("full")
        self.assertIs(type(after.core), A.S8.Adapter)
        self.assertEqual(after.snapshot()["n_jobs"], 0)
        self.authorize(after)
        self.assertEqual(A.source_manifest(), before)

    def test_unknown_mode_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "Unknown ablation gate mode"):
            self.gate("something-else")


if __name__ == "__main__":
    unittest.main()
