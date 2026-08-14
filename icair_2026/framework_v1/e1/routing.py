"""Label-free four-route protocol and train-only operating-point selection."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import PRIMARY_ROUTES, E1Config


def compute_uncertainty(scores: np.ndarray, mode: str) -> np.ndarray:
    values = np.asarray(scores, dtype=float)
    if mode == "probability_margin":
        return np.clip(1.0 - np.abs(2.0 * values - 1.0), 0.0, 1.0)
    if mode == "none":
        return np.zeros(len(values), dtype=float)
    raise ValueError(f"Unsupported uncertainty mode {mode!r}")


def route_frame(
    frame: pd.DataFrame,
    *,
    prompt_threshold: float,
    automated_alert_cap: int,
    review_cap: int,
    review_band_width: float,
    uncertainty_threshold: float,
    uncertainty_mode: str,
) -> pd.DataFrame:
    """Route sequentially using only score, frozen settings, and prior counters."""

    if automated_alert_cap < 0 or review_cap < 0:
        raise ValueError("capacities must be non-negative")
    required = {"subject_id", "trial_id", "score"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Routing input missing {sorted(missing)}")
    routed = frame.sort_values(["subject_id", "trial_id"], kind="mergesort").copy()
    score = routed["score"].to_numpy(dtype=float)
    if not np.isfinite(score).all() or ((score < 0) | (score > 1)).any():
        raise ValueError("scores must be finite probabilities")
    uncertainty = compute_uncertainty(score, uncertainty_mode)
    uncertainty_abstain = uncertainty >= float(uncertainty_threshold)
    threshold_distance = np.abs(score - float(prompt_threshold))
    review_candidate = (~uncertainty_abstain) & (
        threshold_distance <= float(review_band_width)
    )
    auto_candidate = (~uncertainty_abstain) & (
        score > float(prompt_threshold) + float(review_band_width)
    )

    subject = routed["subject_id"]
    review_seen = (
        pd.Series(review_candidate.astype(int), index=routed.index)
        .groupby(subject, sort=False)
        .cumsum()
        .to_numpy(dtype=int)
    )
    review_before = np.minimum(review_seen - review_candidate.astype(int), review_cap)
    review_available = review_before < review_cap
    human_review = review_candidate & review_available
    review_overflow = review_candidate & (~review_available)

    auto_seen = (
        pd.Series(auto_candidate.astype(int), index=routed.index)
        .groupby(subject, sort=False)
        .cumsum()
        .to_numpy(dtype=int)
    )
    auto_before = np.minimum(
        auto_seen - auto_candidate.astype(int), automated_alert_cap
    )
    auto_available = auto_before < automated_alert_cap
    alert = auto_candidate & auto_available
    auto_overflow = auto_candidate & (~auto_available)

    abstain = uncertainty_abstain | review_overflow
    no_action = (~abstain) & (~alert) & (~human_review)
    route = np.full(len(routed), "no_action", dtype=object)
    route[abstain] = "abstain"
    route[alert] = "alert"
    route[human_review] = "human_review"
    reason = np.full(len(routed), "risk_below_prompt_threshold", dtype=object)
    reason[uncertainty_abstain] = "uncertainty_gate"
    reason[review_overflow] = "review_capacity_exhausted"
    reason[auto_overflow] = "auto_alert_capacity_exhausted"
    reason[alert] = "risk_above_review_band"
    reason[human_review] = "risk_within_threshold_review_band"

    routed["uncertainty_score"] = uncertainty
    routed["prompt_threshold"] = float(prompt_threshold)
    routed["uncertainty_threshold"] = float(uncertainty_threshold)
    routed["review_band_width"] = float(review_band_width)
    routed["automated_alert_cap"] = int(automated_alert_cap)
    routed["review_cap"] = int(review_cap)
    routed["primary_route"] = route
    routed["reason_code"] = reason
    routed["auto_alert_count_before"] = auto_before
    routed["auto_alert_count_after"] = auto_before + alert.astype(int)
    routed["review_count_before"] = review_before
    routed["review_count_after"] = review_before + human_review.astype(int)
    for route_name in PRIMARY_ROUTES:
        routed[f"route_{route_name}"] = (route == route_name).astype(np.int8)

    flag_sum = routed[[f"route_{name}" for name in PRIMARY_ROUTES]].sum(axis=1)
    if not flag_sum.eq(1).all():
        raise AssertionError("Primary routes are not mutually exclusive and exhaustive")
    participant_alerts = routed.groupby("subject_id")["route_alert"].sum()
    participant_reviews = routed.groupby("subject_id")["route_human_review"].sum()
    if (participant_alerts > automated_alert_cap).any():
        raise AssertionError("Automated-alert capacity was exceeded")
    if (participant_reviews > review_cap).any():
        raise AssertionError("Human-review capacity was exceeded")
    if not np.array_equal(no_action, routed["primary_route"].eq("no_action")):
        raise AssertionError("no_action construction mismatch")
    return routed.reset_index(drop=True)


def policy_metrics(routed: pd.DataFrame) -> dict[str, float | int]:
    n = len(routed)
    if n == 0:
        raise ValueError("Cannot summarize an empty route frame")
    y = routed["y_true"].to_numpy(dtype=int)
    alert = routed["primary_route"].eq("alert").to_numpy()
    review = routed["primary_route"].eq("human_review").to_numpy()
    action = alert | review
    positives = int(y.sum())
    n_action = int(action.sum())
    true_action = int(y[action].sum()) if n_action else 0
    false_action = n_action - true_action
    n_alert = int(alert.sum())
    true_alert = int(y[alert].sum()) if n_alert else 0
    return {
        "n_decisions": n,
        "n_positive": positives,
        "n_alert": n_alert,
        "n_human_review": int(review.sum()),
        "n_abstain": int(routed["primary_route"].eq("abstain").sum()),
        "n_no_action": int(routed["primary_route"].eq("no_action").sum()),
        "n_action_routes": n_action,
        "n_true_action_routes": true_action,
        "n_false_action_routes": false_action,
        "n_true_alerts": true_alert,
        "n_false_alerts": n_alert - true_alert,
        "n_auto_capacity_blocks": int(
            routed["reason_code"].eq("auto_alert_capacity_exhausted").sum()
        ),
        "n_review_capacity_overflow_abstentions": int(
            routed["reason_code"].eq("review_capacity_exhausted").sum()
        ),
        "alert_rate": n_alert / n,
        "human_review_rate": float(review.mean()),
        "abstain_rate": float(routed["primary_route"].eq("abstain").mean()),
        "no_action_rate": float(routed["primary_route"].eq("no_action").mean()),
        "action_route_rate": n_action / n,
        "event_coverage_by_action": true_action / positives if positives else np.nan,
        "action_precision": true_action / n_action if n_action else np.nan,
        "false_actions_per_100": 100.0 * false_action / n,
        "event_coverage_by_alert": true_alert / positives if positives else np.nan,
        "alert_precision": true_alert / n_alert if n_alert else np.nan,
        "false_alerts_per_100": 100.0 * (n_alert - true_alert) / n,
        "auto_capacity_blocks_per_100": 100.0
        * routed["reason_code"].eq("auto_alert_capacity_exhausted").sum()
        / n,
        "route_rate_sum": float(
            sum(routed["primary_route"].eq(name).mean() for name in PRIMARY_ROUTES)
        ),
    }


def threshold_grid(config: E1Config) -> np.ndarray:
    stop = config.threshold_grid_stop + config.threshold_grid_step / 2.0
    return np.round(
        np.arange(config.threshold_grid_start, stop, config.threshold_grid_step), 10
    )


def select_operating_point(calibration: pd.DataFrame, config: E1Config) -> dict[str, Any]:
    """Select on grouped OOF calibration scores at the frozen reference cap."""

    rows: list[dict[str, Any]] = []
    for threshold in threshold_grid(config):
        routed = route_frame(
            calibration,
            prompt_threshold=float(threshold),
            automated_alert_cap=config.reference_alert_cap,
            review_cap=config.review_cap,
            review_band_width=config.review_band_width,
            uncertainty_threshold=config.uncertainty_threshold,
            uncertainty_mode=config.uncertainty_mode,
        )
        metrics = policy_metrics(routed)
        rows.append({"prompt_threshold": float(threshold), **metrics})
    eligible = [
        row
        for row in rows
        if row["n_action_routes"] > 0
        and row["false_actions_per_100"] <= config.false_action_limit_per_100
        and np.isfinite(row["action_precision"])
        and row["action_precision"] >= config.action_precision_floor
    ]
    if eligible:
        selected = max(
            eligible,
            key=lambda row: (
                row["event_coverage_by_action"],
                row["action_precision"],
                -row["false_actions_per_100"],
                -row["action_route_rate"],
                row["prompt_threshold"],
            ),
        ).copy()
        selected["selection_constraints_satisfied"] = True
    else:
        selected = min(
            rows,
            key=lambda row: (
                max(0.0, row["false_actions_per_100"] - config.false_action_limit_per_100),
                max(
                    0.0,
                    config.action_precision_floor
                    - (row["action_precision"] if np.isfinite(row["action_precision"]) else 0.0),
                ),
                -row["event_coverage_by_action"],
                row["action_route_rate"],
            ),
        ).copy()
        selected["selection_constraints_satisfied"] = False
    selected["selection_source"] = (
        "participant-grouped OOF predictions from training participants only; "
        "reference automated-alert cap=8"
    )
    return selected


def assert_label_independent_routing(routed_input: pd.DataFrame, **route_kwargs: Any) -> None:
    original = route_frame(routed_input, **route_kwargs)
    shuffled = routed_input.copy()
    if "y_true" in shuffled.columns:
        shuffled["y_true"] = shuffled["y_true"].sample(
            frac=1.0, random_state=17
        ).to_numpy()
    rerouted = route_frame(shuffled, **route_kwargs)
    columns = ["primary_route", "reason_code"]
    if not original[columns].equals(rerouted[columns]):
        raise AssertionError("Posthoc labels changed runtime routing")


__all__ = [
    "assert_label_independent_routing",
    "compute_uncertainty",
    "policy_metrics",
    "route_frame",
    "select_operating_point",
]
