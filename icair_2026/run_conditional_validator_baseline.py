#!/usr/bin/env python3
"""Run an independent row-local conditional-record validation baseline.

This baseline is deliberately implemented with the Python standard library and
does not import the claim-license semantic validator.  Its hand-written rules
are analogous in *scope* to conditional/dependent record constraints: they can
check relationships among fields in one serialized record, including the
before/after state carried by that record.  It is not an implementation or
performance evaluation of JSON Schema, CUE, SHACL, OPA/Rego, or any other policy
technology.

The validator never reads ``injection_type`` or ``expected_rule_code`` when it
makes a decision.  Those fields are used only after validation to stratify the
reported sensitivity.  The baseline also never compares different rows, so it
cannot verify that one participant's counter-after value equals the next
record's counter-before value.  That cross-record sequence invariant remains a
separate capability of the claim-license semantic validator.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SCRIPT_VERSION = "1.0.0"
FLOAT_ABS_TOLERANCE = 1e-8

PRIMARY_ROUTES = ("alert", "no_action", "abstain", "human_review")
ROUTE_FLAG_FIELDS = tuple(f"route_{route}" for route in PRIMARY_ROUTES)

DEFAULT_EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
DEFAULT_CLEAN = DEFAULT_EVIDENCE_DIR / "heldout_claim_license_trace.csv"
DEFAULT_INJECTED = DEFAULT_EVIDENCE_DIR / "injected_violation_traces.csv"

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
    # These source mirrors are present in the archived record and let the
    # baseline detect independently injected row-local provenance mismatches.
    "split",
    "model_name",
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
    *ROUTE_FLAG_FIELDS,
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
    "high_risk_probability",
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

RULE_GROUPS = {
    "primitive_shape": (
        "required value presence; string, integer, finite-number and Boolean "
        "types; JSON arrays of non-empty strings"
    ),
    "domains_and_mirrors": (
        "numeric bounds, enumerated routes, and duplicated source-field "
        "agreement within one record"
    ),
    "conditional_route": (
        "one-hot route flags and if/then route-reason guards derived from the "
        "record's score, uncertainty, threshold, band and current capacities"
    ),
    "within_record_counter_state": (
        "counter bounds and before/after transition implied by this record's route"
    ),
    "conditional_evidence": (
        "used-evidence subset, closed-EEG-gate restrictions, and declared "
        "post-hoc-label exclusion"
    ),
    "conditional_claim": (
        "route/reason-to-claim dependency plus permitted-versus-blocked claim checks"
    ),
    "runtime_validation_separation": (
        "runtime capacity role and prohibition on using the post-hoc false-action "
        "criterion as a route gate"
    ),
}

SEQUENCE_ONLY_INVARIANTS = (
    "For each participant, the next record's automated-alert count-before must "
    "equal the preceding record's count-after.",
    "For each participant, the next record's human-review count-before must "
    "equal the preceding record's count-after.",
    "Participant-segment reset boundaries, ordering, duplicate decisions, and "
    "missing intermediate decisions require comparison across records.",
    "A row's declaration that the outcome label was unavailable cannot by itself "
    "prove the absence of undeclared temporal leakage in upstream computation.",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, default=DEFAULT_CLEAN)
    parser.add_argument("--injected", type=Path, default=DEFAULT_INJECTED)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing validator input: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def value_is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def parse_integer(value: Any) -> int | None:
    if isinstance(value, bool) or value_is_missing(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or not numeric.is_integer():
        return None
    return int(numeric)


def parse_number(value: Any) -> float | None:
    if isinstance(value, bool) or value_is_missing(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def parse_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    return None


def parse_json_string_array(value: Any) -> list[str] | None:
    if value_is_missing(value):
        return None
    try:
        parsed = value if isinstance(value, list) else json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list):
        return None
    if any(not isinstance(item, str) or not item.strip() for item in parsed):
        return None
    return parsed


def nearly_equal(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=FLOAT_ABS_TOLERANCE)


def expected_claim_for_route(route: str, reason: str) -> str | None:
    """Independent row-local claim dependency used by the baseline."""
    if reason == "auto_alert_capacity_exhausted":
        return "runtime_auto_alert_capacity_blocks_action"
    if reason == "review_capacity_exhausted":
        return "runtime_review_capacity_blocks_action"
    return {
        "alert": "behavior_only_proxy_supports_automated_prompt",
        "human_review": "behavior_only_proxy_requires_human_review",
        "abstain": "behavior_only_proxy_uncertain_no_automated_action",
        "no_action": "behavior_only_proxy_does_not_authorize_action",
    }.get(route)


def allowed_route_reasons(
    *,
    risk_score: float,
    uncertainty_score: float,
    prompt_threshold: float,
    uncertainty_threshold: float,
    review_band_width: float,
    auto_count_before: int,
    auto_cap: int,
    review_count_before: int,
    review_cap: int,
) -> set[tuple[str, str]]:
    """Return route/reason pairs consistent with one serialized record.

    CSV serialization can collapse a binary floating-point value immediately
    above or below a threshold to the same decimal string.  At a boundary within
    ``FLOAT_ABS_TOLERANCE`` the conditional baseline therefore accepts either
    adjacent branch.  This prevents the baseline from pretending that precision
    discarded by serialization is still observable.
    """

    def route_without_uncertainty_gate() -> set[tuple[str, str]]:
        distance = abs(risk_score - prompt_threshold)

        def review_pair() -> tuple[str, str]:
            if review_count_before >= review_cap:
                return "abstain", "review_capacity_exhausted"
            return "human_review", "risk_within_threshold_review_band"

        def outside_band_pair() -> tuple[str, str]:
            if risk_score > prompt_threshold + review_band_width:
                if auto_count_before >= auto_cap:
                    return "no_action", "auto_alert_capacity_exhausted"
                return "alert", "risk_above_review_band"
            return "no_action", "risk_below_prompt_threshold"

        if distance < review_band_width - FLOAT_ABS_TOLERANCE:
            return {review_pair()}
        if distance > review_band_width + FLOAT_ABS_TOLERANCE:
            return {outside_band_pair()}
        return {review_pair(), outside_band_pair()}

    gate_pair = ("abstain", "uncertainty_gate")
    if uncertainty_score > uncertainty_threshold + FLOAT_ABS_TOLERANCE:
        return {gate_pair}
    if uncertainty_score < uncertainty_threshold - FLOAT_ABS_TOLERANCE:
        return route_without_uncertainty_gate()
    return {gate_pair, *route_without_uncertainty_gate()}


def validate_record(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Return row-local conditional-rule failures, independent of fault metadata."""
    failures: set[str] = set()
    required_fields = (
        REQUIRED_STRING_FIELDS
        + REQUIRED_INTEGER_FIELDS
        + REQUIRED_NUMERIC_FIELDS
        + REQUIRED_BOOLEAN_FIELDS
        + REQUIRED_JSON_LIST_FIELDS
    )
    for field in required_fields:
        if field not in record or value_is_missing(record.get(field)):
            failures.add("CRV_REQUIRED_FIELD")

    for field in REQUIRED_STRING_FIELDS:
        value = record.get(field)
        if not value_is_missing(value) and not isinstance(value, str):
            failures.add("CRV_STRING_TYPE")

    integers: dict[str, int | None] = {}
    for field in REQUIRED_INTEGER_FIELDS:
        integers[field] = parse_integer(record.get(field))
        if not value_is_missing(record.get(field)) and integers[field] is None:
            failures.add("CRV_INTEGER_TYPE")

    numbers: dict[str, float | None] = {}
    for field in REQUIRED_NUMERIC_FIELDS:
        numbers[field] = parse_number(record.get(field))
        if not value_is_missing(record.get(field)) and numbers[field] is None:
            failures.add("CRV_NUMBER_TYPE")

    booleans: dict[str, bool | None] = {}
    for field in REQUIRED_BOOLEAN_FIELDS:
        booleans[field] = parse_boolean(record.get(field))
        if not value_is_missing(record.get(field)) and booleans[field] is None:
            failures.add("CRV_BOOLEAN_TYPE")

    arrays: dict[str, list[str] | None] = {}
    for field in REQUIRED_JSON_LIST_FIELDS:
        arrays[field] = parse_json_string_array(record.get(field))
        if not value_is_missing(record.get(field)) and arrays[field] is None:
            failures.add("CRV_JSON_STRING_ARRAY_TYPE")

    route = str(record.get("primary_route", ""))
    reason = str(record.get("reason_code", ""))
    if route not in PRIMARY_ROUTES:
        failures.add("CRV_ROUTE_DOMAIN")

    route_flags = [integers.get(field) for field in ROUTE_FLAG_FIELDS]
    if all(flag is not None for flag in route_flags):
        if any(flag not in (0, 1) for flag in route_flags):
            failures.add("CRV_ROUTE_FLAG_DOMAIN")
        elif sum(flag for flag in route_flags if flag is not None) != 1:
            failures.add("CRV_ROUTE_ONE_HOT")
        elif route in PRIMARY_ROUTES and integers.get(f"route_{route}") != 1:
            failures.add("CRV_PRIMARY_ROUTE_FLAG_DEPENDENCY")

    # Numeric domains and source mirrors are record-local constraints.
    for field in (
        "risk_score",
        "uncertainty_score",
        "prompt_threshold",
        "uncertainty_threshold",
        "high_risk_probability",
    ):
        value = numbers.get(field)
        if value is not None and not 0.0 <= value <= 1.0:
            failures.add("CRV_PROBABILITY_DOMAIN")
    for field in ("review_band_width", "threshold_distance"):
        value = numbers.get(field)
        if value is not None and value < 0.0:
            failures.add("CRV_NONNEGATIVE_NUMERIC_DOMAIN")
    false_action_limit = numbers.get("validation_false_action_limit_per_100")
    if false_action_limit is not None and false_action_limit < 0.0:
        failures.add("CRV_NONNEGATIVE_NUMERIC_DOMAIN")

    decision_index = integers.get("decision_index")
    heldout_fold = integers.get("heldout_fold")
    proxy_label = integers.get("posthoc_observed_proxy_label")
    if decision_index is not None and decision_index < 0:
        failures.add("CRV_DECISION_INDEX_DOMAIN")
    if heldout_fold is not None and heldout_fold not in range(5):
        failures.add("CRV_HELDOUT_FOLD_DOMAIN")
    if proxy_label is not None and proxy_label not in (0, 1):
        failures.add("CRV_PROXY_LABEL_DOMAIN")

    risk = numbers.get("risk_score")
    source_risk = numbers.get("high_risk_probability")
    prompt = numbers.get("prompt_threshold")
    distance = numbers.get("threshold_distance")
    uncertainty = numbers.get("uncertainty_score")
    uncertainty_threshold = numbers.get("uncertainty_threshold")
    band = numbers.get("review_band_width")
    if (
        risk is not None
        and source_risk is not None
        and not nearly_equal(risk, source_risk)
    ):
        failures.add("CRV_RISK_SCORE_SOURCE_MISMATCH")
    if str(record.get("risk_model_name", "")) != str(record.get("model_name", "")):
        failures.add("CRV_MODEL_NAME_SOURCE_MISMATCH")
    if str(record.get("source_prediction_split", "")) != str(record.get("split", "")):
        failures.add("CRV_SPLIT_SOURCE_MISMATCH")
    if risk is not None and prompt is not None and distance is not None:
        if not nearly_equal(distance, abs(risk - prompt)):
            failures.add("CRV_THRESHOLD_DISTANCE_MISMATCH")
    if risk is not None and uncertainty is not None:
        uncertainty_mode = str(record.get("uncertainty_mode", ""))
        if uncertainty_mode == "probability_margin":
            expected_uncertainty = max(0.0, min(1.0, 1.0 - abs(2.0 * risk - 1.0)))
            if not nearly_equal(uncertainty, expected_uncertainty):
                failures.add("CRV_UNCERTAINTY_SCORE_MISMATCH")
        elif uncertainty_mode == "none":
            if not nearly_equal(uncertainty, 0.0):
                failures.add("CRV_UNCERTAINTY_SCORE_MISMATCH")
        else:
            failures.add("CRV_UNCERTAINTY_MODE_DOMAIN")

    auto_cap = integers.get("runtime_auto_alert_cap")
    auto_before = integers.get("runtime_auto_alert_count_before")
    auto_after = integers.get("runtime_auto_alert_count_after")
    review_cap = integers.get("runtime_review_cap")
    review_before = integers.get("runtime_review_count_before")
    review_after = integers.get("runtime_review_count_after")

    if None not in (auto_cap, auto_before, auto_after):
        assert (
            auto_cap is not None and auto_before is not None and auto_after is not None
        )
        expected_after = auto_before + int(route == "alert")
        if auto_after != expected_after:
            failures.add("CRV_AUTO_COUNTER_ROUTE_TRANSITION")
        if not 0 <= auto_before <= auto_after <= auto_cap:
            failures.add("CRV_AUTO_COUNTER_WITHIN_RECORD_BOUND")
    if None not in (review_cap, review_before, review_after):
        assert (
            review_cap is not None
            and review_before is not None
            and review_after is not None
        )
        expected_after = review_before + int(route == "human_review")
        if review_after != expected_after:
            failures.add("CRV_REVIEW_COUNTER_ROUTE_TRANSITION")
        if not 0 <= review_before <= review_after <= review_cap:
            failures.add("CRV_REVIEW_COUNTER_WITHIN_RECORD_BOUND")

    route_inputs = (
        risk,
        uncertainty,
        prompt,
        uncertainty_threshold,
        band,
        auto_before,
        auto_cap,
        review_before,
        review_cap,
    )
    if all(value is not None for value in route_inputs) and route in PRIMARY_ROUTES:
        allowed_pairs = allowed_route_reasons(
            risk_score=float(risk),
            uncertainty_score=float(uncertainty),
            prompt_threshold=float(prompt),
            uncertainty_threshold=float(uncertainty_threshold),
            review_band_width=float(band),
            auto_count_before=int(auto_before),
            auto_cap=int(auto_cap),
            review_count_before=int(review_before),
            review_cap=int(review_cap),
        )
        if (route, reason) not in allowed_pairs:
            failures.add("CRV_ROUTE_REASON_CONDITION")

    if (
        str(record.get("runtime_auto_alert_capacity_role", ""))
        != "pre_action_hard_count_constraint"
        or str(record.get("runtime_review_capacity_role", ""))
        != "pre_action_hard_count_constraint"
    ):
        failures.add("CRV_RUNTIME_CAPACITY_ROLE_CONDITION")
    if (
        str(record.get("validation_false_action_criterion_role", ""))
        != "posthoc_validation_only"
        or booleans.get("runtime_false_action_criterion_used") is not False
    ):
        failures.add("CRV_VALIDATION_CRITERION_RUNTIME_SEPARATION")
    if (
        str(record.get("validation_false_action_criterion_scope", ""))
        != "alert_or_human_review"
    ):
        failures.add("CRV_VALIDATION_CRITERION_SCOPE")

    admitted = arrays.get("admitted_evidence_json")
    used = arrays.get("used_evidence_json")
    excluded = arrays.get("excluded_evidence_json")
    permitted = arrays.get("permitted_claims_json")
    blocked = arrays.get("blocked_claims_json")
    if admitted is not None and used is not None and not set(used).issubset(admitted):
        failures.add("CRV_USED_EVIDENCE_DEPENDENCY")

    admitted_lower = {item.lower() for item in admitted or []}
    used_lower = {item.lower() for item in used or []}
    excluded_lower = {item.lower() for item in excluded or []}
    combined_runtime_evidence = admitted_lower | used_lower
    declared_eeg = any("eeg" in item for item in combined_runtime_evidence)
    if str(record.get("eeg_gate_status", "")).lower().startswith("closed"):
        if (
            declared_eeg
            or booleans.get("eeg_evidence_admitted") is not False
            or booleans.get("eeg_evidence_used") is not False
        ):
            failures.add("CRV_CLOSED_EEG_GATE_CONDITION")
        if "eeg" not in excluded_lower:
            failures.add("CRV_CLOSED_EEG_EXCLUSION_DEPENDENCY")
    if admitted is not None and used is not None:
        if booleans.get("eeg_evidence_admitted") != any(
            "eeg" in item for item in admitted_lower
        ):
            failures.add("CRV_EEG_ADMISSION_DECLARATION_MISMATCH")
        if booleans.get("eeg_evidence_used") != any(
            "eeg" in item for item in used_lower
        ):
            failures.add("CRV_EEG_USE_DECLARATION_MISMATCH")

    runtime_label_tokens = {
        item for item in combined_runtime_evidence if "posthoc_proxy_label" in item
    }
    if (
        booleans.get("posthoc_proxy_label_available_to_runtime") is not False
        or runtime_label_tokens
    ):
        failures.add("CRV_POSTHOC_LABEL_RUNTIME_EXCLUSION")
    if "posthoc_proxy_label" not in excluded_lower:
        failures.add("CRV_POSTHOC_LABEL_EXCLUSION_DEPENDENCY")
    if booleans.get("runtime_route_computed_before_label_access") is not True:
        failures.add("CRV_RUNTIME_TEMPORALITY_DECLARATION")

    asserted = str(record.get("asserted_claim", ""))
    expected_claim = expected_claim_for_route(route, reason)
    if expected_claim is not None and asserted != expected_claim:
        failures.add("CRV_ROUTE_REASON_CLAIM_DEPENDENCY")
    if permitted is not None and asserted not in permitted:
        failures.add("CRV_ASSERTED_CLAIM_NOT_PERMITTED")
    if blocked is not None and asserted in blocked:
        failures.add("CRV_ASSERTED_CLAIM_BLOCKED")
    if permitted is not None and blocked is not None and set(permitted) & set(blocked):
        failures.add("CRV_PERMITTED_BLOCKED_CLAIM_OVERLAP")

    return tuple(sorted(failures))


def validate_dataset(
    rows: Iterable[Mapping[str, Any]], *, dataset: str
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in rows:
        codes = validate_record(record)
        output.append(
            {
                "validator": "conditional_record_validator",
                "dataset": dataset,
                "trace_id": str(record.get("trace_id", "")),
                "source_trace_id": str(
                    record.get("source_trace_id", record.get("trace_id", ""))
                ),
                # Evaluation metadata is copied only after validate_record() has
                # returned.  It cannot affect the baseline's decision.
                "injection_type": str(record.get("injection_type", "")),
                "expected_rule_code": str(record.get("expected_rule_code", "")),
                "detected_rule_codes": "|".join(codes),
                "audit_pass": not codes,
                "record_flagged": bool(codes),
            }
        )
    return output


def summarize_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean = [row for row in results if row["dataset"] == "clean"]
    injected = [row for row in results if row["dataset"] == "injected"]
    summary: list[dict[str, Any]] = []

    def add_row(
        *,
        scope: str,
        injection_type: str,
        rows: list[dict[str, Any]],
        clean_scope: bool,
    ) -> None:
        flagged = sum(bool(row["record_flagged"]) for row in rows)
        expected_codes = sorted(
            {
                str(row["expected_rule_code"])
                for row in rows
                if row["expected_rule_code"]
            }
        )
        detected_codes = sorted(
            {
                code
                for row in rows
                for code in str(row["detected_rule_codes"]).split("|")
                if code
            }
        )
        summary.append(
            {
                "validator": "conditional_record_validator",
                "evaluation_scope": scope,
                "injection_type": injection_type,
                "expected_semantic_rule_codes": "|".join(expected_codes),
                "detected_conditional_rule_codes": "|".join(detected_codes),
                "fault_scope": "row_local_condition" if not clean_scope else "clean",
                "requires_cross_record_sequence": False,
                "n_records": len(rows),
                "n_flagged": flagged,
                "clean_false_positive_rate": (
                    flagged / len(rows) if clean_scope and rows else ""
                ),
                "detection_sensitivity": (
                    flagged / len(rows) if not clean_scope and rows else ""
                ),
            }
        )

    add_row(
        scope="clean",
        injection_type="none",
        rows=clean,
        clean_scope=True,
    )
    add_row(
        scope="injected_overall",
        injection_type="all",
        rows=injected,
        clean_scope=False,
    )
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in injected:
        by_family[str(row["injection_type"])].append(row)
    for injection_type in sorted(by_family):
        add_row(
            scope="injection_type",
            injection_type=injection_type,
            rows=by_family[injection_type],
            clean_scope=False,
        )
    return summary


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    clean_rows = read_csv(args.clean)
    injected_rows = read_csv(args.injected)
    results = validate_dataset(clean_rows, dataset="clean") + validate_dataset(
        injected_rows, dataset="injected"
    )
    comparison = summarize_results(results)

    clean_flagged = sum(
        row["dataset"] == "clean" and row["record_flagged"] for row in results
    )
    injected_flagged = sum(
        row["dataset"] == "injected" and row["record_flagged"] for row in results
    )

    results_path = args.output_dir / "conditional_record_validator_results.csv"
    comparison_path = args.output_dir / "conditional_record_validator_comparison.csv"
    summary_path = args.output_dir / "conditional_record_validator_summary.json"
    write_csv(results_path, results)
    write_csv(comparison_path, comparison)

    summary = {
        "script": Path(__file__).name,
        "script_version": SCRIPT_VERSION,
        "validator": "conditional_record_validator",
        "implementation": "independent_python_standard_library_row_local_rules",
        "not_implementations_of": [
            "JSON Schema",
            "CUE",
            "SHACL",
            "OPA/Rego",
        ],
        "decision_uses_fault_metadata": False,
        "cross_record_sequence_checked": False,
        "input_sha256": {
            "clean": sha256_file(args.clean),
            "injected": sha256_file(args.injected),
        },
        "counts": {
            "clean_records": len(clean_rows),
            "clean_flagged": clean_flagged,
            "clean_false_positive_rate": (
                clean_flagged / len(clean_rows) if clean_rows else None
            ),
            "injected_records": len(injected_rows),
            "injected_flagged": injected_flagged,
            "injected_detection_sensitivity": (
                injected_flagged / len(injected_rows) if injected_rows else None
            ),
            "injection_families": len(
                {row.get("injection_type", "") for row in injected_rows}
            ),
        },
        "hand_written_rule_groups": RULE_GROUPS,
        "sequence_only_invariants_not_checked": SEQUENCE_ONLY_INVARIANTS,
        "current_injection_scope": (
            "All current injected mutations are contradictions visible within one "
            "record, including the capacity-overrun mutations. None directly tests "
            "cross-record counter continuity."
        ),
        "artifacts": {
            "row_results": results_path.name,
            "comparison": comparison_path.name,
        },
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"clean: {len(clean_rows)} records, {clean_flagged} flagged")
    print(
        f"injected: {len(injected_rows)} records, {injected_flagged} flagged "
        f"across {summary['counts']['injection_families']} families"
    )
    print(f"row results: {results_path}")
    print(f"comparison: {comparison_path}")
    print(f"summary: {summary_path}")

    if clean_flagged:
        raise AssertionError(
            f"Conditional record validator flagged {clean_flagged} clean records"
        )
    if injected_flagged != len(injected_rows):
        raise AssertionError(
            "Conditional record validator missed "
            f"{len(injected_rows) - injected_flagged} injected records"
        )


if __name__ == "__main__":
    main()
