from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRAMEWORK_ROOT))

from component_ablation import (  # noqa: E402
    E1_ACTION_ROUTES,
    RECORD_VALIDATORS,
    REFERENCE_AUTO_CAP,
    REFERENCE_REVIEW_CAP,
    build_record_fault_cases,
    build_runtime_fixture,
    route_component_arm,
    validator_failures,
)


def proposal_frame() -> pd.DataFrame:
    scores = [0.95, 0.92, 0.89, 0.62, 0.61, 0.50] * 4
    return pd.DataFrame(
        {
            "dataset_id": "synthetic",
            "evaluation_scope": "test",
            "model_name": "frozen",
            "subject_id": "p1",
            "study_id": "s1",
            "trial_id": range(1, len(scores) + 1),
            "outer_fold": 0,
            "y_true": [0, 1] * (len(scores) // 2),
            "score": scores,
            "evidence_status": "admitted",
            "prompt_threshold": 0.60,
            "uncertainty_threshold": 0.90,
            "review_band_width": 0.03,
        }
    )


def test_evidence_gate_blocks_only_stressed_invalid_evidence() -> None:
    frame = proposal_frame()
    frame.loc[[0, 3], "evidence_status"] = ["missing", "stale"]
    full = route_component_arm(frame, arm="full_controls")
    gate_off = route_component_arm(frame, arm="evidence_gate_off")
    invalid = ~full["evidence_status"].eq("admitted")
    assert full.loc[invalid, "primary_route"].eq("abstain").all()
    assert not gate_off.loc[invalid, "primary_route"].eq("abstain").all()


def test_uncertainty_and_shared_capacity_arms_keep_frozen_proposals() -> None:
    frame = proposal_frame()
    uncertainty_off = route_component_arm(frame, arm="uncertainty_gate_off")
    assert not uncertainty_off["reason_code"].eq("uncertainty_gate").any()

    shared = route_component_arm(frame, arm="shared_capacity")
    actions = shared["primary_route"].isin(E1_ACTION_ROUTES)
    assert int(actions.sum()) <= REFERENCE_AUTO_CAP + REFERENCE_REVIEW_CAP
    assert shared["score"].tolist() == frame["score"].tolist()


def test_runtime_fault_ablation_uses_trusted_stack(tmp_path: Path) -> None:
    fixture = build_runtime_fixture(tmp_path / "runtime.sqlite")
    cases = build_record_fault_cases(fixture, seed=11, cases_per_family=1)
    clean_case = type(cases[0])(
        case_id="clean",
        fault_family="clean",
        expected_component="none",
        fault_stage="post_execution_receipt",
        source_decision_id="none",
        target_position=-1,
        permits=fixture.permits,
        receipts=fixture.receipts,
    )
    assert all(
        not validator_failures(fixture, clean_case, validator)
        for validator in RECORD_VALIDATORS
    )

    claim_case = next(
        case for case in cases if case.expected_component.startswith("trusted")
    )
    receipt_case = next(
        case for case in cases if case.expected_component.startswith("stateful")
    )
    assert validator_failures(fixture, claim_case, "full_binding_and_receipt")
    assert not validator_failures(fixture, claim_case, "claim_binding_off")
    assert validator_failures(fixture, receipt_case, "full_binding_and_receipt")
    assert not validator_failures(
        fixture, receipt_case, "receipt_state_verification_off"
    )
