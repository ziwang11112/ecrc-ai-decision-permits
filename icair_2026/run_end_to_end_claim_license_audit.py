#!/usr/bin/env python3
"""Build and audit an end-to-end claim-license trace on real held-out decisions.

The experiment deliberately separates two concepts that were previously easy to
conflate:

* runtime auto-alert and human-review capacities are separate pre-action,
  label-free count constraints; and
* the false-action limit is a posthoc validation criterion that requires observed
  proxy labels and can never affect a runtime route.

The four primary routes are mutually exclusive: alert, no_action, abstain, and
human_review.  The script also injects known trace violations and requires the
independent auditor to find every one while raising no alerts on clean traces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


SCRIPT_VERSION = "1.1.0"
N_OUTER_FOLDS = 5
PRIMARY_ROUTES = ("alert", "no_action", "abstain", "human_review")
ROUTE_FLAG_COLUMNS = tuple(f"route_{route}" for route in PRIMARY_ROUTES)
DEFAULT_SYSTEM_NAME = "nested_full_governed_policy"
DEFAULT_RUNTIME_AUTO_ALERT_CAP = 8
DEFAULT_RUNTIME_REVIEW_CAP = 2
DEFAULT_REVIEW_BAND_WIDTH = 0.03
DEFAULT_FALSE_ACTION_LIMIT_PER_100 = 9.0
DEFAULT_INJECTIONS_PER_TYPE = 100
DEFAULT_BOOTSTRAP_REPLICATES = 2000
DEFAULT_SEED = 20260622

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREDICTIONS = (
    REPO_ROOT
    / "outputs"
    / "many_labs_heldout_risk_estimator_benchmark"
    / "heldout_risk_predictions.csv"
)
DEFAULT_SELECTED_PARAMETERS = (
    REPO_ROOT
    / "manuscript"
    / "supplementary_tables"
    / "many_labs_nested_governed_policy_selected_parameters.csv"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "evidence"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument(
        "--selected-parameters", type=Path, default=DEFAULT_SELECTED_PARAMETERS
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--system-name", default=DEFAULT_SYSTEM_NAME)
    parser.add_argument(
        "--runtime-auto-alert-cap",
        type=int,
        default=DEFAULT_RUNTIME_AUTO_ALERT_CAP,
        help=(
            "Fixed pre-action automated-alert capacity per held-out participant "
            "segment; not optimized on held-out labels."
        ),
    )
    parser.add_argument(
        "--runtime-review-cap",
        type=int,
        default=DEFAULT_RUNTIME_REVIEW_CAP,
        help=(
            "Fixed pre-action human-review capacity per held-out participant "
            "segment; not optimized on held-out labels."
        ),
    )
    parser.add_argument(
        "--review-band-width",
        type=float,
        default=DEFAULT_REVIEW_BAND_WIDTH,
        help=(
            "Symmetric risk-score band around the train-selected prompt threshold "
            "that routes to human review; fixed without held-out-label tuning."
        ),
    )
    parser.add_argument(
        "--validation-false-action-limit-per-100",
        type=float,
        default=DEFAULT_FALSE_ACTION_LIMIT_PER_100,
    )
    parser.add_argument(
        "--injections-per-type", type=int, default=DEFAULT_INJECTIONS_PER_TYPE
    )
    parser.add_argument(
        "--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_array(values: Iterable[str]) -> str:
    return json.dumps(list(values), separators=(",", ":"), ensure_ascii=True)


def parse_json_array(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        raise ValueError(f"Expected a JSON list, got: {value!r}")
    return [str(item) for item in parsed]


def is_true(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_selected_parameters(path: Path, system_name: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing selected-parameter table: {path}")
    selected = pd.read_csv(path)
    required = {
        "heldout_fold",
        "system_name",
        "train_risk_model_name",
        "train_prompt_threshold",
        "train_uncertainty_threshold",
        "train_uncertainty_mode",
    }
    missing = required - set(selected.columns)
    if missing:
        raise ValueError(f"Missing selected-parameter columns: {sorted(missing)}")
    selected = selected[selected["system_name"].eq(system_name)].copy()
    if selected.empty:
        raise ValueError(f"No selected parameters for system_name={system_name!r}")
    selected["heldout_fold"] = pd.to_numeric(
        selected["heldout_fold"], errors="raise"
    ).astype(int)
    if selected["heldout_fold"].duplicated().any():
        raise ValueError("Expected exactly one selected-parameter row per outer fold")
    expected_folds = set(range(N_OUTER_FOLDS))
    actual_folds = set(selected["heldout_fold"])
    if actual_folds != expected_folds:
        raise ValueError(
            f"Expected outer folds {sorted(expected_folds)}, got {sorted(actual_folds)}"
        )
    return selected.sort_values("heldout_fold").reset_index(drop=True)


def load_predictions(path: Path, selected_models: set[str]) -> tuple[pd.DataFrame, list[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing frozen held-out predictions: {path}")
    columns = [
        "subject_id",
        "decision_index",
        "split",
        "model_name",
        "high_risk_label",
        "high_risk_probability",
    ]
    predictions = pd.read_csv(path, usecols=columns)
    predictions["subject_id"] = predictions["subject_id"].astype(str)
    all_subjects = sorted(predictions["subject_id"].unique())
    predictions = predictions[
        predictions["split"].eq("heldout")
        & predictions["model_name"].isin(selected_models)
    ].copy()
    predictions["decision_index"] = pd.to_numeric(
        predictions["decision_index"], errors="raise"
    ).astype(int)
    predictions["high_risk_label"] = pd.to_numeric(
        predictions["high_risk_label"], errors="raise"
    ).astype(int)
    if not predictions["high_risk_label"].isin((0, 1)).all():
        raise ValueError("high_risk_label must be binary")
    predictions["high_risk_probability"] = pd.to_numeric(
        predictions["high_risk_probability"], errors="raise"
    ).astype(float)
    if not predictions["high_risk_probability"].between(0.0, 1.0).all():
        raise ValueError("high_risk_probability must be in [0, 1]")
    duplicate_key = ["subject_id", "decision_index", "model_name"]
    if predictions.duplicated(duplicate_key).any():
        raise ValueError(f"Duplicate held-out prediction key: {duplicate_key}")
    return predictions, all_subjects


def assign_outer_folds(subjects: list[str]) -> pd.DataFrame:
    """Reproduce the frozen benchmark's sorted-subject modulo-five assignment."""
    return pd.DataFrame(
        {
            "subject_id": subjects,
            "heldout_fold": np.arange(len(subjects), dtype=int) % N_OUTER_FOLDS,
        }
    )


def compute_uncertainty(risk: pd.Series, mode: str) -> np.ndarray:
    scores = risk.to_numpy(dtype=float)
    if mode == "probability_margin":
        return np.clip(1.0 - np.abs(2.0 * scores - 1.0), 0.0, 1.0)
    if mode == "none":
        return np.zeros(len(scores), dtype=float)
    raise ValueError(f"Unsupported uncertainty mode: {mode!r}")


def route_fold(
    frame: pd.DataFrame,
    *,
    prompt_threshold: float,
    uncertainty_threshold: float,
    uncertainty_mode: str,
    runtime_auto_alert_cap: int,
    runtime_review_cap: int,
    review_band_width: float,
) -> pd.DataFrame:
    if runtime_auto_alert_cap < 0 or runtime_review_cap < 0:
        raise ValueError("runtime capacities must be non-negative")
    if review_band_width < 0.0:
        raise ValueError("review band width must be non-negative")
    replay = frame.sort_values(["subject_id", "decision_index"]).reset_index(drop=True)
    replay["risk_score"] = replay["high_risk_probability"].astype(float)
    replay["uncertainty_score"] = compute_uncertainty(
        replay["risk_score"], uncertainty_mode
    )

    risk = replay["risk_score"].to_numpy(dtype=float)
    uncertainty = replay["uncertainty_score"].to_numpy(dtype=float)
    uncertainty_abstain = uncertainty >= uncertainty_threshold
    threshold_distance = np.abs(risk - prompt_threshold)
    review_candidate = (~uncertainty_abstain) & (
        threshold_distance <= review_band_width
    )
    auto_alert_candidate = (~uncertainty_abstain) & (
        risk > prompt_threshold + review_band_width
    )

    review_seen = (
        pd.Series(review_candidate.astype(int), index=replay.index)
        .groupby(replay["subject_id"], sort=False)
        .cumsum()
        .to_numpy(dtype=int)
    )
    review_before = np.minimum(
        review_seen - review_candidate.astype(int), runtime_review_cap
    )
    review_available = review_before < runtime_review_cap
    human_review = review_candidate & review_available
    review_overflow = review_candidate & (~review_available)

    auto_seen = (
        pd.Series(auto_alert_candidate.astype(int), index=replay.index)
        .groupby(replay["subject_id"], sort=False)
        .cumsum()
        .to_numpy(dtype=int)
    )
    auto_before = np.minimum(
        auto_seen - auto_alert_candidate.astype(int), runtime_auto_alert_cap
    )
    auto_available = auto_before < runtime_auto_alert_cap
    alert = auto_alert_candidate & auto_available
    auto_capacity_blocked = auto_alert_candidate & (~auto_available)
    abstain = uncertainty_abstain | review_overflow
    no_action = (~abstain) & (~alert) & (~human_review)

    primary_route = np.full(len(replay), "no_action", dtype=object)
    primary_route[abstain] = "abstain"
    primary_route[alert] = "alert"
    primary_route[human_review] = "human_review"

    reason = np.full(len(replay), "risk_below_prompt_threshold", dtype=object)
    reason[uncertainty_abstain] = "uncertainty_gate"
    reason[review_overflow] = "review_capacity_exhausted"
    reason[auto_capacity_blocked] = "auto_alert_capacity_exhausted"
    reason[alert] = "risk_above_review_band"
    reason[human_review] = "risk_within_threshold_review_band"

    replay["primary_route"] = primary_route
    replay["reason_code"] = reason
    replay["threshold_distance"] = threshold_distance
    replay["runtime_auto_alert_count_before"] = auto_before
    replay["runtime_auto_alert_count_after"] = auto_before + alert.astype(int)
    replay["runtime_review_count_before"] = review_before
    replay["runtime_review_count_after"] = review_before + human_review.astype(int)
    for route in PRIMARY_ROUTES:
        replay[f"route_{route}"] = (primary_route == route).astype(int)
    if not np.array_equal(no_action, primary_route == "no_action"):
        raise AssertionError("Internal no_action construction mismatch")
    return replay


def claim_for_route(route: str, reason: str) -> str:
    # Capacity-exhaustion claims must be selected from the reason before the
    # generic route branch. In particular, review-capacity exhaustion executes
    # an abstain route but carries a distinct operational interpretation.
    if reason == "auto_alert_capacity_exhausted":
        return "runtime_auto_alert_capacity_blocks_action"
    if reason == "review_capacity_exhausted":
        return "runtime_review_capacity_blocks_action"
    if route == "alert":
        return "behavior_only_proxy_supports_automated_prompt"
    if route == "human_review":
        return "behavior_only_proxy_requires_human_review"
    if route == "abstain":
        return "behavior_only_proxy_uncertain_no_automated_action"
    return "behavior_only_proxy_does_not_authorize_action"


def add_claim_license_fields(
    frame: pd.DataFrame,
    *,
    false_action_limit_per_100: float,
    capacity_source: str,
) -> pd.DataFrame:
    trace = frame.copy()
    trace["trace_id"] = [
        f"mligt::{subject}::{int(index):03d}"
        for subject, index in zip(trace["subject_id"], trace["decision_index"])
    ]
    trace["source_prediction_split"] = "heldout"
    trace["decision_temporality"] = "causal_one_step_probability"
    trace["runtime_operational_setting_source"] = capacity_source
    trace["runtime_auto_alert_capacity_unit"] = (
        "automated_alerts_per_heldout_participant_segment"
    )
    trace["runtime_review_capacity_unit"] = (
        "human_reviews_per_heldout_participant_segment"
    )
    trace["runtime_auto_alert_capacity_role"] = "pre_action_hard_count_constraint"
    trace["runtime_review_capacity_role"] = "pre_action_hard_count_constraint"
    trace["validation_false_action_limit_per_100"] = false_action_limit_per_100
    trace["validation_false_action_criterion_role"] = "posthoc_validation_only"
    trace["validation_false_action_criterion_scope"] = "alert_or_human_review"
    trace["runtime_false_action_criterion_used"] = False
    trace["posthoc_proxy_label_available_to_runtime"] = False
    trace["runtime_route_computed_before_label_access"] = True
    trace = trace.rename(columns={"high_risk_label": "posthoc_observed_proxy_label"})

    admitted = json_array(
        (
            "behavior_oof_probability",
            "outer_train_selected_policy_parameters",
            "pre_action_runtime_state",
        )
    )
    excluded = json_array(
        (
            "eeg",
            "posthoc_proxy_label",
            "clinical_outcome",
            "intervention_outcome",
        )
    )
    blocked = json_array(
        (
            "eeg_incremental_value",
            "clinical_risk",
            "diagnosis",
            "intervention_efficacy",
            "behavior_change",
        )
    )
    trace["license_id"] = "claim_license_behavior_oof_v1"
    trace["license_scope"] = "behavior_only_decision_support"
    trace["validation_unit"] = "participant_heldout_decision_with_outer_fold_policy"
    trace["eeg_gate_status"] = "closed_no_eeg_in_input"
    trace["eeg_evidence_admitted"] = False
    trace["eeg_evidence_used"] = False
    trace["admitted_evidence_json"] = admitted
    trace["used_evidence_json"] = admitted
    trace["excluded_evidence_json"] = excluded
    trace["blocked_claims_json"] = blocked
    trace["asserted_claim"] = [
        claim_for_route(route, reason)
        for route, reason in zip(trace["primary_route"], trace["reason_code"])
    ]
    trace["permitted_claims_json"] = trace["asserted_claim"].map(
        lambda claim: json_array((claim,))
    )
    trace["required_next_evidence_json"] = json_array(
        (
            "registered_eeg_incremental_value_test",
            "prospective_intervention_trial",
        )
    )
    return trace


def build_trace(
    predictions: pd.DataFrame,
    subjects: list[str],
    selected: pd.DataFrame,
    *,
    runtime_auto_alert_cap: int,
    runtime_review_cap: int,
    review_band_width: float,
    false_action_limit_per_100: float,
) -> pd.DataFrame:
    folds = assign_outer_folds(subjects)
    predictions = predictions.merge(
        folds, on="subject_id", how="left", validate="many_to_one"
    )
    routed_folds: list[pd.DataFrame] = []
    for parameters in selected.itertuples(index=False):
        fold = int(parameters.heldout_fold)
        model = str(parameters.train_risk_model_name)
        pool = predictions[
            predictions["heldout_fold"].eq(fold)
            & predictions["model_name"].eq(model)
        ].copy()
        if pool.empty:
            raise ValueError(f"No held-out predictions for fold={fold}, model={model}")
        routed = route_fold(
            pool,
            prompt_threshold=float(parameters.train_prompt_threshold),
            uncertainty_threshold=float(parameters.train_uncertainty_threshold),
            uncertainty_mode=str(parameters.train_uncertainty_mode),
            runtime_auto_alert_cap=runtime_auto_alert_cap,
            runtime_review_cap=runtime_review_cap,
            review_band_width=review_band_width,
        )
        routed["risk_model_name"] = model
        routed["prompt_threshold"] = float(parameters.train_prompt_threshold)
        routed["uncertainty_threshold"] = float(
            parameters.train_uncertainty_threshold
        )
        routed["uncertainty_mode"] = str(parameters.train_uncertainty_mode)
        routed["review_band_width"] = review_band_width
        routed["runtime_auto_alert_cap"] = runtime_auto_alert_cap
        routed["runtime_review_cap"] = runtime_review_cap
        routed_folds.append(routed)

    trace = pd.concat(routed_folds, ignore_index=True)
    trace = add_claim_license_fields(
        trace,
        false_action_limit_per_100=false_action_limit_per_100,
        capacity_source="fixed_operational_settings_not_optimized_on_heldout_labels",
    )
    trace = trace.sort_values(
        ["heldout_fold", "subject_id", "decision_index"]
    ).reset_index(drop=True)
    if trace["trace_id"].duplicated().any():
        raise ValueError("trace_id is not unique")
    return trace


def expected_route_and_reason(row: pd.Series) -> tuple[str, str]:
    if float(row["uncertainty_score"]) >= float(row["uncertainty_threshold"]):
        return "abstain", "uncertainty_gate"
    distance = abs(float(row["risk_score"]) - float(row["prompt_threshold"]))
    if distance <= float(row["review_band_width"]):
        if int(row["runtime_review_count_before"]) >= int(
            row["runtime_review_cap"]
        ):
            return "abstain", "review_capacity_exhausted"
        return "human_review", "risk_within_threshold_review_band"
    if float(row["risk_score"]) > (
        float(row["prompt_threshold"]) + float(row["review_band_width"])
    ):
        if int(row["runtime_auto_alert_count_before"]) >= int(
            row["runtime_auto_alert_cap"]
        ):
            return "no_action", "auto_alert_capacity_exhausted"
        return "alert", "risk_above_review_band"
    return "no_action", "risk_below_prompt_threshold"


REQUIRED_STRING_FIELDS = (
    "trace_id",
    "subject_id",
    "source_prediction_split",
    "risk_model_name",
    "uncertainty_mode",
    "runtime_operational_setting_source",
    "runtime_auto_alert_capacity_unit",
    "runtime_review_capacity_unit",
    "runtime_auto_alert_capacity_role",
    "runtime_review_capacity_role",
    "primary_route",
    "reason_code",
    "license_id",
    "license_scope",
    "validation_unit",
    "asserted_claim",
    "eeg_gate_status",
    "validation_false_action_criterion_role",
    "validation_false_action_criterion_scope",
    "decision_temporality",
)
REQUIRED_INTEGER_FIELDS = (
    "decision_index",
    "heldout_fold",
    "runtime_auto_alert_cap",
    "runtime_auto_alert_count_before",
    "runtime_auto_alert_count_after",
    "runtime_review_cap",
    "runtime_review_count_before",
    "runtime_review_count_after",
    *ROUTE_FLAG_COLUMNS,
    "posthoc_observed_proxy_label",
)
REQUIRED_NUMERIC_FIELDS = (
    "risk_score",
    "uncertainty_score",
    "prompt_threshold",
    "uncertainty_threshold",
    "review_band_width",
    "threshold_distance",
    "validation_false_action_limit_per_100",
)
REQUIRED_BOOLEAN_FIELDS = (
    "eeg_evidence_admitted",
    "eeg_evidence_used",
    "runtime_false_action_criterion_used",
    "posthoc_proxy_label_available_to_runtime",
    "runtime_route_computed_before_label_access",
)
REQUIRED_JSON_LIST_FIELDS = (
    "permitted_claims_json",
    "blocked_claims_json",
    "admitted_evidence_json",
    "used_evidence_json",
    "excluded_evidence_json",
    "required_next_evidence_json",
)


def value_is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def is_finite_number(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return False
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def is_integer_like(value: Any) -> bool:
    return is_finite_number(value) and float(value).is_integer()


def is_boolean_like(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return True
    if isinstance(value, (int, np.integer)):
        return int(value) in (0, 1)
    return str(value).strip().lower() in {"true", "false", "0", "1"}


def structural_audit_row(row: pd.Series) -> list[str]:
    """Presence/type baseline over the exact same complete trace record."""
    failures: set[str] = set()
    required = (
        REQUIRED_STRING_FIELDS
        + REQUIRED_INTEGER_FIELDS
        + REQUIRED_NUMERIC_FIELDS
        + REQUIRED_BOOLEAN_FIELDS
        + REQUIRED_JSON_LIST_FIELDS
    )
    if any(field not in row.index or value_is_missing(row.get(field)) for field in required):
        failures.add("STRUCT_REQUIRED_VALUE")

    for field in REQUIRED_STRING_FIELDS:
        if field in row.index and not value_is_missing(row.get(field)) and not isinstance(
            row.get(field), str
        ):
            failures.add("STRUCT_TYPE")
    for field in REQUIRED_INTEGER_FIELDS:
        if field in row.index and not value_is_missing(row.get(field)) and not is_integer_like(
            row.get(field)
        ):
            failures.add("STRUCT_TYPE")
    for field in REQUIRED_NUMERIC_FIELDS:
        if field in row.index and not value_is_missing(row.get(field)) and not is_finite_number(
            row.get(field)
        ):
            failures.add("STRUCT_TYPE")
    for field in REQUIRED_BOOLEAN_FIELDS:
        if field in row.index and not value_is_missing(row.get(field)) and not is_boolean_like(
            row.get(field)
        ):
            failures.add("STRUCT_TYPE")
    for field in REQUIRED_JSON_LIST_FIELDS:
        if field in row.index and not value_is_missing(row.get(field)):
            try:
                parse_json_array(row.get(field))
            except (TypeError, ValueError, json.JSONDecodeError):
                failures.add("STRUCT_TYPE")
    return sorted(failures)


def semantic_audit_row(row: pd.Series) -> list[str]:
    failures: set[str] = set(structural_audit_row(row))
    if failures:
        return sorted(failures)
    route = str(row.get("primary_route", ""))
    if route not in PRIMARY_ROUTES:
        failures.add("ROUTE_DOMAIN")

    flags = [int(row.get(column, 0)) for column in ROUTE_FLAG_COLUMNS]
    route_flag_matches = route in PRIMARY_ROUTES and int(row[f"route_{route}"]) == 1
    if sum(flags) != 1 or not route_flag_matches:
        failures.add("ROUTE_EXCLUSIVITY")

    try:
        expected_route, expected_reason = expected_route_and_reason(row)
        if route != expected_route or str(row.get("reason_code", "")) != expected_reason:
            failures.add("ROUTE_RULE_CONSISTENCY")
    except (TypeError, ValueError, KeyError):
        failures.add("ROUTE_RULE_CONSISTENCY")

    for prefix, route_name in (
        ("runtime_auto_alert", "alert"),
        ("runtime_review", "human_review"),
    ):
        try:
            before = int(row[f"{prefix}_count_before"])
            after = int(row[f"{prefix}_count_after"])
            limit = int(row[f"{prefix}_cap"])
            if after != before + int(route == route_name):
                failures.add(f"{prefix.upper()}_CAPACITY_TRANSITION")
            if not (0 <= before <= after <= limit):
                failures.add(f"{prefix.upper()}_CAPACITY_BOUND")
        except (TypeError, ValueError, KeyError):
            failures.add(f"{prefix.upper()}_CAPACITY_BOUND")

    if (
        str(row.get("runtime_auto_alert_capacity_role", ""))
        != "pre_action_hard_count_constraint"
        or str(row.get("runtime_review_capacity_role", ""))
        != "pre_action_hard_count_constraint"
    ):
        failures.add("RUNTIME_CAPACITY_ROLE")
    if (
        str(row.get("validation_false_action_criterion_role", ""))
        != "posthoc_validation_only"
        or is_true(row.get("runtime_false_action_criterion_used", False))
    ):
        failures.add("VALIDATION_CRITERION_RUNTIME_MISUSE")

    try:
        admitted = set(parse_json_array(row.get("admitted_evidence_json")))
        used = set(parse_json_array(row.get("used_evidence_json")))
        if not used.issubset(admitted):
            failures.add("EVIDENCE_NOT_ADMITTED")
    except (TypeError, ValueError, json.JSONDecodeError):
        admitted, used = set(), set()
        failures.add("EVIDENCE_ENCODING")

    normalized_used = {item.lower() for item in used}
    normalized_admitted = {item.lower() for item in admitted}
    eeg_in_evidence = any("eeg" in item for item in normalized_used | normalized_admitted)
    if str(row.get("eeg_gate_status", "")).startswith("closed") and (
        eeg_in_evidence
        or is_true(row.get("eeg_evidence_admitted", False))
        or is_true(row.get("eeg_evidence_used", False))
    ):
        failures.add("EEG_GATE_BYPASS")

    if is_true(row.get("posthoc_proxy_label_available_to_runtime", False)) or (
        "posthoc_proxy_label" in normalized_used
    ):
        failures.add("OUTCOME_LABEL_RUNTIME_LEAKAGE")

    try:
        permitted = set(parse_json_array(row.get("permitted_claims_json")))
        blocked = set(parse_json_array(row.get("blocked_claims_json")))
        asserted = str(row.get("asserted_claim", ""))
        expected_claim = claim_for_route(
            str(row.get("primary_route", "")), str(row.get("reason_code", ""))
        )
        if asserted != expected_claim:
            failures.add("CLAIM_ROUTE_REASON_CONSISTENCY")
        if asserted not in permitted:
            failures.add("CLAIM_NOT_PERMITTED")
        if asserted in blocked:
            failures.add("BLOCKED_CLAIM_ASSERTED")
    except (TypeError, ValueError, json.JSONDecodeError):
        failures.add("CLAIM_LICENSE_ENCODING")

    required_text_fields = ("license_id", "license_scope", "validation_unit")
    if any(not str(row.get(column, "")).strip() for column in required_text_fields):
        failures.add("CLAIM_LICENSE_SCOPE_MISSING")
    return sorted(failures)


def audit_frame(
    frame: pd.DataFrame, *, validator: str, check_sequence: bool
) -> pd.DataFrame:
    if validator == "structural_baseline":
        audit_function = structural_audit_row
    elif validator == "semantic_validator":
        audit_function = semantic_audit_row
    else:
        raise ValueError(f"Unknown validator: {validator!r}")
    rule_codes: dict[int, set[str]] = {
        int(index): set(audit_function(row)) for index, row in frame.iterrows()
    }
    if check_sequence and validator == "semantic_validator":
        ordered = frame.sort_values(["subject_id", "decision_index"])
        for _, group in ordered.groupby("subject_id", sort=False):
            expected_auto_before = 0
            expected_review_before = 0
            for index, row in group.iterrows():
                if (
                    int(row["runtime_auto_alert_count_before"])
                    != expected_auto_before
                ):
                    rule_codes[int(index)].add(
                        "RUNTIME_AUTO_ALERT_CAPACITY_SEQUENCE"
                    )
                if int(row["runtime_review_count_before"]) != expected_review_before:
                    rule_codes[int(index)].add("RUNTIME_REVIEW_CAPACITY_SEQUENCE")
                expected_auto_before = int(row["runtime_auto_alert_count_after"])
                expected_review_before = int(row["runtime_review_count_after"])

    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        codes = sorted(rule_codes[int(index)])
        expected = str(row.get("expected_rule_code", ""))
        rows.append(
            {
                "validator": validator,
                "dataset": str(row.get("audit_dataset", "clean")),
                "trace_id": str(row["trace_id"]),
                "source_trace_id": str(row.get("source_trace_id", row["trace_id"])),
                "injection_type": str(row.get("injection_type", "")),
                "expected_rule_code": expected,
                "detected_rule_codes": "|".join(codes),
                "audit_pass": len(codes) == 0,
                "expected_violation_detected": (
                    len(codes) == 0 if not expected else expected in codes
                ),
            }
        )
    return pd.DataFrame(rows)


def validator_comparison(audit_results: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for validator, validator_rows in audit_results.groupby("validator", sort=True):
        clean = validator_rows[validator_rows["dataset"].eq("clean")]
        injected = validator_rows[validator_rows["dataset"].eq("injected")]
        clean_detected = int((~clean["audit_pass"]).sum())
        rows.append(
            {
                "validator": validator,
                "evaluation_scope": "clean",
                "injection_type": "none",
                "n_records": int(len(clean)),
                "n_flagged": clean_detected,
                "clean_false_positive_rate": safe_ratio(
                    clean_detected, int(len(clean))
                ),
                "detection_sensitivity": np.nan,
            }
        )
        injected_detected = int((~injected["audit_pass"]).sum())
        rows.append(
            {
                "validator": validator,
                "evaluation_scope": "injected_overall",
                "injection_type": "all",
                "n_records": int(len(injected)),
                "n_flagged": injected_detected,
                "clean_false_positive_rate": np.nan,
                "detection_sensitivity": safe_ratio(
                    injected_detected, int(len(injected))
                ),
            }
        )
        for injection_type, group in injected.groupby("injection_type", sort=True):
            detected = int((~group["audit_pass"]).sum())
            rows.append(
                {
                    "validator": validator,
                    "evaluation_scope": "injection_type",
                    "injection_type": injection_type,
                    "n_records": int(len(group)),
                    "n_flagged": detected,
                    "clean_false_positive_rate": np.nan,
                    "detection_sensitivity": safe_ratio(detected, int(len(group))),
                }
            )
    return pd.DataFrame(rows)


def append_json_item(serialized: str, item: str) -> str:
    values = parse_json_array(serialized)
    if item not in values:
        values.append(item)
    return json_array(values)


def inject_known_violations(
    clean: pd.DataFrame, *, per_type: int, seed: int
) -> pd.DataFrame:
    if per_type <= 0:
        raise ValueError("injections-per-type must be positive")
    specifications = (
        ("nonexclusive_route", "ROUTE_EXCLUSIVITY"),
        (
            "runtime_auto_alert_capacity_overrun",
            "RUNTIME_AUTO_ALERT_CAPACITY_BOUND",
        ),
        ("runtime_review_capacity_overrun", "RUNTIME_REVIEW_CAPACITY_BOUND"),
        ("closed_eeg_gate_bypass", "EEG_GATE_BYPASS"),
        ("blocked_claim_asserted", "BLOCKED_CLAIM_ASSERTED"),
        ("route_reason_claim_mismatch", "CLAIM_ROUTE_REASON_CONSISTENCY"),
        ("posthoc_label_runtime_leakage", "OUTCOME_LABEL_RUNTIME_LEAKAGE"),
        (
            "validation_criterion_used_as_runtime_gate",
            "VALIDATION_CRITERION_RUNTIME_MISUSE",
        ),
        ("required_license_field_missing", "STRUCT_REQUIRED_VALUE"),
        ("runtime_capacity_type_corruption", "STRUCT_TYPE"),
    )
    required_rows = per_type * len(specifications)
    if required_rows > len(clean):
        raise ValueError("Not enough clean traces for disjoint injected samples")
    generator = np.random.default_rng(seed)
    selected_indices = generator.choice(len(clean), size=required_rows, replace=False)
    injected_rows: list[pd.Series] = []

    for spec_index, (injection_type, expected_rule) in enumerate(specifications):
        start = spec_index * per_type
        for sample_number, clean_index in enumerate(
            selected_indices[start : start + per_type], start=1
        ):
            row = clean.iloc[int(clean_index)].copy()
            source_trace_id = str(row["trace_id"])
            row["source_trace_id"] = source_trace_id
            row["trace_id"] = (
                f"inject::{injection_type}::{sample_number:02d}::{source_trace_id}"
            )
            row["audit_dataset"] = "injected"
            row["injection_type"] = injection_type
            row["expected_rule_code"] = expected_rule

            if injection_type == "nonexclusive_route":
                extra_route = (
                    "human_review" if row["primary_route"] != "human_review" else "alert"
                )
                row[f"route_{extra_route}"] = 1
            elif injection_type == "runtime_auto_alert_capacity_overrun":
                for route_flag in ROUTE_FLAG_COLUMNS:
                    row[route_flag] = 0
                row["primary_route"] = "alert"
                row["route_alert"] = 1
                row["reason_code"] = "risk_above_review_band"
                limit = int(row["runtime_auto_alert_cap"])
                row["runtime_auto_alert_count_before"] = limit
                row["runtime_auto_alert_count_after"] = limit + 1
            elif injection_type == "runtime_review_capacity_overrun":
                for route_flag in ROUTE_FLAG_COLUMNS:
                    row[route_flag] = 0
                row["primary_route"] = "human_review"
                row["route_human_review"] = 1
                row["reason_code"] = "risk_within_threshold_review_band"
                limit = int(row["runtime_review_cap"])
                row["runtime_review_count_before"] = limit
                row["runtime_review_count_after"] = limit + 1
            elif injection_type == "closed_eeg_gate_bypass":
                row["eeg_evidence_admitted"] = True
                row["eeg_evidence_used"] = True
                row["admitted_evidence_json"] = append_json_item(
                    row["admitted_evidence_json"], "eeg_feature"
                )
                row["used_evidence_json"] = append_json_item(
                    row["used_evidence_json"], "eeg_feature"
                )
            elif injection_type == "blocked_claim_asserted":
                row["asserted_claim"] = "clinical_risk"
            elif injection_type == "route_reason_claim_mismatch":
                expected_claim = claim_for_route(
                    str(row["primary_route"]), str(row["reason_code"])
                )
                alternate_claim = "behavior_only_proxy_does_not_authorize_action"
                if expected_claim == alternate_claim:
                    alternate_claim = "behavior_only_proxy_supports_automated_prompt"
                row["asserted_claim"] = alternate_claim
                row["permitted_claims_json"] = json_array((alternate_claim,))
            elif injection_type == "posthoc_label_runtime_leakage":
                row["posthoc_proxy_label_available_to_runtime"] = True
                row["admitted_evidence_json"] = append_json_item(
                    row["admitted_evidence_json"], "posthoc_proxy_label"
                )
                row["used_evidence_json"] = append_json_item(
                    row["used_evidence_json"], "posthoc_proxy_label"
                )
            elif injection_type == "validation_criterion_used_as_runtime_gate":
                row["validation_false_action_criterion_role"] = "runtime_gate"
                row["runtime_false_action_criterion_used"] = True
            elif injection_type == "required_license_field_missing":
                row["license_id"] = ""
            elif injection_type == "runtime_capacity_type_corruption":
                row["runtime_auto_alert_cap"] = "not_an_integer"
            injected_rows.append(row)

    return pd.DataFrame(injected_rows).reset_index(drop=True)


def safe_ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else float("nan")


def metric_row(
    frame: pd.DataFrame,
    *,
    scope: str,
    heldout_fold: int | str,
    false_action_limit_per_100: float,
) -> dict[str, Any]:
    labels = frame["posthoc_observed_proxy_label"].astype(bool)
    alert = frame["primary_route"].eq("alert")
    review = frame["primary_route"].eq("human_review")
    action = alert | review
    n_decisions = int(len(frame))
    n_events = int(labels.sum())
    n_action = int(action.sum())
    n_true_action = int((action & labels).sum())
    n_false_action = int((action & ~labels).sum())
    n_alert = int(alert.sum())
    n_true_alert = int((alert & labels).sum())
    n_false_alert = int((alert & ~labels).sum())
    validation_false_rate = 100.0 * safe_ratio(n_false_action, n_decisions)
    n_no_action = int(frame["primary_route"].eq("no_action").sum())
    n_abstain = int(frame["primary_route"].eq("abstain").sum())
    n_review = int(review.sum())
    n_auto_blocks = int(
        frame["reason_code"].eq("auto_alert_capacity_exhausted").sum()
    )
    n_review_overflow = int(
        frame["reason_code"].eq("review_capacity_exhausted").sum()
    )
    return {
        "scope": scope,
        "heldout_fold": heldout_fold,
        "n_decisions": n_decisions,
        "n_proxy_events": n_events,
        "n_alert": n_alert,
        "n_no_action": n_no_action,
        "n_abstain": n_abstain,
        "n_human_review": n_review,
        "alert_rate": safe_ratio(n_alert, n_decisions),
        "no_action_rate": safe_ratio(n_no_action, n_decisions),
        "abstain_rate": safe_ratio(n_abstain, n_decisions),
        "human_review_rate": safe_ratio(n_review, n_decisions),
        "n_action_bearing_routes": n_action,
        "action_bearing_route_rate": safe_ratio(n_action, n_decisions),
        "n_true_action_routes": n_true_action,
        "n_false_action_routes": n_false_action,
        "n_true_automated_alerts": n_true_alert,
        "n_false_automated_alerts": n_false_alert,
        "posthoc_automated_alert_precision": safe_ratio(n_true_alert, n_alert),
        "posthoc_action_route_precision": safe_ratio(n_true_action, n_action),
        "posthoc_proxy_event_action_coverage": safe_ratio(n_true_action, n_events),
        "proxy_event_recall": safe_ratio(n_true_action, n_events),
        "action_precision": safe_ratio(n_true_action, n_action),
        "posthoc_automated_false_alerts_per_100": 100.0
        * safe_ratio(n_false_alert, n_decisions),
        "validation_false_actions_per_100_decisions": validation_false_rate,
        "false_actions_per_100_decisions": validation_false_rate,
        "validation_false_action_limit_per_100": false_action_limit_per_100,
        "validation_false_action_criterion_scope": "alert_or_human_review",
        "validation_false_action_criterion_pass": bool(
            validation_false_rate <= false_action_limit_per_100
        ),
        "n_runtime_auto_alert_capacity_blocks": n_auto_blocks,
        "runtime_auto_alert_capacity_block_rate": safe_ratio(
            n_auto_blocks, n_decisions
        ),
        "n_runtime_review_capacity_overflow_abstentions": n_review_overflow,
        "runtime_review_capacity_overflow_rate": safe_ratio(
            n_review_overflow, n_decisions
        ),
    }


def validation_metrics(
    trace: pd.DataFrame, false_action_limit_per_100: float
) -> pd.DataFrame:
    rows = [
        metric_row(
            trace,
            scope="pooled_heldout",
            heldout_fold="all",
            false_action_limit_per_100=false_action_limit_per_100,
        )
    ]
    for fold, group in trace.groupby("heldout_fold", sort=True):
        rows.append(
            metric_row(
                group,
                scope="outer_fold_heldout",
                heldout_fold=int(fold),
                false_action_limit_per_100=false_action_limit_per_100,
            )
        )
    return pd.DataFrame(rows)


def participant_burden(trace: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for subject_id, group in trace.groupby("subject_id", sort=True):
        labels = group["posthoc_observed_proxy_label"].astype(bool)
        alert = group["primary_route"].eq("alert")
        no_action = group["primary_route"].eq("no_action")
        abstain = group["primary_route"].eq("abstain")
        review = group["primary_route"].eq("human_review")
        action = alert | review
        n_decisions = int(len(group))
        n_events = int(labels.sum())
        n_action = int(action.sum())
        n_true_action = int((action & labels).sum())
        n_false_action = int((action & ~labels).sum())
        n_false_alert = int((alert & ~labels).sum())
        n_non_event_review = int((review & ~labels).sum())
        n_combined_non_event_escalation = int((action & ~labels).sum())
        if n_combined_non_event_escalation != (
            n_false_alert + n_non_event_review
        ):
            raise AssertionError(
                "Exclusive alert and human-review routes must partition "
                "combined non-event escalations"
            )
        if n_combined_non_event_escalation != n_false_action:
            raise AssertionError(
                "Combined non-event escalations must equal false action routes"
            )
        n_auto_blocks = int(
            group["reason_code"].eq("auto_alert_capacity_exhausted").sum()
        )
        n_review_overflow = int(
            group["reason_code"].eq("review_capacity_exhausted").sum()
        )
        heldout_folds = group["heldout_fold"].unique()
        if len(heldout_folds) != 1:
            raise AssertionError(f"Subject {subject_id} spans multiple outer folds")
        rows.append(
            {
                "subject_id": subject_id,
                "heldout_fold": int(heldout_folds[0]),
                "n_decisions": n_decisions,
                "n_proxy_events": n_events,
                "n_alert": int(alert.sum()),
                "n_no_action": int(no_action.sum()),
                "n_abstain": int(abstain.sum()),
                "n_human_review": int(review.sum()),
                "n_action_bearing_routes": n_action,
                "n_true_action_routes": n_true_action,
                "n_false_action_routes": n_false_action,
                "n_false_automated_alerts": n_false_alert,
                "n_non_event_human_reviews": n_non_event_review,
                "n_combined_non_event_escalations": (
                    n_combined_non_event_escalation
                ),
                "n_runtime_auto_alert_capacity_blocks": n_auto_blocks,
                "n_runtime_review_capacity_overflow_abstentions": n_review_overflow,
                "action_bearing_route_rate": safe_ratio(n_action, n_decisions),
                "false_automated_alert_rate": safe_ratio(
                    n_false_alert, n_decisions
                ),
                "non_event_human_review_rate": safe_ratio(
                    n_non_event_review, n_decisions
                ),
                "combined_non_event_escalation_rate": safe_ratio(
                    n_combined_non_event_escalation, n_decisions
                ),
                "action_routes_per_100_decisions": 100.0
                * safe_ratio(n_action, n_decisions),
                "action_bearing_routes_per_100_decisions": 100.0
                * safe_ratio(n_action, n_decisions),
                "false_automated_alerts_per_100_decisions": 100.0
                * safe_ratio(n_false_alert, n_decisions),
                "non_event_human_reviews_per_100_decisions": 100.0
                * safe_ratio(n_non_event_review, n_decisions),
                "combined_non_event_escalations_per_100_decisions": 100.0
                * safe_ratio(n_combined_non_event_escalation, n_decisions),
                "false_actions_per_100_decisions": 100.0
                * safe_ratio(n_false_action, n_decisions),
                "auto_alert_capacity_blocks_per_100_decisions": 100.0
                * safe_ratio(n_auto_blocks, n_decisions),
                "review_overflow_abstentions_per_100_decisions": 100.0
                * safe_ratio(n_review_overflow, n_decisions),
                "participant_proxy_event_recall": safe_ratio(
                    n_true_action, n_events
                ),
                "participant_action_precision": safe_ratio(
                    n_true_action, n_action
                ),
            }
        )
    return pd.DataFrame(rows)


CAPACITY_PARTICIPANT_BURDEN_METRICS = (
    (
        "n_false_automated_alerts",
        "count",
        "count_per_participant",
    ),
    (
        "false_automated_alerts_per_100_decisions",
        "rate",
        "per_100_participant_decisions",
    ),
    (
        "n_non_event_human_reviews",
        "count",
        "count_per_participant",
    ),
    (
        "non_event_human_reviews_per_100_decisions",
        "rate",
        "per_100_participant_decisions",
    ),
    (
        "n_combined_non_event_escalations",
        "count",
        "count_per_participant",
    ),
    (
        "combined_non_event_escalations_per_100_decisions",
        "rate",
        "per_100_participant_decisions",
    ),
    (
        "n_action_bearing_routes",
        "count",
        "count_per_participant",
    ),
    (
        "action_bearing_routes_per_100_decisions",
        "rate",
        "per_100_participant_decisions",
    ),
)


def runtime_capacity_participant_burden_quantiles(
    participants: pd.DataFrame,
) -> pd.DataFrame:
    """Summarise participant burden at each fixed alert-capacity setting.

    Counts are participant totals. Rates use the participant's held-out decision
    count as denominator and are scaled per 100 decisions; held-out labels are
    used only after routing to identify non-event escalations.
    """
    rows: list[dict[str, Any]] = []
    grouping_columns = (
        "runtime_auto_alert_cap_label",
        "runtime_auto_alert_cap_numeric",
        "runtime_auto_alert_cap_is_unbounded",
        "runtime_review_cap",
        "review_band_width",
    )
    for setting, group in participants.groupby(list(grouping_columns), sort=False):
        setting_values = dict(zip(grouping_columns, setting))
        for metric, metric_type, unit in CAPACITY_PARTICIPANT_BURDEN_METRICS:
            values = pd.to_numeric(group[metric], errors="raise")
            if values.isna().any():
                raise AssertionError(
                    f"Participant burden metric contains missing values: {metric}"
                )
            rows.append(
                {
                    **setting_values,
                    "metric": metric,
                    "metric_type": metric_type,
                    "unit": unit,
                    "rate_denominator": (
                        "participant_heldout_decisions"
                        if metric_type == "rate"
                        else "not_applicable"
                    ),
                    "n_participants": int(len(values)),
                    "median": float(values.quantile(0.50)),
                    "q1": float(values.quantile(0.25)),
                    "q3": float(values.quantile(0.75)),
                    "p90": float(values.quantile(0.90)),
                    "max": float(values.max()),
                }
            )
    return pd.DataFrame(rows)


def participant_burden_distribution(participants: pd.DataFrame) -> pd.DataFrame:
    metrics = (
        "n_alert",
        "n_human_review",
        "n_action_bearing_routes",
        "n_false_action_routes",
        "n_abstain",
        "n_runtime_auto_alert_capacity_blocks",
        "n_runtime_review_capacity_overflow_abstentions",
        "action_routes_per_100_decisions",
        "false_actions_per_100_decisions",
        "auto_alert_capacity_blocks_per_100_decisions",
        "review_overflow_abstentions_per_100_decisions",
    )
    rows: list[dict[str, Any]] = []
    for metric in metrics:
        values = pd.to_numeric(participants[metric], errors="coerce").dropna()
        q1 = float(values.quantile(0.25))
        median = float(values.quantile(0.50))
        q3 = float(values.quantile(0.75))
        rows.append(
            {
                "metric": metric,
                "n_participants": int(len(values)),
                "median": median,
                "q1": q1,
                "q3": q3,
                "iqr": q3 - q1,
                "p90": float(values.quantile(0.90)),
                "maximum": float(values.max()),
            }
        )
    return pd.DataFrame(rows)


def participant_bootstrap_confidence_intervals(
    participants: pd.DataFrame, *, replicates: int, seed: int
) -> pd.DataFrame:
    if replicates < 100:
        raise ValueError("bootstrap-replicates must be at least 100")
    contribution_columns = (
        "n_decisions",
        "n_proxy_events",
        "n_alert",
        "n_no_action",
        "n_abstain",
        "n_human_review",
        "n_action_bearing_routes",
        "n_true_action_routes",
        "n_false_action_routes",
        "n_runtime_auto_alert_capacity_blocks",
        "n_runtime_review_capacity_overflow_abstentions",
    )
    contributions = participants[list(contribution_columns)].to_numpy(dtype=float)
    n_participants = len(participants)
    generator = np.random.default_rng(seed)
    indices = generator.integers(
        0, n_participants, size=(replicates, n_participants), endpoint=False
    )
    bootstrap_totals = contributions[indices].sum(axis=1)
    observed_totals = contributions.sum(axis=0)
    column_index = {column: index for index, column in enumerate(contribution_columns)}
    specifications = (
        ("alert_rate", "n_alert", "n_decisions", 1.0),
        ("no_action_rate", "n_no_action", "n_decisions", 1.0),
        ("abstain_rate", "n_abstain", "n_decisions", 1.0),
        ("human_review_rate", "n_human_review", "n_decisions", 1.0),
        (
            "action_bearing_route_rate",
            "n_action_bearing_routes",
            "n_decisions",
            1.0,
        ),
        (
            "proxy_event_recall",
            "n_true_action_routes",
            "n_proxy_events",
            1.0,
        ),
        (
            "action_precision",
            "n_true_action_routes",
            "n_action_bearing_routes",
            1.0,
        ),
        (
            "false_actions_per_100_decisions",
            "n_false_action_routes",
            "n_decisions",
            100.0,
        ),
        (
            "runtime_auto_alert_capacity_block_rate",
            "n_runtime_auto_alert_capacity_blocks",
            "n_decisions",
            1.0,
        ),
        (
            "runtime_review_capacity_overflow_rate",
            "n_runtime_review_capacity_overflow_abstentions",
            "n_decisions",
            1.0,
        ),
    )
    rows: list[dict[str, Any]] = []
    for metric, numerator, denominator, multiplier in specifications:
        numerator_index = column_index[numerator]
        denominator_index = column_index[denominator]
        observed = multiplier * (
            observed_totals[numerator_index]
            / observed_totals[denominator_index]
        )
        bootstrap_values = multiplier * np.divide(
            bootstrap_totals[:, numerator_index],
            bootstrap_totals[:, denominator_index],
            out=np.full(replicates, np.nan, dtype=float),
            where=bootstrap_totals[:, denominator_index] > 0,
        )
        bootstrap_values = bootstrap_values[np.isfinite(bootstrap_values)]
        rows.append(
            {
                "metric": metric,
                "estimate": float(observed),
                "ci_95_low": float(np.percentile(bootstrap_values, 2.5)),
                "ci_95_high": float(np.percentile(bootstrap_values, 97.5)),
                "bootstrap_unit": "participant",
                "bootstrap_method": "percentile",
                "bootstrap_replicates": replicates,
                "bootstrap_seed": seed,
                "n_participants": n_participants,
            }
        )
    return pd.DataFrame(rows)


def runtime_capacity_sensitivity(
    predictions: pd.DataFrame,
    subjects: list[str],
    selected: pd.DataFrame,
    *,
    primary_trace: pd.DataFrame,
    primary_auto_alert_cap: int,
    runtime_review_cap: int,
    review_band_width: float,
    false_action_limit_per_100: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    maximum_segment_decisions = int(
        predictions.groupby("subject_id", sort=False).size().max()
    )
    settings: list[tuple[str, int]] = [
        ("2", 2),
        ("4", 4),
        ("6", 6),
        ("8", 8),
        ("unbounded", maximum_segment_decisions + 1),
    ]
    thresholds_by_fold = {
        str(int(row.heldout_fold)): float(row.train_prompt_threshold)
        for row in selected.itertuples(index=False)
    }
    rows: list[dict[str, Any]] = []
    participant_frames: list[pd.DataFrame] = []
    for label, cap in settings:
        replay = (
            primary_trace
            if cap == primary_auto_alert_cap
            else build_trace(
                predictions,
                subjects,
                selected,
                runtime_auto_alert_cap=cap,
                runtime_review_cap=runtime_review_cap,
                review_band_width=review_band_width,
                false_action_limit_per_100=false_action_limit_per_100,
            )
        )
        row = metric_row(
            replay,
            scope="runtime_capacity_sensitivity",
            heldout_fold="all",
            false_action_limit_per_100=false_action_limit_per_100,
        )
        row.update(
            {
                "runtime_auto_alert_cap_label": label,
                "runtime_auto_alert_cap_numeric": cap,
                "runtime_auto_alert_cap_is_unbounded": label == "unbounded",
                "runtime_review_cap": runtime_review_cap,
                "review_band_width": review_band_width,
                "score_source": "frozen_outer_fold_heldout_probability",
                "prompt_threshold_source": "frozen_outer_train_selected_per_fold",
                "prompt_thresholds_by_fold_json": json.dumps(
                    thresholds_by_fold, separators=(",", ":"), sort_keys=True
                ),
                "settings_provenance": (
                    "fixed_operational_settings_not_optimized_on_heldout_labels"
                ),
                "route_rate_sum": float(
                    sum(
                        replay["primary_route"].eq(route).mean()
                        for route in PRIMARY_ROUTES
                    )
                ),
            }
        )
        rows.append(row)

        cap_participants = participant_burden(replay)
        cap_participants.insert(0, "runtime_auto_alert_cap_label", label)
        cap_participants.insert(1, "runtime_auto_alert_cap_numeric", cap)
        cap_participants.insert(
            2, "runtime_auto_alert_cap_is_unbounded", label == "unbounded"
        )
        cap_participants.insert(3, "runtime_review_cap", runtime_review_cap)
        cap_participants.insert(4, "review_band_width", review_band_width)
        cap_participants.insert(
            5,
            "settings_provenance",
            "fixed_operational_settings_not_optimized_on_heldout_labels",
        )

        if int(cap_participants["n_alert"].max()) > cap:
            raise AssertionError(
                f"Participant automated-alert count exceeded cap={cap}"
            )
        if label == "unbounded" and int(
            cap_participants["n_runtime_auto_alert_capacity_blocks"].sum()
        ):
            raise AssertionError(
                "Effectively unbounded automated-alert capacity blocked a route"
            )

        pooled_identities = (
            (
                "n_false_automated_alerts",
                int(row["n_false_automated_alerts"]),
            ),
            (
                "n_combined_non_event_escalations",
                int(row["n_false_action_routes"]),
            ),
            (
                "n_action_bearing_routes",
                int(row["n_action_bearing_routes"]),
            ),
        )
        for participant_metric, pooled_value in pooled_identities:
            participant_total = int(cap_participants[participant_metric].sum())
            if participant_total != pooled_value:
                raise AssertionError(
                    f"Participant sum mismatch for cap={cap}, "
                    f"metric={participant_metric}: {participant_total} != "
                    f"{pooled_value}"
                )
        expected_non_event_reviews = int(row["n_false_action_routes"]) - int(
            row["n_false_automated_alerts"]
        )
        if int(cap_participants["n_non_event_human_reviews"].sum()) != (
            expected_non_event_reviews
        ):
            raise AssertionError(
                f"Participant non-event review sum mismatch for cap={cap}"
            )
        participant_frames.append(cap_participants)

    sensitivity = pd.DataFrame(rows)
    capacity_participants = pd.concat(participant_frames, ignore_index=True)
    expected_rows = len(settings) * len(subjects)
    if len(capacity_participants) != expected_rows:
        raise AssertionError(
            "Expected one participant burden row per cap and participant: "
            f"{len(capacity_participants)} != {expected_rows}"
        )
    capacity_quantiles = runtime_capacity_participant_burden_quantiles(
        capacity_participants
    )
    expected_quantile_rows = len(settings) * len(
        CAPACITY_PARTICIPANT_BURDEN_METRICS
    )
    if len(capacity_quantiles) != expected_quantile_rows:
        raise AssertionError(
            "Unexpected number of cap-level participant quantile rows: "
            f"{len(capacity_quantiles)} != {expected_quantile_rows}"
        )
    return sensitivity, capacity_participants, capacity_quantiles


def reorder_trace_columns(trace: pd.DataFrame) -> pd.DataFrame:
    leading = [
        "trace_id",
        "subject_id",
        "decision_index",
        "heldout_fold",
        "source_prediction_split",
        "risk_model_name",
        "risk_score",
        "uncertainty_score",
        "prompt_threshold",
        "uncertainty_threshold",
        "uncertainty_mode",
        "review_band_width",
        "threshold_distance",
        "runtime_auto_alert_cap",
        "runtime_auto_alert_count_before",
        "runtime_auto_alert_count_after",
        "runtime_review_cap",
        "runtime_review_count_before",
        "runtime_review_count_after",
        "runtime_operational_setting_source",
        "runtime_auto_alert_capacity_unit",
        "runtime_review_capacity_unit",
        "runtime_auto_alert_capacity_role",
        "runtime_review_capacity_role",
        "primary_route",
        "reason_code",
        *ROUTE_FLAG_COLUMNS,
        "license_id",
        "license_scope",
        "validation_unit",
        "asserted_claim",
        "permitted_claims_json",
        "blocked_claims_json",
        "admitted_evidence_json",
        "used_evidence_json",
        "excluded_evidence_json",
        "required_next_evidence_json",
        "eeg_gate_status",
        "eeg_evidence_admitted",
        "eeg_evidence_used",
        "validation_false_action_limit_per_100",
        "validation_false_action_criterion_role",
        "validation_false_action_criterion_scope",
        "runtime_false_action_criterion_used",
        "posthoc_proxy_label_available_to_runtime",
        "runtime_route_computed_before_label_access",
        "posthoc_observed_proxy_label",
        "decision_temporality",
    ]
    remaining = [column for column in trace.columns if column not in leading]
    return trace[leading + remaining]


def main() -> int:
    args = parse_args()
    if not 0.0 <= args.review_band_width <= 1.0:
        raise ValueError("review-band-width must be in [0, 1]")
    if args.runtime_auto_alert_cap < 0 or args.runtime_review_cap < 0:
        raise ValueError("runtime capacities must be non-negative")
    if args.injections_per_type < 20:
        raise ValueError("injections-per-type must be at least 20")

    selected = load_selected_parameters(args.selected_parameters, args.system_name)
    selected_models = set(selected["train_risk_model_name"].astype(str))
    predictions, subjects = load_predictions(args.predictions, selected_models)
    trace = build_trace(
        predictions,
        subjects,
        selected,
        runtime_auto_alert_cap=args.runtime_auto_alert_cap,
        runtime_review_cap=args.runtime_review_cap,
        review_band_width=args.review_band_width,
        false_action_limit_per_100=args.validation_false_action_limit_per_100,
    )
    trace["audit_dataset"] = "clean"
    clean_structural_audit = audit_frame(
        trace, validator="structural_baseline", check_sequence=False
    )
    clean_semantic_audit = audit_frame(
        trace, validator="semantic_validator", check_sequence=True
    )

    injected = inject_known_violations(
        trace, per_type=args.injections_per_type, seed=args.seed
    )
    injected_structural_audit = audit_frame(
        injected, validator="structural_baseline", check_sequence=False
    )
    injected_semantic_audit = audit_frame(
        injected, validator="semantic_validator", check_sequence=False
    )
    audit_results = pd.concat(
        (
            clean_structural_audit,
            clean_semantic_audit,
            injected_structural_audit,
            injected_semantic_audit,
        ),
        ignore_index=True,
    )
    comparison = validator_comparison(audit_results)

    clean_failures = int((~clean_semantic_audit["audit_pass"]).sum())
    structural_clean_failures = int(
        (~clean_structural_audit["audit_pass"]).sum()
    )
    missed_injections = int(
        (~injected_semantic_audit["expected_violation_detected"]).sum()
    )
    if clean_failures:
        failing = clean_semantic_audit[~clean_semantic_audit["audit_pass"]].head(10)
        raise AssertionError(f"Clean trace audit failed:\n{failing.to_string(index=False)}")
    if structural_clean_failures:
        failing = clean_structural_audit[
            ~clean_structural_audit["audit_pass"]
        ].head(10)
        raise AssertionError(
            f"Clean structural baseline failed:\n{failing.to_string(index=False)}"
        )
    if missed_injections:
        missed = injected_semantic_audit[
            ~injected_semantic_audit["expected_violation_detected"]
        ]
        raise AssertionError(f"Injected violations missed:\n{missed.to_string(index=False)}")

    one_hot_sum = trace[list(ROUTE_FLAG_COLUMNS)].sum(axis=1)
    if not one_hot_sum.eq(1).all():
        raise AssertionError("Primary routes are not mutually exclusive")
    route_rate_sum = float(
        sum(trace["primary_route"].eq(route).mean() for route in PRIMARY_ROUTES)
    )
    if not np.isclose(route_rate_sum, 1.0, atol=1e-12):
        raise AssertionError(f"Route rates do not sum to one: {route_rate_sum}")

    # Explicit negative-control check: labels are shuffled only after routing and
    # recomputing the label-free rule must leave every route unchanged.
    shuffled = trace.copy()
    shuffled["posthoc_observed_proxy_label"] = np.random.default_rng(args.seed).permutation(
        shuffled["posthoc_observed_proxy_label"].to_numpy()
    )
    rerouted = shuffled.apply(lambda row: expected_route_and_reason(row)[0], axis=1)
    label_shuffle_route_changes = int(
        (rerouted.to_numpy() != trace["primary_route"].to_numpy()).sum()
    )
    if label_shuffle_route_changes:
        raise AssertionError("A shuffled posthoc label changed a runtime route")

    metrics = validation_metrics(trace, args.validation_false_action_limit_per_100)
    participants = participant_burden(trace)
    burden_distribution = participant_burden_distribution(participants)
    bootstrap_cis = participant_bootstrap_confidence_intervals(
        participants, replicates=args.bootstrap_replicates, seed=args.seed
    )
    sensitivity, capacity_participants, capacity_quantiles = (
        runtime_capacity_sensitivity(
            predictions,
            subjects,
            selected,
            primary_trace=trace,
            primary_auto_alert_cap=args.runtime_auto_alert_cap,
            runtime_review_cap=args.runtime_review_cap,
            review_band_width=args.review_band_width,
            false_action_limit_per_100=(
                args.validation_false_action_limit_per_100
            ),
        )
    )
    pooled = metrics.iloc[0]
    fold_metrics = metrics[metrics["scope"].eq("outer_fold_heldout")]
    route_counts = {
        route: int(trace["primary_route"].eq(route).sum()) for route in PRIMARY_ROUTES
    }
    route_rates = {
        route: float(trace["primary_route"].eq(route).mean())
        for route in PRIMARY_ROUTES
    }
    burden_summary: dict[str, dict[str, float]] = {}
    for metric in (
        "n_action_bearing_routes",
        "n_false_action_routes",
        "n_runtime_auto_alert_capacity_blocks",
        "n_runtime_review_capacity_overflow_abstentions",
    ):
        distribution_row = burden_distribution[
            burden_distribution["metric"].eq(metric)
        ].iloc[0]
        burden_summary[metric] = {
            "median": float(distribution_row["median"]),
            "q1": float(distribution_row["q1"]),
            "q3": float(distribution_row["q3"]),
            "iqr": float(distribution_row["iqr"]),
            "p90": float(distribution_row["p90"]),
            "maximum": float(distribution_row["maximum"]),
        }
    summary = {
        "script_version": SCRIPT_VERSION,
        "seed": args.seed,
        "inputs": {
            "predictions": str(args.predictions.resolve()),
            "predictions_sha256": sha256_file(args.predictions),
            "selected_parameters": str(args.selected_parameters.resolve()),
            "selected_parameters_sha256": sha256_file(args.selected_parameters),
            "system_name": args.system_name,
        },
        "sample": {
            "n_subjects": int(trace["subject_id"].nunique()),
            "n_heldout_decisions": int(len(trace)),
            "n_outer_folds": int(trace["heldout_fold"].nunique()),
        },
        "runtime_operational_settings": {
            "provenance": (
                "fixed_operational_settings_not_optimized_on_heldout_labels"
            ),
            "review_band_width": args.review_band_width,
            "human_review_semantics": "risk_within_train_selected_threshold_band",
            "review_capacity_overflow_route": "abstain",
            "auto_alert_capacity": {
                "role": "pre_action_hard_count_constraint",
                "unit": "automated_alerts_per_heldout_participant_segment",
                "limit": args.runtime_auto_alert_cap,
                "n_blocks": int(
                    trace["reason_code"].eq("auto_alert_capacity_exhausted").sum()
                ),
            },
            "human_review_capacity": {
                "role": "pre_action_hard_count_constraint",
                "unit": "human_reviews_per_heldout_participant_segment",
                "limit": args.runtime_review_cap,
                "n_overflow_abstentions": int(
                    trace["reason_code"].eq("review_capacity_exhausted").sum()
                ),
            },
            "uses_posthoc_label": False,
            "capacity_sensitivity_labels": sensitivity[
                "runtime_auto_alert_cap_label"
            ].astype(str).tolist(),
        },
        "validation_false_action_criterion": {
            "role": "posthoc_validation_only",
            "scope": "alert_or_human_review",
            "limit_per_100_decisions": args.validation_false_action_limit_per_100,
            "pooled_observed_per_100": float(
                pooled["validation_false_actions_per_100_decisions"]
            ),
            "pooled_pass": bool(
                pooled["validation_false_action_criterion_pass"]
            ),
            "outer_folds_passing": int(
                fold_metrics["validation_false_action_criterion_pass"].sum()
            ),
            "outer_folds_total": int(len(fold_metrics)),
            "used_for_runtime_routing": False,
        },
        "routes": {
            "mutually_exclusive": True,
            "counts": route_counts,
            "rates": route_rates,
            "rate_sum": route_rate_sum,
        },
        "posthoc_performance": {
            "n_action_bearing_routes": int(pooled["n_action_bearing_routes"]),
            "action_route_precision": float(
                pooled["posthoc_action_route_precision"]
            ),
            "proxy_event_action_coverage": float(
                pooled["posthoc_proxy_event_action_coverage"]
            ),
            "automated_alert_precision": float(
                pooled["posthoc_automated_alert_precision"]
            ),
            "automated_false_alerts_per_100": float(
                pooled["posthoc_automated_false_alerts_per_100"]
            ),
        },
        "participant_uncertainty": {
            "bootstrap_unit": "participant",
            "bootstrap_method": "percentile",
            "bootstrap_replicates": args.bootstrap_replicates,
            "bootstrap_seed": args.seed,
            "burden_distribution": burden_summary,
        },
        "runtime_capacity_participant_burden": {
            "settings_provenance": (
                "fixed_operational_settings_not_optimized_on_heldout_labels"
            ),
            "rate_definition": "100_times_count_divided_by_participant_decisions",
            "non_event_status_source": "posthoc_observed_proxy_label",
            "posthoc_label_used_for_runtime_routing": False,
            "combined_non_event_escalation_definition": (
                "false_automated_alert_or_non_event_human_review"
            ),
            "action_bearing_route_definition": "alert_or_human_review",
            "n_participant_rows": int(len(capacity_participants)),
            "n_quantile_rows": int(len(capacity_quantiles)),
            "n_participants_per_setting": int(
                capacity_participants.groupby(
                    "runtime_auto_alert_cap_label", sort=False
                )["subject_id"].nunique().min()
            ),
            "settings": [
                {
                    "label": str(row.runtime_auto_alert_cap_label),
                    "numeric_cap": int(row.runtime_auto_alert_cap_numeric),
                    "effectively_unbounded": bool(
                        row.runtime_auto_alert_cap_is_unbounded
                    ),
                }
                for row in sensitivity.itertuples(index=False)
            ],
            "participant_identity_checks_passed": True,
        },
        "audit": {
            "same_records_for_both_validators": True,
            "clean_rows_per_validator": int(len(clean_semantic_audit)),
            "injected_rows_per_validator": int(len(injected_semantic_audit)),
            "injections_per_type": args.injections_per_type,
            "n_injection_types": int(injected["injection_type"].nunique()),
            "structural_baseline": {
                "scope": "required_field_presence_and_type_only",
                "clean_false_positive_rate": safe_ratio(
                    structural_clean_failures, int(len(clean_structural_audit))
                ),
                "injected_detection_sensitivity": float(
                    (~injected_structural_audit["audit_pass"]).mean()
                ),
            },
            "semantic_validator": {
                "clean_false_positive_rate": safe_ratio(
                    clean_failures, int(len(clean_semantic_audit))
                ),
                "injected_expected_violations_detected": int(
                    injected_semantic_audit["expected_violation_detected"].sum()
                ),
                "injected_detection_sensitivity": float(
                    (~injected_semantic_audit["audit_pass"]).mean()
                ),
            },
            "label_shuffle_route_changes": label_shuffle_route_changes,
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    trace_output = reorder_trace_columns(
        trace.drop(columns=["audit_dataset"], errors="ignore")
    )
    injected_output = reorder_trace_columns(
        injected.drop(
            columns=["audit_dataset"], errors="ignore"
        )
    )
    # Preserve injection metadata at the front of the injected artifact.
    injection_metadata = [
        "source_trace_id",
        "injection_type",
        "expected_rule_code",
    ]
    injected_output = injected_output[
        ["trace_id"]
        + injection_metadata
        + [
            column
            for column in injected_output.columns
            if column not in {"trace_id", *injection_metadata}
        ]
    ]

    trace_path = args.output_dir / "heldout_claim_license_trace.csv"
    injected_path = args.output_dir / "injected_violation_traces.csv"
    audit_path = args.output_dir / "trace_audit_results.csv"
    comparison_path = args.output_dir / "validator_comparison.csv"
    metrics_path = args.output_dir / "heldout_validation_metrics.csv"
    sensitivity_path = args.output_dir / "runtime_capacity_sensitivity.csv"
    capacity_participant_path = (
        args.output_dir / "runtime_capacity_participant_burden.csv"
    )
    capacity_quantiles_path = (
        args.output_dir / "runtime_capacity_participant_burden_quantiles.csv"
    )
    participant_path = args.output_dir / "reference_setting_participant_burden.csv"
    burden_distribution_path = (
        args.output_dir / "reference_setting_burden_distribution.csv"
    )
    bootstrap_path = args.output_dir / "reference_setting_bootstrap_ci.csv"
    summary_path = args.output_dir / "experiment_summary.json"
    trace_output.to_csv(trace_path, index=False, float_format="%.10g")
    injected_output.to_csv(injected_path, index=False, float_format="%.10g")
    audit_results.to_csv(audit_path, index=False)
    comparison.to_csv(comparison_path, index=False, float_format="%.10g")
    metrics.to_csv(metrics_path, index=False, float_format="%.10g")
    sensitivity.to_csv(sensitivity_path, index=False, float_format="%.10g")
    capacity_participants.to_csv(
        capacity_participant_path, index=False, float_format="%.10g"
    )
    capacity_quantiles.to_csv(
        capacity_quantiles_path, index=False, float_format="%.10g"
    )
    participants.to_csv(participant_path, index=False, float_format="%.10g")
    burden_distribution.to_csv(
        burden_distribution_path, index=False, float_format="%.10g"
    )
    bootstrap_cis.to_csv(bootstrap_path, index=False, float_format="%.10g")
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"trace: {trace_path}")
    print(f"injected: {injected_path}")
    print(f"audit: {audit_path}")
    print(f"validator_comparison: {comparison_path}")
    print(f"metrics: {metrics_path}")
    print(f"sensitivity: {sensitivity_path}")
    print(f"capacity_participant_burden: {capacity_participant_path}")
    print(f"capacity_participant_burden_quantiles: {capacity_quantiles_path}")
    print(f"participant_burden: {participant_path}")
    print(f"burden_distribution: {burden_distribution_path}")
    print(f"bootstrap_ci: {bootstrap_path}")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
