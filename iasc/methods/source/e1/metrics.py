"""Prediction, workload, and participant-cluster bootstrap summaries."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    roc_auc_score,
)

from .routing import policy_metrics


def expected_calibration_error(
    y_true: np.ndarray,
    score: np.ndarray,
    *,
    n_bins: int = 10,
) -> float:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(score, dtype=float)
    bins = np.minimum((p * n_bins).astype(int), n_bins - 1)
    total = len(y)
    value = 0.0
    for index in range(n_bins):
        selected = bins == index
        if selected.any():
            value += selected.mean() * abs(float(y[selected].mean() - p[selected].mean()))
    return float(value) if total else np.nan


def prediction_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    y = frame["y_true"].to_numpy(dtype=int)
    score = frame["score"].to_numpy(dtype=float)
    if len(y) == 0:
        raise ValueError("Cannot score an empty prediction frame")
    both_classes = np.unique(y).size == 2
    predicted = score >= 0.5
    return {
        "n_participants": int(frame["subject_id"].nunique()),
        "n_decisions": int(len(frame)),
        "n_positive": int(y.sum()),
        "positive_prevalence": float(y.mean()),
        "auroc": float(roc_auc_score(y, score)) if both_classes else np.nan,
        "average_precision": float(average_precision_score(y, score))
        if y.sum()
        else np.nan,
        "brier_score": float(brier_score_loss(y, score)),
        "balanced_accuracy_at_0_5": float(balanced_accuracy_score(y, predicted))
        if both_classes
        else np.nan,
        "f1_at_0_5": float(f1_score(y, predicted, zero_division=0)),
        "ece_10_bin": expected_calibration_error(y, score, n_bins=10),
    }


def model_performance_table(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    group_columns = ["dataset_id", "evaluation_scope", "model_name"]
    for keys, frame in predictions.groupby(group_columns, sort=True):
        rows.append(
            {
                "dataset_id": keys[0],
                "evaluation_scope": keys[1],
                "model_name": keys[2],
                "aggregate_level": "pooled",
                "outer_fold": "all",
                **prediction_metrics(frame),
            }
        )
        if frame["outer_fold"].ge(0).any():
            for fold, fold_frame in frame.groupby("outer_fold", sort=True):
                rows.append(
                    {
                        "dataset_id": keys[0],
                        "evaluation_scope": keys[1],
                        "model_name": keys[2],
                        "aggregate_level": "outer_fold",
                        "outer_fold": int(fold),
                        **prediction_metrics(fold_frame),
                    }
                )
    return pd.DataFrame(rows)


def participant_workload_table(routes: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        "dataset_id",
        "evaluation_scope",
        "model_name",
        "cap_label",
        "automated_alert_cap",
        "subject_id",
    ]
    rows: list[dict[str, object]] = []
    for keys, frame in routes.groupby(group_columns, sort=True):
        metrics = policy_metrics(frame)
        outer_folds = sorted(frame["outer_fold"].unique())
        if len(outer_folds) != 1:
            raise AssertionError("A participant appears in multiple outer folds")
        rows.append(
            {
                **dict(zip(group_columns, keys, strict=True)),
                "outer_fold": int(outer_folds[0]),
                **metrics,
            }
        )
    return pd.DataFrame(rows)


def route_workload_table(routes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    group_columns = [
        "dataset_id",
        "evaluation_scope",
        "model_name",
        "cap_label",
        "automated_alert_cap",
    ]
    for keys, frame in routes.groupby(group_columns, sort=True):
        rows.append(
            {
                **dict(zip(group_columns, keys, strict=True)),
                "aggregate_level": "pooled",
                "outer_fold": "all",
                "n_participants": int(frame["subject_id"].nunique()),
                **policy_metrics(frame),
            }
        )
        if frame["outer_fold"].ge(0).any():
            for fold, fold_frame in frame.groupby("outer_fold", sort=True):
                rows.append(
                    {
                        **dict(zip(group_columns, keys, strict=True)),
                        "aggregate_level": "outer_fold",
                        "outer_fold": int(fold),
                        "n_participants": int(fold_frame["subject_id"].nunique()),
                        **policy_metrics(fold_frame),
                    }
                )
    return pd.DataFrame(rows)


def _weighted_rank_metrics(
    y: np.ndarray,
    score: np.ndarray,
    weights: np.ndarray,
    order: np.ndarray,
    group_starts: np.ndarray,
) -> tuple[float, float]:
    y_sorted = y[order]
    weight_sorted = weights[order]
    positive_by_score = np.add.reduceat(weight_sorted * y_sorted, group_starts)
    negative_by_score = np.add.reduceat(weight_sorted * (1 - y_sorted), group_starts)
    total_positive = float(positive_by_score.sum())
    total_negative = float(negative_by_score.sum())
    if total_positive <= 0 or total_negative <= 0:
        auc = np.nan
    else:
        negative_before = np.cumsum(negative_by_score) - negative_by_score
        auc = float(
            np.sum(positive_by_score * (negative_before + 0.5 * negative_by_score))
            / (total_positive * total_negative)
        )

    positive_desc = positive_by_score[::-1]
    negative_desc = negative_by_score[::-1]
    cumulative_positive = np.cumsum(positive_desc)
    cumulative_total = np.cumsum(positive_desc + negative_desc)
    if total_positive <= 0:
        average_precision = np.nan
    else:
        precision = np.divide(
            cumulative_positive,
            cumulative_total,
            out=np.zeros_like(cumulative_positive),
            where=cumulative_total > 0,
        )
        average_precision = float(
            np.sum((positive_desc / total_positive) * precision)
        )
    return auc, average_precision


def _prediction_bootstrap_distributions(
    frame: pd.DataFrame,
    *,
    replicates: int,
    seed: int,
) -> dict[str, np.ndarray]:
    subjects = sorted(frame["subject_id"].astype(str).unique())
    subject_to_code = {subject: index for index, subject in enumerate(subjects)}
    codes = frame["subject_id"].astype(str).map(subject_to_code).to_numpy(dtype=int)
    y = frame["y_true"].to_numpy(dtype=int)
    score = frame["score"].to_numpy(dtype=float)
    order = np.argsort(score, kind="mergesort")
    sorted_score = score[order]
    group_starts = np.flatnonzero(
        np.r_[True, sorted_score[1:] != sorted_score[:-1]]
    )
    rng = np.random.default_rng(seed)
    counts = rng.multinomial(
        len(subjects),
        np.full(len(subjects), 1.0 / len(subjects)),
        size=replicates,
    )
    distributions = {
        name: np.full(replicates, np.nan, dtype=float)
        for name in (
            "auroc",
            "average_precision",
            "brier_score",
            "balanced_accuracy_at_0_5",
        )
    }
    squared_error = (score - y) ** 2
    positive_mask = y == 1
    negative_mask = ~positive_mask
    predicted_positive = score >= 0.5
    for replicate in range(replicates):
        weights = counts[replicate, codes].astype(float)
        auc, average_precision = _weighted_rank_metrics(
            y, score, weights, order, group_starts
        )
        distributions["auroc"][replicate] = auc
        distributions["average_precision"][replicate] = average_precision
        total_weight = weights.sum()
        distributions["brier_score"][replicate] = (
            float(np.dot(weights, squared_error) / total_weight)
            if total_weight
            else np.nan
        )
        positive_weight = weights[positive_mask].sum()
        negative_weight = weights[negative_mask].sum()
        tpr = (
            weights[positive_mask & predicted_positive].sum() / positive_weight
            if positive_weight
            else np.nan
        )
        tnr = (
            weights[negative_mask & (~predicted_positive)].sum() / negative_weight
            if negative_weight
            else np.nan
        )
        distributions["balanced_accuracy_at_0_5"][replicate] = np.nanmean([tpr, tnr])
    return distributions


def _ratio(numerator: np.ndarray, denominator: np.ndarray, scale: float = 1.0) -> np.ndarray:
    return np.divide(
        scale * numerator,
        denominator,
        out=np.full_like(numerator, np.nan, dtype=float),
        where=denominator > 0,
    )


def _route_bootstrap_distributions(
    participants: pd.DataFrame,
    *,
    replicates: int,
    seed: int,
) -> dict[str, np.ndarray]:
    count_columns = [
        "n_decisions",
        "n_positive",
        "n_alert",
        "n_human_review",
        "n_abstain",
        "n_no_action",
        "n_action_routes",
        "n_true_action_routes",
        "n_false_action_routes",
        "n_true_alerts",
        "n_false_alerts",
        "n_auto_capacity_blocks",
        "n_review_capacity_overflow_abstentions",
    ]
    matrix = participants[count_columns].to_numpy(dtype=float)
    n_participants = len(participants)
    rng = np.random.default_rng(seed)
    weights = rng.multinomial(
        n_participants,
        np.full(n_participants, 1.0 / n_participants),
        size=replicates,
    )
    totals = weights @ matrix
    values = {name: totals[:, index] for index, name in enumerate(count_columns)}
    decisions = values["n_decisions"]
    positives = values["n_positive"]
    actions = values["n_action_routes"]
    alerts = values["n_alert"]
    return {
        "alert_rate": _ratio(values["n_alert"], decisions),
        "human_review_rate": _ratio(values["n_human_review"], decisions),
        "abstain_rate": _ratio(values["n_abstain"], decisions),
        "no_action_rate": _ratio(values["n_no_action"], decisions),
        "action_route_rate": _ratio(actions, decisions),
        "event_coverage_by_action": _ratio(values["n_true_action_routes"], positives),
        "action_precision": _ratio(values["n_true_action_routes"], actions),
        "false_actions_per_100": _ratio(
            values["n_false_action_routes"], decisions, 100.0
        ),
        "event_coverage_by_alert": _ratio(values["n_true_alerts"], positives),
        "alert_precision": _ratio(values["n_true_alerts"], alerts),
        "false_alerts_per_100": _ratio(values["n_false_alerts"], decisions, 100.0),
        "auto_capacity_blocks_per_100": _ratio(
            values["n_auto_capacity_blocks"], decisions, 100.0
        ),
    }


def _ci_rows(
    distributions: dict[str, np.ndarray],
    estimates: dict[str, float | int],
    *,
    family: str,
    identifiers: dict[str, object],
    replicates: int,
    seed: int,
    confidence_level: float,
) -> Iterable[dict[str, object]]:
    alpha = (1.0 - confidence_level) / 2.0
    low_percentile = 100.0 * alpha
    high_percentile = 100.0 * (1.0 - alpha)
    for metric, distribution in distributions.items():
        finite = distribution[np.isfinite(distribution)]
        yield {
            "metric_family": family,
            **identifiers,
            "metric": metric,
            "estimate": float(estimates[metric]),
            "ci_low": float(np.percentile(finite, low_percentile))
            if len(finite)
            else np.nan,
            "ci_high": float(np.percentile(finite, high_percentile))
            if len(finite)
            else np.nan,
            "confidence_level": confidence_level,
            "bootstrap_unit": "participant",
            "bootstrap_method": "cluster percentile; participants sampled with replacement",
            "bootstrap_replicates": replicates,
            "bootstrap_seed": seed,
            "finite_replicates": int(len(finite)),
        }


def participant_cluster_bootstrap(
    predictions: pd.DataFrame,
    participant_workload: pd.DataFrame,
    *,
    replicates: int,
    seed: int,
    confidence_level: float,
) -> pd.DataFrame:
    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    rows: list[dict[str, object]] = []
    prediction_groups = ["dataset_id", "evaluation_scope", "model_name"]
    for group_index, (keys, frame) in enumerate(
        predictions.groupby(prediction_groups, sort=True)
    ):
        estimates = prediction_metrics(frame)
        group_seed = seed + 10_000 * group_index
        distributions = _prediction_bootstrap_distributions(
            frame, replicates=replicates, seed=group_seed
        )
        rows.extend(
            _ci_rows(
                distributions,
                estimates,
                family="prediction",
                identifiers={
                    "dataset_id": keys[0],
                    "evaluation_scope": keys[1],
                    "model_name": keys[2],
                    "cap_label": "not_applicable",
                    "automated_alert_cap": np.nan,
                },
                replicates=replicates,
                seed=group_seed,
                confidence_level=confidence_level,
            )
        )

    route_groups = [
        "dataset_id",
        "evaluation_scope",
        "model_name",
        "cap_label",
        "automated_alert_cap",
    ]
    for group_index, (keys, frame) in enumerate(
        participant_workload.groupby(route_groups, sort=True)
    ):
        # Sum participant counts and derive the same ratios used in the pooled table.
        totals = frame[
            [
                "n_decisions",
                "n_positive",
                "n_alert",
                "n_human_review",
                "n_abstain",
                "n_no_action",
                "n_action_routes",
                "n_true_action_routes",
                "n_false_action_routes",
                "n_true_alerts",
                "n_false_alerts",
                "n_auto_capacity_blocks",
            ]
        ].sum()
        estimates = {
            "alert_rate": totals.n_alert / totals.n_decisions,
            "human_review_rate": totals.n_human_review / totals.n_decisions,
            "abstain_rate": totals.n_abstain / totals.n_decisions,
            "no_action_rate": totals.n_no_action / totals.n_decisions,
            "action_route_rate": totals.n_action_routes / totals.n_decisions,
            "event_coverage_by_action": totals.n_true_action_routes / totals.n_positive,
            "action_precision": totals.n_true_action_routes / totals.n_action_routes
            if totals.n_action_routes
            else np.nan,
            "false_actions_per_100": 100.0
            * totals.n_false_action_routes
            / totals.n_decisions,
            "event_coverage_by_alert": totals.n_true_alerts / totals.n_positive,
            "alert_precision": totals.n_true_alerts / totals.n_alert
            if totals.n_alert
            else np.nan,
            "false_alerts_per_100": 100.0 * totals.n_false_alerts / totals.n_decisions,
            "auto_capacity_blocks_per_100": 100.0
            * totals.n_auto_capacity_blocks
            / totals.n_decisions,
        }
        group_seed = seed + 1_000_000 + 10_000 * group_index
        distributions = _route_bootstrap_distributions(
            frame, replicates=replicates, seed=group_seed
        )
        rows.extend(
            _ci_rows(
                distributions,
                estimates,
                family="route_workload",
                identifiers={
                    "dataset_id": keys[0],
                    "evaluation_scope": keys[1],
                    "model_name": keys[2],
                    "cap_label": keys[3],
                    "automated_alert_cap": int(keys[4]),
                },
                replicates=replicates,
                seed=group_seed,
                confidence_level=confidence_level,
            )
        )
    return pd.DataFrame(rows)


__all__ = [
    "model_performance_table",
    "participant_cluster_bootstrap",
    "participant_workload_table",
    "prediction_metrics",
    "route_workload_table",
]
