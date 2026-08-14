#!/usr/bin/env python3
"""Verify the completed official-v2 E1 replay and its v1 equivalence claims."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_ROOT = REPOSITORY_ROOT / "icair_2026" / "framework_v1"
DEFAULT_V1_EVIDENCE = FRAMEWORK_ROOT / "evidence"
DEFAULT_V2_EVIDENCE = FRAMEWORK_ROOT / "evidence_v2"
WORKSPACE_ROOT = REPOSITORY_ROOT.parents[2]
DEFAULT_COMPARISON_SUMMARY = (
    WORKSPACE_ROOT
    / "data"
    / "raw"
    / "external"
    / "mendeley_igt_v2_behavior_only"
    / "metadata"
    / "mendeley_v1_v2_comparison_summary.json"
)

sys.path.insert(0, str(FRAMEWORK_ROOT))
from e1.provenance import verify_finalized_manifest  # noqa: E402

MODELS = {
    "history_baseline",
    "regularised_logistic",
    "hist_gradient_boosting",
}
CAPS = {"2", "4", "6", "8", "effective_unbounded"}


def _external_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["dataset_id"].astype(str).str.startswith("mendeley_")].copy()


def _assert_numeric_equal(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    key: list[str],
    numeric: list[str],
    context: str,
) -> None:
    left_sorted = left.sort_values(key, kind="mergesort").reset_index(drop=True)
    right_sorted = right.sort_values(key, kind="mergesort").reset_index(drop=True)
    if len(left_sorted) != len(right_sorted):
        raise AssertionError(f"{context}: row-count mismatch")
    if not left_sorted[key].astype(str).equals(right_sorted[key].astype(str)):
        raise AssertionError(f"{context}: key mismatch")
    for column in numeric:
        if not np.allclose(
            left_sorted[column].to_numpy(dtype=float),
            right_sorted[column].to_numpy(dtype=float),
            rtol=0.0,
            atol=0.0,
            equal_nan=True,
        ):
            raise AssertionError(f"{context}: numeric mismatch in {column}")


def verify(v1_dir: Path, v2_dir: Path, comparison_summary: Path) -> dict[str, object]:
    verify_finalized_manifest(v2_dir)
    validation = json.loads((v2_dir / "validation_checks.json").read_text(encoding="utf-8"))
    failed = {
        key: value
        for key, value in validation.items()
        if key.endswith("_gate") and value != "pass"
    }
    if failed:
        raise AssertionError(f"Version-2 validation gates did not pass: {failed}")
    if validation.get("eeg_files_read") != 0 or validation.get("eeg_columns_read") != []:
        raise AssertionError("Version-2 validation does not prove EEG=0")
    if validation.get("external_labels_or_scores_used_for_fit_or_threshold") is not False:
        raise AssertionError("Version-2 selection-boundary gate is absent or failed")

    comparison = json.loads(comparison_summary.read_text(encoding="utf-8"))
    if not (
        comparison.get("raw_byte_identical_files") == 59
        and comparison.get("normalized_behavior_identical_files") == 59
        and comparison.get("v1_total_rows") == comparison.get("v2_total_rows") == 11_800
    ):
        raise AssertionError("v1/v2 behavior equivalence audit did not pass")

    performance_v1 = _external_rows(pd.read_csv(v1_dir / "model_performance.csv"))
    performance_v2 = _external_rows(pd.read_csv(v2_dir / "model_performance.csv"))
    pooled_v1 = performance_v1[performance_v1["aggregate_level"].eq("pooled")]
    pooled_v2 = performance_v2[performance_v2["aggregate_level"].eq("pooled")]
    if set(pooled_v2["model_name"]) != MODELS:
        raise AssertionError("Version-2 performance does not contain exactly three models")
    _assert_numeric_equal(
        pooled_v1,
        pooled_v2,
        key=["model_name", "aggregate_level", "outer_fold"],
        numeric=[
            "n_participants",
            "n_decisions",
            "n_positive",
            "positive_prevalence",
            "auroc",
            "average_precision",
            "brier_score",
            "balanced_accuracy_at_0_5",
            "f1_at_0_5",
            "ece_10_bin",
        ],
        context="external pooled performance",
    )

    workload_v1 = _external_rows(pd.read_csv(v1_dir / "route_workload_metrics.csv"))
    workload_v2 = _external_rows(pd.read_csv(v2_dir / "route_workload_metrics.csv"))
    pooled_workload_v1 = workload_v1[workload_v1["aggregate_level"].eq("pooled")]
    pooled_workload_v2 = workload_v2[workload_v2["aggregate_level"].eq("pooled")]
    if set(pooled_workload_v2["cap_label"].astype(str)) != CAPS:
        raise AssertionError("Version-2 workload does not contain every declared cap")
    workload_numeric = [
        column
        for column in pooled_workload_v1.columns
        if column not in {
            "dataset_id",
            "evaluation_scope",
            "model_name",
            "cap_label",
            "aggregate_level",
            "outer_fold",
        }
    ]
    _assert_numeric_equal(
        pooled_workload_v1,
        pooled_workload_v2,
        key=["model_name", "cap_label", "aggregate_level", "outer_fold"],
        numeric=workload_numeric,
        context="external pooled workload",
    )

    frozen_v1 = pd.read_csv(v1_dir / "frozen_operating_points.csv")
    frozen_v2 = pd.read_csv(v2_dir / "frozen_operating_points.csv")
    _assert_numeric_equal(
        frozen_v1,
        frozen_v2,
        key=["model_name"],
        numeric=[
            "prompt_threshold",
            "reference_alert_cap",
            "review_cap",
            "review_band_width",
            "uncertainty_threshold",
            "n_many_labs_oof_participants",
            "n_many_labs_oof_decisions",
        ],
        context="frozen operating points",
    )
    if frozen_v2["external_dataset_used_for_selection"].astype(bool).any():
        raise AssertionError("External dataset was marked as used for selection")

    cap8 = pooled_workload_v2[pooled_workload_v2["cap_label"].astype(str).eq("8")]
    summary = {
        "verification": "pass",
        "artifact_checksum_gate": "pass",
        "all_validation_gates": "pass",
        "three_models": sorted(MODELS),
        "capacities": sorted(CAPS),
        "bootstrap_replicates": int(
            pd.read_csv(v2_dir / "bootstrap_confidence_intervals.csv")[
                "bootstrap_replicates"
            ].max()
        ),
        "v1_v2_raw_files_identical": 59,
        "v1_v2_normalized_files_identical": 59,
        "v1_v2_external_metrics_exactly_identical": True,
        "v1_v2_frozen_operating_points_exactly_identical": True,
        "cap8_metrics": cap8[
            [
                "model_name",
                "alert_rate",
                "human_review_rate",
                "abstain_rate",
                "no_action_rate",
                "event_coverage_by_action",
                "action_precision",
                "false_actions_per_100",
                "event_coverage_by_alert",
                "alert_precision",
                "false_alerts_per_100",
                "auto_capacity_blocks_per_100",
            ]
        ].to_dict(orient="records"),
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-evidence", type=Path, default=DEFAULT_V1_EVIDENCE)
    parser.add_argument("--v2-evidence", type=Path, default=DEFAULT_V2_EVIDENCE)
    parser.add_argument(
        "--comparison-summary", type=Path, default=DEFAULT_COMPARISON_SUMMARY
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the verification JSON; stdout is always emitted.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = verify(args.v1_evidence, args.v2_evidence, args.comparison_summary)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
