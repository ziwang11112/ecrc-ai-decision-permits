#!/usr/bin/env python3
"""Matched ECRC component ablation over frozen E1 proposals.

The evaluation has two deliberately separate axes.

* Routing/resource components are evaluated with route and workload outcomes.
  A deterministic missing/stale-evidence fixture tests the evidence gate; an
  effectively unbounded alert and review ledger tests removal of capacity.
* Record/state components are evaluated only with clean false positives and
  prespecified fault detection.  The clean fixture is issued by the real ECRC
  adjudicator, persisted in its SQLite ledger, consumed by the PEP simulator,
  and checked by the stateful receipt verifier.

The runtime fixture is a deterministic conformance artifact.  It does not
establish that any real-world action was executed or that the SQLite transaction
extends to an external alert or ticketing service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
from e1.config import PRIMARY_ROUTES
from e1.provenance import (
    environment_record,
    finalize_manifest,
    git_record,
    sha256_file,
    write_csv,
    write_gzip_csv,
    write_json,
)
from e1.routing import policy_metrics, route_frame

from agentic_eeg_dm.governance import (
    ClaimRule,
    DecisionPermit,
    EvidenceEnvelope,
    EvidenceItem,
    EvidenceRule,
    ExecutionReceipt,
    GovernanceError,
    ModelBinding,
    OrderedAdjudicator,
    PEPSimulator,
    PolicyManifest,
    ProposalEnvelope,
    ReceiptVerificationError,
    SQLiteCapacityLedger,
    StatefulReceiptVerifier,
    canonical_hash,
)

SCRIPT_VERSION = "1.1.0"
DEFAULT_SEED = 20_260_813
DEFAULT_BOOTSTRAP_REPLICATES = 2_000
DEFAULT_FAULTS_PER_FAMILY = 12
REFERENCE_AUTO_CAP = 8
REFERENCE_REVIEW_CAP = 2
EVIDENCE_STRESS_MODULUS = 20
EVIDENCE_MISSING_REMAINDERS = frozenset((0,))
EVIDENCE_STALE_REMAINDERS = frozenset((1,))
E1_ACTION_ROUTES = frozenset(("alert", "human_review"))

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
DEFAULT_ROUTE_SOURCE = HERE / "evidence_v2" / "route_assignments.csv.gz"
DEFAULT_OUTPUT_DIR = HERE / "evidence_v2" / "component_ablation"

ROUTING_ARMS = (
    "full_controls",
    "evidence_gate_off",
    "uncertainty_gate_off",
    "shared_capacity",
    "capacity_off",
)
RECORD_VALIDATORS = (
    "ordinary_log",
    "claim_binding_off",
    "receipt_state_verification_off",
    "full_binding_and_receipt",
)
CLAIM_FAULTS = (
    "claim_scope_substitution",
    "evidence_hash_substitution",
)
RECEIPT_FAULTS = (
    "side_effect_id_tamper",
    "previous_receipt_hash_tamper",
    "receipt_reorder",
    "permit_replay",
    "missing_receipt",
)
FAULT_FAMILIES = CLAIM_FAULTS + RECEIPT_FAULTS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", type=Path, default=DEFAULT_ROUTE_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES
    )
    parser.add_argument(
        "--faults-per-family", type=int, default=DEFAULT_FAULTS_PER_FAMILY
    )
    return parser.parse_args()


def stable_hash(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_reference_routes(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    routes = pd.read_csv(source, dtype={"cap_label": str}, low_memory=False)
    routes = routes[routes["cap_label"].eq(str(REFERENCE_AUTO_CAP))].copy()
    required = {
        "dataset_id",
        "evaluation_scope",
        "model_name",
        "subject_id",
        "study_id",
        "trial_id",
        "outer_fold",
        "y_true",
        "score",
        "prompt_threshold",
        "uncertainty_threshold",
        "review_band_width",
        "primary_route",
        "reason_code",
    }
    missing = required - set(routes.columns)
    if missing:
        raise ValueError(f"Reference route source missing {sorted(missing)}")
    if routes.empty:
        raise ValueError("No cap-8 reference routes found")
    key = ["dataset_id", "model_name", "subject_id", "trial_id"]
    if routes.duplicated(key).any():
        raise ValueError("Reference cap-8 routes contain duplicate decision/model keys")
    if any("eeg" in column.lower() for column in routes.columns):
        raise ValueError("Component ablation rejects EEG-bearing route inputs")
    return routes.sort_values(key, kind="mergesort").reset_index(drop=True)


def evidence_status_for_decision(
    dataset_id: str,
    subject_id: str,
    trial_id: int,
    *,
    seed: int,
    scenario: str,
) -> str:
    if scenario == "clean":
        return "admitted"
    if scenario != "missing_stale_stress":
        raise ValueError(f"Unknown evidence scenario {scenario!r}")
    remainder = (
        int(stable_hash(seed, dataset_id, subject_id, int(trial_id))[:16], 16)
        % EVIDENCE_STRESS_MODULUS
    )
    if remainder in EVIDENCE_MISSING_REMAINDERS:
        return "missing"
    if remainder in EVIDENCE_STALE_REMAINDERS:
        return "stale"
    return "admitted"


def add_evidence_status(
    routes: pd.DataFrame,
    *,
    seed: int,
    scenario: str,
) -> pd.DataFrame:
    result = routes.copy()
    # The key excludes model_name so every proposal model receives the same
    # evidence perturbation at a given dataset/participant/decision.
    unique = result[["dataset_id", "subject_id", "trial_id"]].drop_duplicates()
    unique["evidence_status"] = [
        evidence_status_for_decision(
            str(row.dataset_id),
            str(row.subject_id),
            int(row.trial_id),
            seed=seed,
            scenario=scenario,
        )
        for row in unique.itertuples(index=False)
    ]
    return result.merge(
        unique,
        on=["dataset_id", "subject_id", "trial_id"],
        how="left",
        validate="many_to_one",
    )


def _routing_projection(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[
        [
            "dataset_id",
            "evaluation_scope",
            "model_name",
            "subject_id",
            "study_id",
            "trial_id",
            "outer_fold",
            "y_true",
            "score",
            "evidence_status",
        ]
    ].copy()


def _recompute_counters_and_flags(
    routed: pd.DataFrame,
    *,
    automated_alert_cap: int,
    review_cap: int,
) -> pd.DataFrame:
    result = routed.sort_values(["subject_id", "trial_id"], kind="mergesort").copy()
    alert = result["primary_route"].eq("alert").astype(int)
    review = result["primary_route"].eq("human_review").astype(int)
    alert_after = alert.groupby(result["subject_id"], sort=False).cumsum()
    review_after = review.groupby(result["subject_id"], sort=False).cumsum()
    result["auto_alert_count_before"] = alert_after - alert
    result["auto_alert_count_after"] = alert_after
    result["review_count_before"] = review_after - review
    result["review_count_after"] = review_after
    result["automated_alert_cap"] = int(automated_alert_cap)
    result["review_cap"] = int(review_cap)
    for route_name in PRIMARY_ROUTES:
        result[f"route_{route_name}"] = (
            result["primary_route"].eq(route_name).astype(np.int8)
        )
    if not result[[f"route_{name}" for name in PRIMARY_ROUTES]].sum(axis=1).eq(1).all():
        raise AssertionError(
            "Ablation routes are not mutually exclusive and exhaustive"
        )
    if (result.groupby("subject_id")["route_alert"].sum() > automated_alert_cap).any():
        raise AssertionError("Ablation exceeded automated-alert capacity")
    if (result.groupby("subject_id")["route_human_review"].sum() > review_cap).any():
        raise AssertionError("Ablation exceeded review capacity")
    return result.reset_index(drop=True)


def _route_shared_capacity(
    frame: pd.DataFrame,
    *,
    prompt_threshold: float,
    review_band_width: float,
    uncertainty_threshold: float,
    total_action_cap: int,
) -> pd.DataFrame:
    """Route with one FIFO action pool shared by alerts and reviews.

    Review-candidate overflow fails closed to abstention; automated-alert
    overflow becomes no_action.  Candidate type remains mutually exclusive.
    """

    result = frame.sort_values(["subject_id", "trial_id"], kind="mergesort").copy()
    score = result["score"].to_numpy(dtype=float)
    uncertainty = np.clip(1.0 - np.abs(2.0 * score - 1.0), 0.0, 1.0)
    uncertainty_abstain = uncertainty >= uncertainty_threshold
    distance = np.abs(score - prompt_threshold)
    review_candidate = (~uncertainty_abstain) & (distance <= review_band_width)
    alert_candidate = (~uncertainty_abstain) & (
        score > prompt_threshold + review_band_width
    )
    action_candidate = review_candidate | alert_candidate
    candidate_seen = (
        pd.Series(action_candidate.astype(int), index=result.index)
        .groupby(result["subject_id"], sort=False)
        .cumsum()
        .to_numpy(dtype=int)
    )
    action_before = np.minimum(
        candidate_seen - action_candidate.astype(int), total_action_cap
    )
    available = action_before < total_action_cap
    alert = alert_candidate & available
    review = review_candidate & available
    review_overflow = review_candidate & (~available)
    alert_overflow = alert_candidate & (~available)
    abstain = uncertainty_abstain | review_overflow
    route = np.full(len(result), "no_action", dtype=object)
    route[abstain] = "abstain"
    route[alert] = "alert"
    route[review] = "human_review"
    reason = np.full(len(result), "risk_below_prompt_threshold", dtype=object)
    reason[uncertainty_abstain] = "uncertainty_gate"
    reason[review_overflow] = "shared_capacity_exhausted_review"
    reason[alert_overflow] = "shared_capacity_exhausted_alert"
    reason[alert] = "risk_above_review_band"
    reason[review] = "risk_within_threshold_review_band"
    result["uncertainty_score"] = uncertainty
    result["prompt_threshold"] = prompt_threshold
    result["uncertainty_threshold"] = uncertainty_threshold
    result["review_band_width"] = review_band_width
    result["automated_alert_cap"] = total_action_cap
    result["review_cap"] = total_action_cap
    result["primary_route"] = route
    result["reason_code"] = reason
    result["shared_action_count_before"] = action_before
    result["shared_action_count_after"] = action_before + (alert | review).astype(int)
    return result


def route_component_arm(
    frame: pd.DataFrame,
    *,
    arm: str,
) -> pd.DataFrame:
    if arm not in ROUTING_ARMS:
        raise ValueError(f"Unknown routing arm {arm!r}")
    evidence_gate_on = arm != "evidence_gate_off"
    capacity_on = arm != "capacity_off"
    uncertainty_gate_on = arm != "uncertainty_gate_off"
    shared_capacity = arm == "shared_capacity"
    maximum_segment = int(frame.groupby("subject_id").size().max())
    automated_alert_cap = REFERENCE_AUTO_CAP if capacity_on else maximum_segment + 1
    review_cap = REFERENCE_REVIEW_CAP if capacity_on else maximum_segment + 1
    valid = frame["evidence_status"].eq("admitted")
    route_input = frame if not evidence_gate_on else frame[valid]
    uncertainty_threshold = (
        float(frame["uncertainty_threshold"].iloc[0])
        if uncertainty_gate_on
        else float("inf")
    )
    if shared_capacity:
        routed_valid = _route_shared_capacity(
            _routing_projection(route_input),
            prompt_threshold=float(frame["prompt_threshold"].iloc[0]),
            review_band_width=float(frame["review_band_width"].iloc[0]),
            uncertainty_threshold=uncertainty_threshold,
            total_action_cap=REFERENCE_AUTO_CAP + REFERENCE_REVIEW_CAP,
        )
    else:
        routed_valid = route_frame(
            _routing_projection(route_input),
            prompt_threshold=float(frame["prompt_threshold"].iloc[0]),
            automated_alert_cap=automated_alert_cap,
            review_cap=review_cap,
            review_band_width=float(frame["review_band_width"].iloc[0]),
            uncertainty_threshold=uncertainty_threshold,
            uncertainty_mode="probability_margin",
        )
    if evidence_gate_on and (~valid).any():
        invalid = _routing_projection(frame[~valid])
        invalid["uncertainty_score"] = np.nan
        invalid["prompt_threshold"] = float(frame["prompt_threshold"].iloc[0])
        invalid["uncertainty_threshold"] = float(frame["uncertainty_threshold"].iloc[0])
        invalid["review_band_width"] = float(frame["review_band_width"].iloc[0])
        invalid["primary_route"] = "abstain"
        invalid["reason_code"] = np.where(
            invalid["evidence_status"].eq("missing"),
            "required_evidence_missing",
            "required_evidence_stale",
        )
        combined = pd.concat([routed_valid, invalid], ignore_index=True, sort=False)
    else:
        combined = routed_valid
    counter_cap = REFERENCE_AUTO_CAP + REFERENCE_REVIEW_CAP if shared_capacity else None
    combined = _recompute_counters_and_flags(
        combined,
        automated_alert_cap=(counter_cap or automated_alert_cap),
        review_cap=(counter_cap or review_cap),
    )
    if shared_capacity:
        per_participant_actions = (
            combined.groupby("subject_id")[["route_alert", "route_human_review"]]
            .sum()
            .sum(axis=1)
        )
        if (per_participant_actions > counter_cap).any():
            raise AssertionError("Shared action capacity was exceeded")
        combined["shared_action_cap"] = counter_cap
    else:
        combined["shared_action_cap"] = pd.NA
    combined["component_arm"] = arm
    combined["evidence_gate_enabled"] = evidence_gate_on
    combined["finite_capacity_enabled"] = capacity_on
    combined["uncertainty_gate_enabled"] = uncertainty_gate_on
    combined["capacity_architecture"] = (
        "shared_fifo_total_10" if shared_capacity else "separate_alert_review"
    )
    combined["route_computed_before_label_access"] = True
    return combined


def build_route_ablation(
    reference_routes: pd.DataFrame,
    *,
    seed: int,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    group_columns = [
        "dataset_id",
        "evaluation_scope",
        "model_name",
        "outer_fold",
        "prompt_threshold",
        "uncertainty_threshold",
        "review_band_width",
    ]
    for scenario in ("clean", "missing_stale_stress"):
        scenario_frame = add_evidence_status(
            reference_routes, seed=seed, scenario=scenario
        )
        for _, group in scenario_frame.groupby(group_columns, sort=True, dropna=False):
            for arm in ROUTING_ARMS:
                routed = route_component_arm(group, arm=arm)
                routed["evidence_scenario"] = scenario
                frames.append(routed)
    result = pd.concat(frames, ignore_index=True)
    keys = [
        "evidence_scenario",
        "component_arm",
        "dataset_id",
        "model_name",
        "subject_id",
        "trial_id",
    ]
    if result.duplicated(keys).any():
        raise AssertionError("Duplicate route-ablation decision keys")
    return result


def _invalid_evidence_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    invalid = ~frame["evidence_status"].eq("admitted")
    action = frame["primary_route"].isin(E1_ACTION_ROUTES)
    n_invalid = int(invalid.sum())
    n_invalid_action = int((invalid & action).sum())
    direct_gate_block = frame["reason_code"].isin(
        ("required_evidence_missing", "required_evidence_stale")
    )
    return {
        "n_invalid_evidence": n_invalid,
        "n_action_on_invalid_evidence": n_invalid_action,
        "invalid_evidence_action_acceptance_rate": (
            n_invalid_action / n_invalid if n_invalid else 0.0
        ),
        "n_invalid_evidence_forced_abstain": int(
            (invalid & frame["primary_route"].eq("abstain")).sum()
        ),
        "n_direct_evidence_gate_blocks": int(direct_gate_block.sum()),
        "direct_evidence_gate_blocks_per_100": 100.0 * float(direct_gate_block.mean()),
    }


def _separated_route_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    """Summarize automated alerts and human-review burden separately."""

    raw = policy_metrics(frame)
    y = frame["y_true"].to_numpy(dtype=int)
    review = frame["primary_route"].eq("human_review").to_numpy()
    event_reviews = int(y[review].sum()) if review.any() else 0
    non_event_reviews = int(review.sum()) - event_reviews
    positives = int(y.sum())
    n = len(frame)
    reason = frame["reason_code"]
    auto_blocks = int(
        reason.isin(
            (
                "auto_alert_capacity_exhausted",
                "alert_capacity_exhausted",
                "shared_capacity_exhausted_alert",
            )
        ).sum()
    )
    review_overflow = int(
        reason.isin(
            ("review_capacity_exhausted", "shared_capacity_exhausted_review")
        ).sum()
    )
    return {
        "n_decisions": int(raw["n_decisions"]),
        "n_positive": int(raw["n_positive"]),
        "n_alert": int(raw["n_alert"]),
        "n_true_alerts": int(raw["n_true_alerts"]),
        "n_false_alerts": int(raw["n_false_alerts"]),
        "n_human_review": int(raw["n_human_review"]),
        "n_event_human_reviews": event_reviews,
        "n_non_event_human_reviews": non_event_reviews,
        "n_abstain": int(raw["n_abstain"]),
        "n_no_action": int(raw["n_no_action"]),
        "n_auto_capacity_blocks": auto_blocks,
        "n_review_capacity_overflow_abstentions": review_overflow,
        "alert_rate": float(raw["alert_rate"]),
        "human_review_rate": float(raw["human_review_rate"]),
        "abstain_rate": float(raw["abstain_rate"]),
        "no_action_rate": float(raw["no_action_rate"]),
        "event_coverage_by_alert": float(raw["event_coverage_by_alert"]),
        "alert_precision": float(raw["alert_precision"]),
        "false_alerts_per_100": float(raw["false_alerts_per_100"]),
        "event_coverage_by_human_review": (
            event_reviews / positives if positives else np.nan
        ),
        "non_event_human_reviews_per_100": 100.0 * non_event_reviews / n,
        "auto_capacity_blocks_per_100": 100.0 * auto_blocks / n,
        "review_capacity_overflow_abstentions_per_100": 100.0 * review_overflow / n,
        "route_rate_sum": float(raw["route_rate_sum"]),
    }


def _participant_burden_metrics(frame: pd.DataFrame) -> dict[str, float]:
    burden = (
        frame.assign(
            alert=frame["primary_route"].eq("alert").astype(int),
            review=frame["primary_route"].eq("human_review").astype(int),
        )
        .groupby("subject_id", sort=True)[["alert", "review"]]
        .sum()
    )
    output: dict[str, float] = {}
    for column, label in (("alert", "alerts"), ("review", "reviews")):
        values = burden[column].to_numpy(dtype=float)
        output[f"participant_{label}_median"] = float(np.median(values))
        output[f"participant_{label}_q1"] = float(np.percentile(values, 25))
        output[f"participant_{label}_q3"] = float(np.percentile(values, 75))
        output[f"participant_{label}_p90"] = float(np.percentile(values, 90))
    return output


def participant_route_metrics(routes: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        "evidence_scenario",
        "component_arm",
        "dataset_id",
        "evaluation_scope",
        "model_name",
        "subject_id",
    ]
    rows: list[dict[str, object]] = []
    for keys, frame in routes.groupby(group_columns, sort=True):
        rows.append(
            {
                **dict(zip(group_columns, keys, strict=True)),
                **_separated_route_metrics(frame),
                **_invalid_evidence_metrics(frame),
            }
        )
    return pd.DataFrame(rows)


def route_ablation_metrics(routes: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        "evidence_scenario",
        "component_arm",
        "dataset_id",
        "evaluation_scope",
        "model_name",
    ]
    rows: list[dict[str, object]] = []
    for keys, frame in routes.groupby(group_columns, sort=True):
        full = routes[
            routes["evidence_scenario"].eq(keys[0])
            & routes["component_arm"].eq("full_controls")
            & routes["dataset_id"].eq(keys[2])
            & routes["evaluation_scope"].eq(keys[3])
            & routes["model_name"].eq(keys[4])
        ][["subject_id", "trial_id", "primary_route"]].rename(
            columns={"primary_route": "full_route"}
        )
        comparison = frame.merge(
            full,
            on=["subject_id", "trial_id"],
            how="left",
            validate="one_to_one",
        )
        route_agreement = float(
            comparison["primary_route"].eq(comparison["full_route"]).mean()
        )
        rows.append(
            {
                **dict(zip(group_columns, keys, strict=True)),
                "n_participants": int(frame["subject_id"].nunique()),
                **_separated_route_metrics(frame),
                **_invalid_evidence_metrics(frame),
                **_participant_burden_metrics(frame),
                "route_agreement_with_full": route_agreement,
                "prediction_scores_changed": False,
                "predictive_metric_credit_applicable": False,
            }
        )
    return pd.DataFrame(rows)


ROUTE_DELTA_METRICS = (
    "alert_rate",
    "human_review_rate",
    "abstain_rate",
    "no_action_rate",
    "event_coverage_by_alert",
    "alert_precision",
    "false_alerts_per_100",
    "event_coverage_by_human_review",
    "non_event_human_reviews_per_100",
    "auto_capacity_blocks_per_100",
    "review_capacity_overflow_abstentions_per_100",
    "invalid_evidence_action_acceptance_rate",
    "direct_evidence_gate_blocks_per_100",
)


def route_metric_deltas(metrics: pd.DataFrame) -> pd.DataFrame:
    identifiers = [
        "evidence_scenario",
        "dataset_id",
        "evaluation_scope",
        "model_name",
    ]
    rows: list[dict[str, object]] = []
    for keys, frame in metrics.groupby(identifiers, sort=True):
        reference = frame[frame["component_arm"].eq("full_controls")]
        if len(reference) != 1:
            raise AssertionError("Expected one full-control metric row")
        reference_row = reference.iloc[0]
        for row in frame.itertuples(index=False):
            if row.component_arm == "full_controls":
                continue
            for metric in ROUTE_DELTA_METRICS:
                rows.append(
                    {
                        **dict(zip(identifiers, keys, strict=True)),
                        "component_arm": row.component_arm,
                        "reference_arm": "full_controls",
                        "metric": metric,
                        "arm_value": float(getattr(row, metric)),
                        "reference_value": float(reference_row[metric]),
                        "delta_arm_minus_full": float(
                            getattr(row, metric) - reference_row[metric]
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _metrics_from_totals(totals: pd.Series) -> dict[str, float]:
    def ratio(numerator: str, denominator: str, scale: float = 1.0) -> float:
        value = float(totals[denominator])
        return scale * float(totals[numerator]) / value if value else np.nan

    return {
        "alert_rate": ratio("n_alert", "n_decisions"),
        "human_review_rate": ratio("n_human_review", "n_decisions"),
        "abstain_rate": ratio("n_abstain", "n_decisions"),
        "no_action_rate": ratio("n_no_action", "n_decisions"),
        "event_coverage_by_alert": ratio("n_true_alerts", "n_positive"),
        "alert_precision": ratio("n_true_alerts", "n_alert"),
        "false_alerts_per_100": ratio("n_false_alerts", "n_decisions", 100.0),
        "event_coverage_by_human_review": ratio("n_event_human_reviews", "n_positive"),
        "non_event_human_reviews_per_100": ratio(
            "n_non_event_human_reviews", "n_decisions", 100.0
        ),
        "auto_capacity_blocks_per_100": ratio(
            "n_auto_capacity_blocks", "n_decisions", 100.0
        ),
        "review_capacity_overflow_abstentions_per_100": ratio(
            "n_review_capacity_overflow_abstentions", "n_decisions", 100.0
        ),
        "invalid_evidence_action_acceptance_rate": ratio(
            "n_action_on_invalid_evidence", "n_invalid_evidence"
        )
        if float(totals["n_invalid_evidence"])
        else 0.0,
        "direct_evidence_gate_blocks_per_100": ratio(
            "n_direct_evidence_gate_blocks", "n_decisions", 100.0
        ),
    }


_BOOTSTRAP_RATIO_COLUMNS = {
    "alert_rate": ("n_alert", "n_decisions", 1.0, np.nan),
    "human_review_rate": ("n_human_review", "n_decisions", 1.0, np.nan),
    "abstain_rate": ("n_abstain", "n_decisions", 1.0, np.nan),
    "no_action_rate": ("n_no_action", "n_decisions", 1.0, np.nan),
    "event_coverage_by_alert": ("n_true_alerts", "n_positive", 1.0, np.nan),
    "alert_precision": ("n_true_alerts", "n_alert", 1.0, np.nan),
    "false_alerts_per_100": ("n_false_alerts", "n_decisions", 100.0, np.nan),
    "event_coverage_by_human_review": (
        "n_event_human_reviews",
        "n_positive",
        1.0,
        np.nan,
    ),
    "non_event_human_reviews_per_100": (
        "n_non_event_human_reviews",
        "n_decisions",
        100.0,
        np.nan,
    ),
    "auto_capacity_blocks_per_100": (
        "n_auto_capacity_blocks",
        "n_decisions",
        100.0,
        np.nan,
    ),
    "review_capacity_overflow_abstentions_per_100": (
        "n_review_capacity_overflow_abstentions",
        "n_decisions",
        100.0,
        np.nan,
    ),
    "invalid_evidence_action_acceptance_rate": (
        "n_action_on_invalid_evidence",
        "n_invalid_evidence",
        1.0,
        0.0,
    ),
    "direct_evidence_gate_blocks_per_100": (
        "n_direct_evidence_gate_blocks",
        "n_decisions",
        100.0,
        np.nan,
    ),
}


def _bootstrap_metric_vector(
    totals: np.ndarray,
    count_columns: Sequence[str],
    metric: str,
) -> np.ndarray:
    numerator, denominator, scale, zero_value = _BOOTSTRAP_RATIO_COLUMNS[metric]
    column_index = {name: index for index, name in enumerate(count_columns)}
    numerator_values = totals[:, column_index[numerator]]
    denominator_values = totals[:, column_index[denominator]]
    output = np.full(len(totals), zero_value, dtype=float)
    np.divide(
        scale * numerator_values,
        denominator_values,
        out=output,
        where=denominator_values != 0,
    )
    return output


def paired_participant_bootstrap(
    participants: pd.DataFrame,
    *,
    replicates: int,
    seed: int,
) -> pd.DataFrame:
    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    count_columns = [
        "n_decisions",
        "n_positive",
        "n_alert",
        "n_true_alerts",
        "n_false_alerts",
        "n_human_review",
        "n_event_human_reviews",
        "n_non_event_human_reviews",
        "n_abstain",
        "n_no_action",
        "n_auto_capacity_blocks",
        "n_review_capacity_overflow_abstentions",
        "n_invalid_evidence",
        "n_action_on_invalid_evidence",
        "n_direct_evidence_gate_blocks",
    ]
    identifiers = [
        "evidence_scenario",
        "dataset_id",
        "evaluation_scope",
        "model_name",
    ]
    rows: list[dict[str, object]] = []
    for group_index, (keys, group) in enumerate(
        participants.groupby(identifiers, sort=True)
    ):
        pivot = group.set_index(["component_arm", "subject_id"])
        subjects = sorted(group["subject_id"].unique())
        rng = np.random.default_rng(seed + group_index * 10_000)
        sample_weights = rng.multinomial(
            len(subjects),
            np.full(len(subjects), 1.0 / len(subjects)),
            size=replicates,
        )
        arm_matrices: dict[str, np.ndarray] = {}
        arm_points: dict[str, dict[str, float]] = {}
        for arm in ROUTING_ARMS:
            arm_frame = pivot.loc[arm].reindex(subjects)
            if arm_frame[count_columns].isna().any().any():
                raise AssertionError("Unmatched participants in paired bootstrap")
            matrix = arm_frame[count_columns].to_numpy(dtype=float)
            arm_matrices[arm] = sample_weights @ matrix
            arm_points[arm] = _metrics_from_totals(arm_frame[count_columns].sum())
        for arm in ROUTING_ARMS:
            if arm == "full_controls":
                continue
            for metric in ROUTE_DELTA_METRICS:
                replicate_deltas = _bootstrap_metric_vector(
                    arm_matrices[arm], count_columns, metric
                ) - _bootstrap_metric_vector(
                    arm_matrices["full_controls"], count_columns, metric
                )
                finite = replicate_deltas[np.isfinite(replicate_deltas)]
                rows.append(
                    {
                        **dict(zip(identifiers, keys, strict=True)),
                        "component_arm": arm,
                        "reference_arm": "full_controls",
                        "metric": metric,
                        "delta_arm_minus_full": (
                            arm_points[arm][metric]
                            - arm_points["full_controls"][metric]
                        ),
                        "ci_low": float(np.percentile(finite, 2.5))
                        if len(finite)
                        else np.nan,
                        "ci_high": float(np.percentile(finite, 97.5))
                        if len(finite)
                        else np.nan,
                        "bootstrap_unit": "participant",
                        "bootstrap_method": "paired cluster percentile",
                        "bootstrap_replicates": replicates,
                        "bootstrap_seed": seed + group_index * 10_000,
                    }
                )
    return pd.DataFrame(rows)


RUNTIME_NOW = "2026-01-01T00:00:10Z"
RUNTIME_EXECUTION_TIME = "2026-01-01T00:00:11Z"
RUNTIME_MODEL_HASH = "a" * 64


@dataclass(frozen=True)
class RuntimeFixture:
    policy: PolicyManifest
    ledger: SQLiteCapacityLedger
    permits: tuple[DecisionPermit, ...]
    receipts: tuple[ExecutionReceipt, ...]
    trusted_tail_hash: str


def _runtime_policy() -> PolicyManifest:
    return PolicyManifest(
        policy_id="ecrc-component-ablation-runtime-v1",
        revision=1,
        issuer_id="deterministic-conformance-authority",
        effective_from="2026-01-01T00:00:00Z",
        expires_at="2026-01-02T00:00:00Z",
        approved_models=(ModelBinding("frozen-conformance-model", RUNTIME_MODEL_HASH),),
        evidence_rules=(
            EvidenceRule(
                evidence_type="behavior_score",
                allowed_sources=("frozen-heldout-pipeline",),
                allowed_schema_versions=("1.0",),
                max_age_seconds=60,
                use_allowed=True,
            ),
        ),
        score_threshold=0.60,
        uncertainty_threshold=0.80,
        review_band_width=0.05,
        alert_capacity=64,
        review_capacity=64,
        capacity_scope="subject_session",
        claim_rules=(
            ClaimRule(
                "task_alert", ("alert",), required_evidence_types=("behavior_score",)
            ),
            ClaimRule(
                "task_review", ("review",), required_evidence_types=("behavior_score",)
            ),
            ClaimRule("task_abstention", ("abstain",)),
            ClaimRule("task_no_action", ("no_action",)),
        ),
        blocked_claim_ids=("clinical_diagnosis", "intervention_efficacy"),
    )


def _runtime_proposal(
    decision_id: str, score: float, uncertainty: float
) -> ProposalEnvelope:
    return ProposalEnvelope(
        decision_id=decision_id,
        subject_id="deterministic-subject",
        session_id="deterministic-session",
        model_id="frozen-conformance-model",
        model_version="1.0",
        model_hash=RUNTIME_MODEL_HASH,
        score=score,
        uncertainty=uncertainty,
        proposed_action="alert",
        proposed_at="2026-01-01T00:00:05Z",
        input_hash=canonical_hash({"decision_id": decision_id}),
        validation_scope_id="deterministic-conformance-decision",
    )


def _runtime_evidence(decision_id: str) -> EvidenceEnvelope:
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
        ),
    )


def build_runtime_fixture(database_path: Path) -> RuntimeFixture:
    """Issue and consume a deterministic sample through the real ECRC stack."""

    if database_path.exists():
        database_path.unlink()
    policy = _runtime_policy()
    ledger = SQLiteCapacityLedger(database_path)
    ledger.register_policy(policy)
    adjudicator = OrderedAdjudicator(ledger)
    pep = PEPSimulator(ledger, enforcement_point_id="component-ablation-pep")
    route_inputs = (
        ("alert", 0.90, 0.10),
        ("review", 0.62, 0.10),
        ("abstain", 0.90, 0.90),
        ("no_action", 0.20, 0.10),
    )
    permits: list[DecisionPermit] = []
    receipts: list[ExecutionReceipt] = []
    for index in range(32):
        expected_route, score, uncertainty = route_inputs[index % len(route_inputs)]
        decision_id = f"runtime-{index + 1:03d}"
        permit = adjudicator.adjudicate(
            policy,
            _runtime_proposal(decision_id, score, uncertainty),
            _runtime_evidence(decision_id),
            at=RUNTIME_NOW,
        )
        if permit.route != expected_route:
            raise AssertionError(
                f"Runtime fixture route {permit.route!r} != {expected_route!r}"
            )
        receipt = pep.execute(policy, permit, at=RUNTIME_EXECUTION_TIME)
        permits.append(permit)
        receipts.append(receipt)
    trusted_tail = ledger.tail_receipt_hash()
    StatefulReceiptVerifier().verify_chain(
        receipts,
        {permit.permit_id: permit for permit in permits},
        expected_tail_hash=trusted_tail,
    )
    counts = ledger.counts()
    if counts.issued_permits != 32 or counts.executions != 32 or counts.receipts != 32:
        raise AssertionError("Runtime ledger counts do not match the issued sample")
    return RuntimeFixture(
        policy=policy,
        ledger=ledger,
        permits=tuple(permits),
        receipts=tuple(receipts),
        trusted_tail_hash=trusted_tail,
    )


@dataclass(frozen=True)
class RecordFaultCase:
    case_id: str
    fault_family: str
    expected_component: str
    fault_stage: str
    source_decision_id: str
    target_position: int
    permits: tuple[DecisionPermit, ...]
    receipts: tuple[ExecutionReceipt, ...]


def _ranked_candidates(
    candidates: Iterable[int],
    *,
    family: str,
    seed: int,
    count: int,
) -> list[int]:
    ranked = sorted(
        candidates,
        key=lambda item: (stable_hash(seed, family, item), item),
    )
    if len(ranked) < count:
        raise ValueError(f"Only {len(ranked)} eligible {family} cases; need {count}")
    return ranked[:count]


def build_record_fault_cases(
    fixture: RuntimeFixture,
    *,
    seed: int,
    cases_per_family: int,
) -> tuple[RecordFaultCase, ...]:
    all_candidates = list(range(len(fixture.permits)))
    nonfirst_candidates = list(range(1, len(fixture.receipts)))
    nonlast_candidates = list(range(len(fixture.receipts) - 1))
    executed_candidates = [
        position
        for position, receipt in enumerate(fixture.receipts)
        if receipt.execution_status == "executed"
    ]
    cases: list[RecordFaultCase] = []
    for family_index, family in enumerate(FAULT_FAMILIES, 1):
        if family == "previous_receipt_hash_tamper":
            candidates = nonfirst_candidates
        elif family == "side_effect_id_tamper":
            candidates = executed_candidates
        elif family in {"receipt_reorder", "permit_replay"}:
            candidates = nonlast_candidates
        else:
            candidates = all_candidates
        selected = _ranked_candidates(
            candidates,
            family=family,
            seed=seed,
            count=cases_per_family,
        )
        for ordinal, position in enumerate(selected, 1):
            permits = list(fixture.permits)
            receipts = list(fixture.receipts)
            source_decision = permits[position].decision_id
            if family == "claim_scope_substitution":
                permits[position] = replace(
                    permits[position], permitted_claim_ids=("forged_scope_claim",)
                )
            elif family == "evidence_hash_substitution":
                permits[position] = replace(permits[position], evidence_hash="f" * 64)
            elif family == "side_effect_id_tamper":
                receipts[position] = replace(
                    receipts[position], side_effect_id=f"tampered-{position:03d}"
                )
            elif family == "previous_receipt_hash_tamper":
                receipts[position] = replace(
                    receipts[position], previous_receipt_hash="f" * 64
                )
            elif family == "receipt_reorder":
                receipts[position], receipts[position + 1] = (
                    receipts[position + 1],
                    receipts[position],
                )
            elif family == "permit_replay":
                receipts.insert(position + 1, receipts[position])
            elif family == "missing_receipt":
                del receipts[position]
            else:
                raise AssertionError(f"Unhandled fault family {family}")
            fault_stage = (
                "pre_execution_permit"
                if family in CLAIM_FAULTS
                else "post_execution_receipt"
            )
            case_receipts = () if family in CLAIM_FAULTS else tuple(receipts)
            cases.append(
                RecordFaultCase(
                    case_id=f"B-{family_index:02d}-{ordinal:03d}",
                    fault_family=family,
                    expected_component=(
                        "trusted_permit_claim_binding"
                        if family in CLAIM_FAULTS
                        else "stateful_receipt_verification"
                    ),
                    fault_stage=fault_stage,
                    source_decision_id=source_decision,
                    target_position=position,
                    permits=tuple(permits),
                    receipts=case_receipts,
                )
            )
    return tuple(cases)


def _typed_structure_failures(case: RecordFaultCase) -> tuple[str, ...]:
    failures: list[str] = []
    for position, permit in enumerate(case.permits):
        try:
            DecisionPermit.from_dict(permit.to_dict())
        except (KeyError, TypeError, ValueError) as exc:
            failures.append(f"PERMIT_SCHEMA:{position}:{type(exc).__name__}")
    for position, receipt in enumerate(case.receipts):
        try:
            ExecutionReceipt.from_dict(receipt.to_dict())
        except (KeyError, TypeError, ValueError) as exc:
            failures.append(f"RECEIPT_SCHEMA:{position}:{type(exc).__name__}")
    return tuple(failures)


def validator_failures(
    fixture: RuntimeFixture,
    case: RecordFaultCase,
    validator: str,
) -> tuple[str, ...]:
    if validator not in RECORD_VALIDATORS:
        raise ValueError(f"Unknown record validator {validator!r}")
    failures = list(_typed_structure_failures(case))
    claim_binding_enabled = validator in {
        "receipt_state_verification_off",
        "full_binding_and_receipt",
    }
    receipt_verification_enabled = validator in {
        "claim_binding_off",
        "full_binding_and_receipt",
    }
    if claim_binding_enabled:
        pep = PEPSimulator(fixture.ledger, enforcement_point_id="ablation-verifier")
        for position, permit in enumerate(case.permits):
            try:
                fixture.ledger.assert_issued_permit(permit)
                pep.validate(fixture.policy, permit, at=RUNTIME_EXECUTION_TIME)
            except GovernanceError as exc:
                failures.append(
                    f"TRUSTED_PERMIT_BINDING:{position}:{type(exc).__name__}"
                )
    if receipt_verification_enabled and case.fault_stage == "post_execution_receipt":
        try:
            StatefulReceiptVerifier().verify_chain(
                case.receipts,
                {permit.permit_id: permit for permit in case.permits},
                expected_tail_hash=fixture.trusted_tail_hash,
            )
        except ReceiptVerificationError as exc:
            failures.append(f"STATEFUL_RECEIPT:{type(exc).__name__}")
    return tuple(failures)


def evaluate_record_ablation(
    fixture: RuntimeFixture,
    cases: Sequence[RecordFaultCase],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    clean_case = RecordFaultCase(
        case_id="B-CLEAN",
        fault_family="clean",
        expected_component="none",
        fault_stage="post_execution_receipt",
        source_decision_id="none",
        target_position=-1,
        permits=fixture.permits,
        receipts=fixture.receipts,
    )
    clean_rows = []
    for validator in RECORD_VALIDATORS:
        failures = validator_failures(fixture, clean_case, validator)
        clean_rows.append(
            {
                "validator": validator,
                "n_clean_records": len(fixture.receipts),
                "n_clean_failures": len(failures),
                "clean_false_positive_rate": len(failures) / len(fixture.receipts),
            }
        )

    case_rows: list[dict[str, object]] = []
    manifest_rows: list[dict[str, object]] = []
    for case in cases:
        record_payload = json.dumps(
            {
                "permits": [permit.to_dict() for permit in case.permits],
                "receipts": [receipt.to_dict() for receipt in case.receipts],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        manifest_rows.append(
            {
                "case_id": case.case_id,
                "fault_family": case.fault_family,
                "expected_component": case.expected_component,
                "fault_stage": case.fault_stage,
                "source_decision_id": case.source_decision_id,
                "target_position": case.target_position,
                "n_case_permits": len(case.permits),
                "n_case_receipts": len(case.receipts),
                "case_sha256": hashlib.sha256(record_payload).hexdigest(),
                "structurally_valid": not bool(_typed_structure_failures(case)),
            }
        )
        for validator in RECORD_VALIDATORS:
            failures = validator_failures(fixture, case, validator)
            case_rows.append(
                {
                    "case_id": case.case_id,
                    "fault_family": case.fault_family,
                    "expected_component": case.expected_component,
                    "fault_stage": case.fault_stage,
                    "validator": validator,
                    "detected": bool(failures),
                    "n_findings": len(failures),
                    "finding_codes": ";".join(sorted(set(failures))),
                }
            )
    case_results = pd.DataFrame(case_rows)
    family_summary = (
        case_results.groupby(
            ["fault_family", "expected_component", "validator"], sort=True
        )
        .agg(n_cases=("case_id", "size"), n_detected=("detected", "sum"))
        .reset_index()
    )
    family_summary["sensitivity"] = (
        family_summary["n_detected"] / family_summary["n_cases"]
    )
    component_summary = (
        case_results.groupby(["expected_component", "validator"], sort=True)
        .agg(n_cases=("case_id", "size"), n_detected=("detected", "sum"))
        .reset_index()
    )
    component_summary["sensitivity"] = (
        component_summary["n_detected"] / component_summary["n_cases"]
    )
    return (
        pd.DataFrame(clean_rows),
        pd.DataFrame(manifest_rows),
        case_results,
        family_summary,
        component_summary,
    )


def assert_route_ablation_contract(
    routes: pd.DataFrame,
    reference_routes: pd.DataFrame,
) -> dict[str, object]:
    key = ["dataset_id", "model_name", "subject_id", "trial_id"]
    clean_full = routes[
        routes["evidence_scenario"].eq("clean")
        & routes["component_arm"].eq("full_controls")
    ]
    clean_gate_off = routes[
        routes["evidence_scenario"].eq("clean")
        & routes["component_arm"].eq("evidence_gate_off")
    ]
    full_compare = clean_full[key + ["primary_route", "reason_code"]].merge(
        reference_routes[key + ["primary_route", "reason_code"]],
        on=key,
        suffixes=("_ablation", "_e1"),
        validate="one_to_one",
    )
    reference_match = bool(
        full_compare["primary_route_ablation"]
        .eq(full_compare["primary_route_e1"])
        .all()
        and full_compare["reason_code_ablation"]
        .eq(full_compare["reason_code_e1"])
        .all()
    )
    gate_compare = clean_full[key + ["primary_route", "reason_code"]].merge(
        clean_gate_off[key + ["primary_route", "reason_code"]],
        on=key,
        suffixes=("_full", "_gate_off"),
        validate="one_to_one",
    )
    clean_gate_equivalence = bool(
        gate_compare["primary_route_full"]
        .eq(gate_compare["primary_route_gate_off"])
        .all()
        and gate_compare["reason_code_full"]
        .eq(gate_compare["reason_code_gate_off"])
        .all()
    )
    stress_full = routes[
        routes["evidence_scenario"].eq("missing_stale_stress")
        & routes["component_arm"].eq("full_controls")
    ]
    invalid = ~stress_full["evidence_status"].eq("admitted")
    invalid_actions = int(
        (invalid & stress_full["primary_route"].isin(E1_ACTION_ROUTES)).sum()
    )
    capacity_off = routes[routes["component_arm"].eq("capacity_off")]
    capacity_blocks = int(
        capacity_off["reason_code"]
        .isin(
            (
                "auto_alert_capacity_exhausted",
                "alert_capacity_exhausted",
                "review_capacity_exhausted",
                "shared_capacity_exhausted_alert",
                "shared_capacity_exhausted_review",
            )
        )
        .sum()
    )
    uncertainty_off = routes[
        routes["component_arm"].eq("uncertainty_gate_off")
        & routes["evidence_status"].eq("admitted")
    ]
    uncertainty_blocks = int(
        uncertainty_off["reason_code"].eq("uncertainty_gate").sum()
    )
    shared = routes[routes["component_arm"].eq("shared_capacity")]
    shared_usage = (
        shared.groupby(["evidence_scenario", "dataset_id", "model_name", "subject_id"])[
            ["route_alert", "route_human_review"]
        ]
        .sum()
        .sum(axis=1)
    )
    shared_capacity_exceeded = bool(
        (shared_usage > REFERENCE_AUTO_CAP + REFERENCE_REVIEW_CAP).any()
    )
    route_flags = [f"route_{name}" for name in PRIMARY_ROUTES]
    exclusive = bool(routes[route_flags].sum(axis=1).eq(1).all())
    if not reference_match:
        raise AssertionError("Clean full-control replay differs from E1 cap-8 routes")
    if not clean_gate_equivalence:
        raise AssertionError("Evidence gate changed clean admitted-evidence routes")
    if invalid_actions:
        raise AssertionError("Full evidence gate permitted action on invalid evidence")
    if capacity_blocks:
        raise AssertionError("Capacity-off arm still produced capacity blocks")
    if uncertainty_blocks:
        raise AssertionError("Uncertainty-gate-off arm still gated admitted evidence")
    if shared_capacity_exceeded:
        raise AssertionError("Shared-capacity arm exceeded total quota 10")
    if not exclusive:
        raise AssertionError("Component-ablation routes are not exclusive")
    return {
        "clean_full_matches_e1_cap8_routes": reference_match,
        "clean_evidence_gate_off_matches_full": clean_gate_equivalence,
        "full_gate_invalid_evidence_action_count": invalid_actions,
        "capacity_off_capacity_block_count": capacity_blocks,
        "uncertainty_gate_off_admitted_evidence_blocks": uncertainty_blocks,
        "shared_capacity_total_quota_exceeded": shared_capacity_exceeded,
        "all_routes_mutually_exclusive_and_exhaustive": exclusive,
        "prediction_scores_changed_across_arms": False,
        "runtime_labels_consulted": False,
    }


def _notes() -> str:
    return """# Matched component-ablation evidence

This directory contains two separate evaluation axes over the frozen E1
proposal stream. The final run reads `evidence_v2/route_assignments.csv.gz`:
Many Labs participant-grouped outer-CV proposals plus the frozen external
official Mendeley v2 replay (`mendeley_igt_official_v2`).

## Routing/resource axis

- `full_controls`: uncertainty routing, evidence admission, alert cap 8 and
  review cap 2.
- `evidence_gate_off`: identical settings, but deterministic missing/stale
  evidence is ignored.
- `uncertainty_gate_off`: identical evidence and separate capacities, but the
  uncertainty threshold is disabled.
- `shared_capacity`: the same candidate rules use one per-participant FIFO
  action pool of 10 slots (8 alert + 2 review in the reference). Review
  overflow abstains; alert overflow becomes no action.
- `capacity_off`: evidence admission remains fail-closed, while both alert and
  review capacities are effectively unbounded.

The evidence stress is a deterministic conformance fixture: SHA-256 assignment
marks one twentieth of decisions missing and one twentieth stale, independently
of model score and posthoc label. It is not an estimate of real missingness.
Clean admitted-evidence results are reported separately.

Routing components are evaluated with automated-alert outcomes and human-review
burden reported separately. Proposal scores are identical across arms, so the
ablation does not credit any component with predictive improvement. The shared
arm estimates the consequence of pooling the same nominal total quota under
FIFO; it does not establish that 10 is optimal or that shared capacity is
generally preferable.

## Record/state axis

Thirty-two deterministic decisions are sent through the repository's actual
`OrderedAdjudicator -> SQLiteCapacityLedger -> PEPSimulator` path. The resulting
issued permits and receipts are checked by `StatefulReceiptVerifier` against the
ledger's trusted tail. Four validation arms compare ordinary typed parsing,
claim binding bypassed, receipt/state verification bypassed, and both checks.
Typed claim/evidence substitutions occur pre-execution; typed receipt
mutation/reorder/replay/omission cases occur post-execution. These components
are evaluated only by clean false positives and prespecified fault sensitivity.

The PEP simulates side effects inside SQLite. These records do not show external
action execution, atomicity with a real alert service, legal authorisation,
tamper-proof storage, or unknown-fault coverage.
"""


def main() -> int:
    args = parse_args()
    if args.bootstrap_replicates < 1 or args.faults_per_family < 1:
        raise ValueError("bootstrap replicates and faults per family must be positive")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("load frozen E1 cap-8 routes", flush=True)
    reference = load_reference_routes(args.routes)
    print("run matched routing/resource arms", flush=True)
    route_assignments = build_route_ablation(reference, seed=args.seed)
    route_checks = assert_route_ablation_contract(route_assignments, reference)
    route_participants = participant_route_metrics(route_assignments)
    route_metrics = route_ablation_metrics(route_assignments)
    route_deltas = route_metric_deltas(route_metrics)
    print("paired participant bootstrap", flush=True)
    route_bootstrap = paired_participant_bootstrap(
        route_participants,
        replicates=args.bootstrap_replicates,
        seed=args.seed,
    )

    print("build real ECRC runtime conformance fixture", flush=True)
    runtime_database = output_dir / "runtime_ledger.sqlite"
    record_fixture = build_runtime_fixture(runtime_database)
    cases = build_record_fault_cases(
        record_fixture,
        seed=args.seed,
        cases_per_family=args.faults_per_family,
    )
    repeated_cases = build_record_fault_cases(
        record_fixture,
        seed=args.seed,
        cases_per_family=args.faults_per_family,
    )
    if cases != repeated_cases:
        raise AssertionError("Record-fault fixture is not deterministic")
    (
        record_clean,
        record_manifest,
        record_case_results,
        record_family_summary,
        record_component_summary,
    ) = evaluate_record_ablation(record_fixture, cases)
    if record_clean["n_clean_failures"].sum() != 0:
        raise AssertionError("A record validator raised a clean false positive")

    artifacts: list[Path] = []
    artifacts.append(
        write_csv(output_dir / "route_component_metrics.csv", route_metrics)
    )
    artifacts.append(write_csv(output_dir / "route_component_deltas.csv", route_deltas))
    artifacts.append(
        write_csv(output_dir / "route_component_bootstrap.csv", route_bootstrap)
    )
    artifacts.append(
        write_csv(output_dir / "route_component_participant.csv", route_participants)
    )
    route_columns = [
        "evidence_scenario",
        "component_arm",
        "dataset_id",
        "evaluation_scope",
        "model_name",
        "subject_id",
        "trial_id",
        "outer_fold",
        "y_true",
        "score",
        "evidence_status",
        "primary_route",
        "reason_code",
        "automated_alert_cap",
        "review_cap",
        *[f"route_{name}" for name in PRIMARY_ROUTES],
        "evidence_gate_enabled",
        "finite_capacity_enabled",
        "uncertainty_gate_enabled",
        "capacity_architecture",
        "shared_action_cap",
        "route_computed_before_label_access",
    ]
    artifacts.append(
        write_gzip_csv(
            output_dir / "route_component_assignments.csv.gz",
            route_assignments[route_columns],
        )
    )
    artifacts.append(
        write_json(output_dir / "runtime_policy.json", record_fixture.policy.to_dict())
    )
    artifacts.append(
        write_json(
            output_dir / "runtime_permits.json",
            [permit.to_dict() for permit in record_fixture.permits],
        )
    )
    artifacts.append(
        write_json(
            output_dir / "runtime_receipts.json",
            [receipt.to_dict() for receipt in record_fixture.receipts],
        )
    )
    artifacts.append(runtime_database)
    artifacts.append(
        write_csv(output_dir / "record_clean_validator_summary.csv", record_clean)
    )
    artifacts.append(
        write_csv(output_dir / "record_fault_manifest.csv", record_manifest)
    )
    artifacts.append(
        write_csv(output_dir / "record_fault_case_results.csv", record_case_results)
    )
    artifacts.append(
        write_csv(output_dir / "record_fault_family_summary.csv", record_family_summary)
    )
    artifacts.append(
        write_csv(output_dir / "record_component_summary.csv", record_component_summary)
    )
    contract = {
        "experiment": "matched_component_ablation",
        "script_version": SCRIPT_VERSION,
        "routing_axis": {
            "arms": list(ROUTING_ARMS),
            "scenarios": ["clean", "missing_stale_stress"],
            "reference_auto_cap": REFERENCE_AUTO_CAP,
            "reference_review_cap": REFERENCE_REVIEW_CAP,
            "shared_capacity_estimand": (
                "route/workload difference under one FIFO quota of 10 versus "
                "separate FIFO alert=8 and review=2 quotas, conditional on frozen proposals"
            ),
            "shared_overflow_routes": {
                "alert_candidate": "no_action",
                "review_candidate": "abstain",
            },
            "evidence_stress_assignment": (
                "SHA256(dataset_id, subject_id, trial_id, seed) mod 20; "
                "0=missing, 1=stale, otherwise admitted"
            ),
            "evidence_stress_is_real_prevalence_estimate": False,
            "outcomes": list(ROUTE_DELTA_METRICS),
            "proposal_scores_refit_or_changed": False,
        },
        "record_axis": {
            "validators": list(RECORD_VALIDATORS),
            "claim_faults": list(CLAIM_FAULTS),
            "receipt_faults": list(RECEIPT_FAULTS),
            "faults_per_family": args.faults_per_family,
            "fixture": (
                "32 deterministic decisions issued and consumed through the real "
                "ECRC adjudicator, trusted SQLite ledger, PEP simulator, and verifier"
            ),
            "fault_stages": {
                "claim_faults": "pre_execution_permit",
                "receipt_faults": "post_execution_receipt",
            },
            "outcomes": ["clean_false_positive_rate", "fault_sensitivity"],
            "predictive_metrics_applicable": False,
        },
        "boundaries": [
            "No action reached a participant or operational system.",
            "The PEP side effect is simulated; receipts do not establish external execution.",
            "SQLite atomicity does not establish atomicity with an external service.",
            "Fault sensitivity applies only to the prespecified families.",
            "The evidence stress is a conformance fixture, not a prevalence estimate.",
            "No component receives credit for predictive improvement.",
        ],
    }
    artifacts.append(write_json(output_dir / "ablation_contract.json", contract))
    artifacts.append(
        write_json(output_dir / "route_validation_checks.json", route_checks)
    )
    code_paths = [
        Path(__file__),
        REPOSITORY_ROOT / "src" / "agentic_eeg_dm" / "governance" / "adjudicator.py",
        REPOSITORY_ROOT / "src" / "agentic_eeg_dm" / "governance" / "enforcement.py",
        REPOSITORY_ROOT / "src" / "agentic_eeg_dm" / "governance" / "ledger.py",
        REPOSITORY_ROOT / "src" / "agentic_eeg_dm" / "governance" / "models.py",
        REPOSITORY_ROOT / "src" / "agentic_eeg_dm" / "governance" / "verifier.py",
    ]
    code_hashes = pd.DataFrame(
        [
            {
                "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in code_paths
        ]
    )
    artifacts.append(write_csv(output_dir / "code_hashes.csv", code_hashes))
    input_hashes = pd.DataFrame(
        [
            {
                "path": str(args.routes.resolve()),
                "bytes": args.routes.stat().st_size,
                "sha256": sha256_file(args.routes),
            }
        ]
    )
    artifacts.append(write_csv(output_dir / "input_hashes.csv", input_hashes))
    notes_path = output_dir / "README.md"
    notes_path.write_text(_notes(), encoding="utf-8")
    artifacts.append(notes_path)

    summary = {
        "routing_rows": len(route_assignments),
        "routing_participants": int(route_assignments["subject_id"].nunique()),
        "routing_models": sorted(route_assignments["model_name"].unique()),
        "routing_datasets": sorted(route_assignments["dataset_id"].unique()),
        "route_checks": route_checks,
        "record_fixture_permits": len(record_fixture.permits),
        "record_fixture_receipts": len(record_fixture.receipts),
        "record_fixture_trusted_tail_hash": record_fixture.trusted_tail_hash,
        "record_fault_cases": len(cases),
        "record_fault_families": list(FAULT_FAMILIES),
        "record_clean_false_positives": int(record_clean["n_clean_failures"].sum()),
        "interpretation": (
            "Routing components affect route/workload properties; record/state "
            "components affect conformance-fault observability only."
        ),
    }
    artifacts.append(write_json(output_dir / "ablation_summary.json", summary))
    manifest_payload = {
        **summary,
        "experiment": "ECRC_matched_component_ablation",
        "script_version": SCRIPT_VERSION,
        "seed": args.seed,
        "bootstrap_replicates": args.bootstrap_replicates,
        "faults_per_family": args.faults_per_family,
        "source_route_sha256": sha256_file(args.routes),
        "contract": contract,
        "environment": environment_record(),
        "git": git_record(REPOSITORY_ROOT),
    }
    manifest_path, checksum_path = finalize_manifest(
        output_dir,
        manifest_payload=manifest_payload,
        artifact_paths=artifacts,
    )
    print(f"output: {output_dir}", flush=True)
    print(f"manifest: {manifest_path}", flush=True)
    print(f"checksums: {checksum_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
