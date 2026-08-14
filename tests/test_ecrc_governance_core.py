from __future__ import annotations

from dataclasses import replace

import pytest

from agentic_eeg_dm.governance import (
    ClaimRule,
    EvidenceEnvelope,
    EvidenceItem,
    EvidenceRule,
    IdempotencyConflictError,
    InvalidPermitError,
    ModelBinding,
    OrderedAdjudicator,
    PEPSimulator,
    PermitReplayError,
    PolicyExpiredError,
    PolicyManifest,
    ProposalEnvelope,
    ReceiptVerificationError,
    RevokedPolicyError,
    SQLiteCapacityLedger,
    StalePolicyError,
    StatefulReceiptVerifier,
    canonical_hash,
)

NOW = "2026-01-01T00:00:10Z"
EXECUTION_TIME = "2026-01-01T00:00:11Z"
MODEL_HASH = "a" * 64


def make_policy(**overrides: object) -> PolicyManifest:
    values: dict[str, object] = {
        "policy_id": "test-policy",
        "revision": 1,
        "issuer_id": "test-authority",
        "effective_from": "2026-01-01T00:00:00Z",
        "expires_at": "2026-01-02T00:00:00Z",
        "approved_models": (ModelBinding("frozen-model", MODEL_HASH),),
        "evidence_rules": (
            EvidenceRule(
                evidence_type="behavior_score",
                allowed_sources=("frozen-heldout-pipeline",),
                allowed_schema_versions=("1.0",),
                max_age_seconds=60,
                use_allowed=True,
            ),
        ),
        "score_threshold": 0.60,
        "uncertainty_threshold": 0.80,
        "review_band_width": 0.05,
        "alert_capacity": 2,
        "review_capacity": 2,
        "capacity_scope": "subject_session",
        "claim_rules": (
            ClaimRule(
                "task_alert",
                ("alert",),
                required_evidence_types=("behavior_score",),
            ),
            ClaimRule(
                "task_review",
                ("review",),
                required_evidence_types=("behavior_score",),
            ),
            ClaimRule("task_abstention", ("abstain",)),
            ClaimRule("task_no_action", ("no_action",)),
        ),
        "blocked_claim_ids": ("clinical_diagnosis", "intervention_efficacy"),
    }
    values.update(overrides)
    return PolicyManifest(**values)


def make_proposal(
    decision_id: str,
    *,
    score: float = 0.90,
    uncertainty: float = 0.10,
    subject_id: str = "subject-1",
    session_id: str = "session-1",
) -> ProposalEnvelope:
    return ProposalEnvelope(
        decision_id=decision_id,
        subject_id=subject_id,
        session_id=session_id,
        model_id="frozen-model",
        model_version="1.0",
        model_hash=MODEL_HASH,
        score=score,
        uncertainty=uncertainty,
        proposed_action="alert",
        proposed_at="2026-01-01T00:00:05Z",
        input_hash=canonical_hash({"decision_id": decision_id}),
        validation_scope_id="heldout-task-decision",
    )


def make_evidence(decision_id: str) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        decision_id=decision_id,
        created_at="2026-01-01T00:00:06Z",
        items=(
            EvidenceItem(
                evidence_id=f"behavior::{decision_id}",
                evidence_type="behavior_score",
                source="frozen-heldout-pipeline",
                schema_version="1.0",
                observed_at="2026-01-01T00:00:03Z",
                available_at="2026-01-01T00:00:04Z",
                provenance_hash=canonical_hash({"evidence": decision_id}),
                requested_for_use=True,
            ),
            EvidenceItem(
                evidence_id=f"outcome::{decision_id}",
                evidence_type="posthoc_outcome",
                source="evaluator-only",
                schema_version="1.0",
                observed_at="2026-01-01T00:00:07Z",
                available_at="2026-01-01T00:00:08Z",
                provenance_hash=canonical_hash({"outcome": decision_id}),
                requested_for_use=True,
            ),
        ),
    )


def test_schema_round_trip_and_canonical_hash() -> None:
    policy = make_policy()
    assert PolicyManifest.from_dict(policy.to_dict()) == policy
    assert PolicyManifest.json_schema()["title"] == "ECRC PolicyManifest"
    assert ProposalEnvelope.json_schema()["additionalProperties"] is False
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


def test_model_id_hash_binding_rejects_cross_pair(tmp_path) -> None:
    other_hash = "b" * 64
    policy = make_policy(
        approved_models=(
            ModelBinding("frozen-model", MODEL_HASH),
            ModelBinding("other-model", other_hash),
        )
    )
    ledger = SQLiteCapacityLedger(tmp_path / "model-binding.sqlite")
    ledger.register_policy(policy)
    crossed = replace(make_proposal("crossed"), model_hash=other_hash)
    with pytest.raises(InvalidPermitError, match="ID/hash pair"):
        OrderedAdjudicator(ledger).adjudicate(
            policy, crossed, make_evidence("crossed"), at=NOW
        )


def test_policy_recomputes_evidence_admission_and_use(tmp_path) -> None:
    policy = make_policy()
    ledger = SQLiteCapacityLedger(tmp_path / "evidence-gate.sqlite")
    ledger.register_policy(policy)
    proposal = make_proposal("gated")
    evidence = EvidenceEnvelope(
        decision_id="gated",
        created_at="2026-01-01T00:00:06Z",
        items=(
            EvidenceItem(
                evidence_id="wrong-source",
                evidence_type="behavior_score",
                source="untrusted-source",
                schema_version="1.0",
                observed_at="2026-01-01T00:00:03Z",
                available_at="2026-01-01T00:00:04Z",
                provenance_hash=canonical_hash("wrong-source"),
                requested_for_use=True,
            ),
            EvidenceItem(
                evidence_id="future",
                evidence_type="behavior_score",
                source="frozen-heldout-pipeline",
                schema_version="1.0",
                observed_at="2026-01-01T00:00:06Z",
                available_at="2026-01-01T00:00:06Z",
                provenance_hash=canonical_hash("future"),
                requested_for_use=True,
            ),
        ),
    )
    permit = OrderedAdjudicator(ledger).adjudicate(policy, proposal, evidence, at=NOW)
    assert permit.route == "abstain"
    assert permit.reason_code == "no_policy_admitted_evidence_for_use"
    assert permit.admitted_evidence_ids == ()
    assert set(permit.excluded_evidence_ids) == {"future", "wrong-source"}


def test_unrelated_but_admitted_evidence_cannot_authorize_action(tmp_path) -> None:
    policy = make_policy(
        evidence_rules=(
            EvidenceRule(
                evidence_type="behavior_score",
                allowed_sources=("frozen-heldout-pipeline",),
                allowed_schema_versions=("1.0",),
                max_age_seconds=60,
            ),
            EvidenceRule(
                evidence_type="unrelated_context",
                allowed_sources=("frozen-heldout-pipeline",),
                allowed_schema_versions=("1.0",),
                max_age_seconds=60,
            ),
        )
    )
    ledger = SQLiteCapacityLedger(tmp_path / "unrelated-evidence.sqlite")
    ledger.register_policy(policy)
    evidence = EvidenceEnvelope(
        decision_id="unrelated",
        created_at="2026-01-01T00:00:06Z",
        items=(
            EvidenceItem(
                evidence_id="context-only",
                evidence_type="unrelated_context",
                source="frozen-heldout-pipeline",
                schema_version="1.0",
                observed_at="2026-01-01T00:00:03Z",
                available_at="2026-01-01T00:00:04Z",
                provenance_hash=canonical_hash("context-only"),
                requested_for_use=True,
            ),
        ),
    )
    permit = OrderedAdjudicator(ledger).adjudicate(
        policy, make_proposal("unrelated"), evidence, at=NOW
    )
    assert permit.route == "abstain"
    assert permit.reason_code == "no_claim_supported_by_used_evidence"
    assert permit.reservation_id is None
    assert permit.used_evidence_ids == ("context-only",)
    counts = ledger.counts()
    assert counts.reservations_released == 1
    assert counts.reservations_reserved == 0

    duplicate = OrderedAdjudicator(ledger).adjudicate(
        policy, make_proposal("unrelated"), evidence, at=NOW
    )
    assert duplicate == permit


def test_manifest_and_permit_require_evidence_bound_action_claims(tmp_path) -> None:
    with pytest.raises(ValueError, match="requires a claim rule"):
        make_policy(claim_rules=())
    with pytest.raises(ValueError, match="require at least one evidence type"):
        make_policy(
            claim_rules=(
                ClaimRule("unbound_alert", ("alert",)),
                ClaimRule(
                    "task_review",
                    ("review",),
                    required_evidence_types=("behavior_score",),
                ),
            )
        )

    ledger = SQLiteCapacityLedger(tmp_path / "permit-claim-invariant.sqlite")
    policy = make_policy()
    ledger.register_policy(policy)
    permit = OrderedAdjudicator(ledger).adjudicate(
        policy,
        make_proposal("claim-invariant"),
        make_evidence("claim-invariant"),
        at=NOW,
    )
    with pytest.raises(ValueError, match="at least one permitted claim"):
        replace(permit, permitted_claim_ids=())


def test_ordered_adjudicator_routes_and_claims(tmp_path) -> None:
    ledger = SQLiteCapacityLedger(tmp_path / "governance.sqlite")
    policy = make_policy(alert_capacity=3, review_capacity=3)
    ledger.register_policy(policy)
    adjudicator = OrderedAdjudicator(ledger)

    cases = (
        (make_proposal("alert", score=0.90), "alert", "task_alert"),
        (make_proposal("review", score=0.62), "review", "task_review"),
        (
            make_proposal("abstain", score=0.90, uncertainty=0.90),
            "abstain",
            "task_abstention",
        ),
        (make_proposal("none", score=0.20), "no_action", "task_no_action"),
    )
    for proposal, expected_route, expected_claim in cases:
        permit = adjudicator.adjudicate(
            policy, proposal, make_evidence(proposal.decision_id), at=NOW
        )
        assert permit.route == expected_route
        assert expected_claim in permit.permitted_claim_ids
        assert "clinical_diagnosis" in permit.blocked_claim_ids
        assert set(permit.used_evidence_ids).issubset(permit.admitted_evidence_ids)


def test_duplicate_retry_is_idempotent_and_conflict_is_closed(tmp_path) -> None:
    ledger = SQLiteCapacityLedger(tmp_path / "governance.sqlite")
    policy = make_policy(alert_capacity=1)
    ledger.register_policy(policy)
    adjudicator = OrderedAdjudicator(ledger)
    proposal = make_proposal("duplicate")
    evidence = make_evidence("duplicate")

    first = adjudicator.adjudicate(policy, proposal, evidence, at=NOW)
    second = adjudicator.adjudicate(policy, proposal, evidence, at=NOW)
    assert first == second
    snapshot = ledger.capacity_snapshot(
        policy, scope_key="subject-1::session-1", resource="alert"
    )
    assert (snapshot.reserved, snapshot.committed, snapshot.available) == (1, 0, 0)

    conflicting = replace(proposal, score=0.95)
    with pytest.raises(IdempotencyConflictError):
        adjudicator.adjudicate(policy, conflicting, evidence, at=NOW)

    pep = PEPSimulator(ledger)
    receipt = pep.execute(policy, first, at=EXECUTION_TIME)
    assert receipt.execution_status == "executed"
    with pytest.raises(PermitReplayError):
        pep.execute(policy, second, at=EXECUTION_TIME)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("permitted_claim_ids", ("forged_claim",)),
        ("blocked_claim_ids", ("forged_block",)),
        ("admitted_evidence_ids", ("behavior::forged", "forged_evidence")),
        ("reason_code", "forged_reason"),
        ("permit_id", "permit_forged_identifier"),
    ),
)
def test_pep_rejects_forged_permit_content(tmp_path, field, value) -> None:
    ledger = SQLiteCapacityLedger(tmp_path / f"forged-{field}.sqlite")
    policy = make_policy(alert_capacity=1)
    ledger.register_policy(policy)
    issued = OrderedAdjudicator(ledger).adjudicate(
        policy, make_proposal("forged"), make_evidence("forged"), at=NOW
    )
    forged = replace(issued, **{field: value})
    with pytest.raises(InvalidPermitError):
        PEPSimulator(ledger).execute(policy, forged, at=EXECUTION_TIME)


def test_pep_rejects_forged_nonaction_route(tmp_path) -> None:
    ledger = SQLiteCapacityLedger(tmp_path / "forged-route.sqlite")
    policy = make_policy(alert_capacity=1)
    ledger.register_policy(policy)
    issued = OrderedAdjudicator(ledger).adjudicate(
        policy, make_proposal("forged-route"), make_evidence("forged-route"), at=NOW
    )
    forged = replace(
        issued,
        route="no_action",
        reason_code="forged_route",
        reservation_id=None,
        reserved_resource=None,
        pre_state_revision=0,
        post_state_revision=0,
    )
    with pytest.raises(InvalidPermitError):
        PEPSimulator(ledger).execute(policy, forged, at=EXECUTION_TIME)


def test_expired_revoked_and_stale_policies_fail_closed(tmp_path) -> None:
    expired_ledger = SQLiteCapacityLedger(tmp_path / "expired.sqlite")
    expired = make_policy(
        policy_id="expired",
        effective_from="2025-12-31T00:00:00Z",
        expires_at="2026-01-01T00:00:09Z",
    )
    expired_ledger.register_policy(expired)
    with pytest.raises(PolicyExpiredError):
        OrderedAdjudicator(expired_ledger).adjudicate(
            expired, make_proposal("expired"), make_evidence("expired"), at=NOW
        )

    revoked_ledger = SQLiteCapacityLedger(tmp_path / "revoked.sqlite")
    revoked = make_policy(policy_id="revoked")
    revoked_ledger.register_policy(revoked)
    revoked_ledger.revoke_policy(revoked.policy_id, expected_revision=1)
    with pytest.raises(RevokedPolicyError):
        OrderedAdjudicator(revoked_ledger).adjudicate(
            revoked, make_proposal("revoked"), make_evidence("revoked"), at=NOW
        )

    stale_ledger = SQLiteCapacityLedger(tmp_path / "stale.sqlite")
    first_policy = make_policy(policy_id="versioned", alert_capacity=1)
    stale_ledger.register_policy(first_policy)
    stale_permit = OrderedAdjudicator(stale_ledger).adjudicate(
        first_policy,
        make_proposal("stale-permit"),
        make_evidence("stale-permit"),
        at=NOW,
    )
    second_policy = replace(first_policy, revision=2, alert_capacity=2)
    stale_ledger.register_policy(second_policy)
    with pytest.raises(StalePolicyError):
        OrderedAdjudicator(stale_ledger).adjudicate(
            first_policy,
            make_proposal("stale-request"),
            make_evidence("stale-request"),
            at=NOW,
        )
    with pytest.raises(StalePolicyError):
        PEPSimulator(stale_ledger).execute(
            first_policy, stale_permit, at=EXECUTION_TIME
        )


def test_pre_execution_failure_releases_capacity(tmp_path) -> None:
    ledger = SQLiteCapacityLedger(tmp_path / "governance.sqlite")
    policy = make_policy(alert_capacity=1)
    ledger.register_policy(policy)
    adjudicator = OrderedAdjudicator(ledger)
    first = adjudicator.adjudicate(
        policy, make_proposal("crash-1"), make_evidence("crash-1"), at=NOW
    )
    failed = PEPSimulator(ledger).execute(
        policy,
        first,
        at=EXECUTION_TIME,
        simulate_pre_execution_failure=True,
    )
    assert failed.execution_status == "failed"
    released = ledger.capacity_snapshot(
        policy, scope_key="subject-1::session-1", resource="alert"
    )
    assert (released.reserved, released.committed, released.available) == (0, 0, 1)

    second = adjudicator.adjudicate(
        policy, make_proposal("crash-2"), make_evidence("crash-2"), at=NOW
    )
    assert second.route == "alert"


def test_expired_unissued_reservation_is_reaped_after_crash_gap(tmp_path) -> None:
    ledger = SQLiteCapacityLedger(
        tmp_path / "crash-gap.sqlite", reservation_lease_seconds=1
    )
    policy = make_policy(alert_capacity=1)
    ledger.register_policy(policy)
    proposal = make_proposal("crashed-after-reserve")
    reservation = ledger.reserve(
        policy,
        scope_key="subject-1::session-1",
        resource="alert",
        idempotency_key="crash-gap-reservation",
        request_hash=canonical_hash({"decision": proposal.decision_id}),
        at=NOW,
    )
    assert reservation.status == "reserved"
    assert ledger.reap_expired_reservations(at=NOW) == ()

    reaped = ledger.reap_expired_reservations(at="2026-01-01T00:00:11Z")
    assert tuple(row.reservation_id for row in reaped) == (reservation.reservation_id,)
    snapshot = ledger.capacity_snapshot(
        policy, scope_key="subject-1::session-1", resource="alert"
    )
    assert (snapshot.reserved, snapshot.committed, snapshot.available) == (0, 0, 1)
    recovered = OrderedAdjudicator(ledger).adjudicate(
        policy,
        make_proposal("post-crash-new-decision"),
        make_evidence("post-crash-new-decision"),
        at="2026-01-01T00:00:12Z",
    )
    assert recovered.route == "alert"


def test_reaper_never_releases_issued_or_committed_reservations(tmp_path) -> None:
    ledger = SQLiteCapacityLedger(
        tmp_path / "issued-lease.sqlite", reservation_lease_seconds=1
    )
    policy = make_policy(alert_capacity=1)
    ledger.register_policy(policy)
    permit = OrderedAdjudicator(ledger).adjudicate(
        policy,
        make_proposal("issued-before-lease-expiry"),
        make_evidence("issued-before-lease-expiry"),
        at=NOW,
    )
    assert ledger.reap_expired_reservations(at="2026-01-01T00:00:11Z") == ()
    receipt = PEPSimulator(ledger).execute(policy, permit, at=EXECUTION_TIME)
    assert receipt.execution_status == "executed"
    assert ledger.reap_expired_reservations(at="2026-01-01T00:00:12Z") == ()
    counts = ledger.counts()
    assert counts.reservations_committed == 1
    assert counts.reservations_released == 0


def test_receipt_hash_chain_detects_reorder_mutation_and_missing_rows(tmp_path) -> None:
    ledger = SQLiteCapacityLedger(tmp_path / "governance.sqlite")
    policy = make_policy(alert_capacity=2)
    ledger.register_policy(policy)
    adjudicator = OrderedAdjudicator(ledger)
    pep = PEPSimulator(ledger)
    permits = []
    for decision_id in ("chain-1", "chain-2"):
        permit = adjudicator.adjudicate(
            policy,
            make_proposal(decision_id),
            make_evidence(decision_id),
            at=NOW,
        )
        permits.append(permit)
        pep.execute(policy, permit, at=EXECUTION_TIME)

    receipts = ledger.list_receipts()
    permits_by_id = {permit.permit_id: permit for permit in permits}
    trusted_tail = ledger.tail_receipt_hash()
    StatefulReceiptVerifier().verify_chain(
        receipts, permits_by_id, expected_tail_hash=trusted_tail
    )

    with pytest.raises(ReceiptVerificationError):
        StatefulReceiptVerifier().verify_chain(tuple(reversed(receipts)), permits_by_id)
    with pytest.raises(ReceiptVerificationError):
        StatefulReceiptVerifier().verify_chain(receipts[1:], permits_by_id)

    mutated_first = (replace(receipts[0], side_effect_id="tampered"), receipts[1])
    with pytest.raises(ReceiptVerificationError):
        StatefulReceiptVerifier().verify_chain(mutated_first, permits_by_id)

    mutated_last = (receipts[0], replace(receipts[1], side_effect_id="tampered-tail"))
    with pytest.raises(ReceiptVerificationError):
        StatefulReceiptVerifier().verify_chain(
            mutated_last, permits_by_id, expected_tail_hash=trusted_tail
        )


def test_pep_rejects_expired_permit(tmp_path) -> None:
    ledger = SQLiteCapacityLedger(tmp_path / "governance.sqlite")
    policy = make_policy(alert_capacity=1)
    ledger.register_policy(policy)
    permit = OrderedAdjudicator(ledger, permit_ttl_seconds=1).adjudicate(
        policy, make_proposal("permit-expiry"), make_evidence("permit-expiry"), at=NOW
    )
    with pytest.raises(InvalidPermitError):
        PEPSimulator(ledger).execute(policy, permit, at="2026-01-01T00:00:12Z")
