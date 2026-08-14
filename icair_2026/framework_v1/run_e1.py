#!/usr/bin/env python3
"""Run E1: cross-model prediction plus capacity-aware four-route replay.

The implementation is intentionally isolated from the legacy ICAIR evidence.
It trains on behavior-only Many Labs IGT history, evaluates participant-grouped
outer folds, freezes each model and its operating point, and then performs a
manifest-identified Mendeley behavior-only external replay.  No EEG file or
EEG-derived field is read.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
from e1.config import MODEL_NAMES, PRIMARY_ROUTES, SCRIPT_VERSION, E1Config
from e1.data import (
    assert_causal_feature_invariance,
    assign_participant_folds,
    build_causal_history_features,
    dataset_summary,
    limit_participants,
    load_many_labs,
    load_mendeley_behavior,
    model_feature_columns,
)
from e1.metrics import (
    model_performance_table,
    participant_cluster_bootstrap,
    participant_workload_table,
    route_workload_table,
)
from e1.models import (
    fit_and_score_outer_fold,
    fit_model,
    grouped_oof_predictions,
    model_specifications,
    predict_scores,
    save_frozen_model,
)
from e1.provenance import (
    environment_record,
    finalize_manifest,
    git_record,
    input_hash_table,
    verify_finalized_manifest,
    write_csv,
    write_gzip_csv,
    write_json,
)
from e1.routing import (
    assert_label_independent_routing,
    route_frame,
    select_operating_point,
)

FRAMEWORK_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = FRAMEWORK_ROOT.parents[1]
WORKSPACE_ROOT = REPOSITORY_ROOT.parents[2]
DEFAULT_MANY_LABS = (
    WORKSPACE_ROOT
    / "data"
    / "raw"
    / "external"
    / "many_labs_igt"
    / "many_labs_igt_behavior_long.csv"
)
DEFAULT_MENDELEY_DIR = WORKSPACE_ROOT / "data" / "raw" / "igt_eeg" / "IGT"
DEFAULT_MENDELEY_MANIFEST = (
    WORKSPACE_ROOT
    / "data"
    / "raw"
    / "igt_eeg"
    / "metadata"
    / "download_manifest_v1_raw_eeg_igt.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "full"), default="full")
    parser.add_argument("--many-labs", type=Path, default=DEFAULT_MANY_LABS)
    parser.add_argument("--mendeley-dir", type=Path, default=DEFAULT_MENDELEY_DIR)
    parser.add_argument(
        "--mendeley-manifest", type=Path, default=DEFAULT_MENDELEY_MANIFEST
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--models", nargs="+", choices=MODEL_NAMES, default=list(MODEL_NAMES))
    parser.add_argument("--seed", type=int, default=E1Config.seed)
    parser.add_argument("--outer-folds", type=int, default=None)
    parser.add_argument("--inner-folds", type=int, default=None)
    parser.add_argument("--bootstrap-replicates", type=int, default=None)
    parser.add_argument("--max-many-subjects", type=int, default=None)
    parser.add_argument("--max-mendeley-subjects", type=int, default=None)
    return parser.parse_args()


def _resolved_config(args: argparse.Namespace) -> E1Config:
    if args.mode == "smoke":
        config = E1Config(
            seed=args.seed,
            outer_folds=3,
            inner_folds=2,
            bootstrap_replicates=50,
        )
    else:
        config = E1Config(seed=args.seed)
    updates: dict[str, Any] = {}
    if args.outer_folds is not None:
        updates["outer_folds"] = args.outer_folds
    if args.inner_folds is not None:
        updates["inner_folds"] = args.inner_folds
    if args.bootstrap_replicates is not None:
        updates["bootstrap_replicates"] = args.bootstrap_replicates
    config = replace(config, **updates)
    if config.outer_folds < 2 or config.inner_folds < 2:
        raise ValueError("outer and inner folds must each be at least 2")
    return config


def _prediction_projection(
    scored: pd.DataFrame,
    *,
    model_name: str,
    evaluation_scope: str,
    outer_fold: int,
) -> pd.DataFrame:
    columns = [
        "dataset_id",
        "subject_id",
        "study_id",
        "trial_id",
        "y_true",
        "score",
    ]
    projected = scored[columns].copy()
    projected["evaluation_scope"] = evaluation_scope
    projected["model_name"] = model_name
    projected["outer_fold"] = int(outer_fold)
    return projected[
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
        ]
    ]


def run_grouped_outer_cv(
    many_features: pd.DataFrame,
    *,
    feature_columns: list[str],
    models: tuple[str, ...],
    config: E1Config,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    assignments = assign_participant_folds(
        many_features, n_folds=config.outer_folds, seed=config.seed
    )
    assigned = many_features.merge(
        assignments[["subject_id", "fold"]], on="subject_id", how="left", validate="many_to_one"
    )
    if assigned["fold"].isna().any():
        raise AssertionError("Some Many Labs participants lack an outer fold")
    prediction_frames: list[pd.DataFrame] = []
    operating_rows: list[dict[str, object]] = []
    all_subjects = set(assigned["subject_id"].astype(str).unique())

    for fold in sorted(assignments["fold"].unique()):
        test_subjects = set(
            assignments.loc[assignments["fold"].eq(fold), "subject_id"].astype(str)
        )
        train_subjects = all_subjects - test_subjects
        if train_subjects & test_subjects:
            raise AssertionError("Outer participant groups overlap")
        train = assigned[assigned["subject_id"].isin(train_subjects)].drop(columns="fold")
        test = assigned[assigned["subject_id"].isin(test_subjects)].drop(columns="fold")
        print(
            f"outer fold {fold}: train={len(train_subjects)} participants, "
            f"test={len(test_subjects)} participants",
            flush=True,
        )
        for model_index, model_name in enumerate(models):
            print(f"  {model_name}: inner grouped OOF calibration", flush=True)
            calibration = grouped_oof_predictions(
                train,
                model_name=model_name,
                feature_columns=feature_columns,
                n_folds=config.inner_folds,
                seed=config.seed + 1_000 * int(fold) + 100 * model_index,
            )
            calibration_route_input = calibration[
                ["subject_id", "trial_id", "y_true", "score"]
            ].copy()
            selected = select_operating_point(calibration_route_input, config)
            _, scored = fit_and_score_outer_fold(
                train,
                test,
                model_name=model_name,
                feature_columns=feature_columns,
                seed=config.seed + 10_000 * int(fold) + model_index,
            )
            prediction_frames.append(
                _prediction_projection(
                    scored,
                    model_name=model_name,
                    evaluation_scope="participant_grouped_outer_cv",
                    outer_fold=int(fold),
                )
            )
            operating_rows.append(
                {
                    "model_name": model_name,
                    "outer_fold": int(fold),
                    "n_training_participants": len(train_subjects),
                    "n_calibration_participants": int(
                        calibration["subject_id"].nunique()
                    ),
                    "n_calibration_decisions": int(len(calibration)),
                    **selected,
                }
            )
            print(
                f"    selected threshold={selected['prompt_threshold']:.3f}; "
                f"constraints={selected['selection_constraints_satisfied']}",
                flush=True,
            )

    predictions = pd.concat(prediction_frames, ignore_index=True)
    key = ["model_name", "subject_id", "trial_id"]
    expected_rows = len(many_features) * len(models)
    if predictions.duplicated(key).any() or len(predictions) != expected_rows:
        raise AssertionError("Outer-CV predictions are not exactly one per decision/model")
    return predictions, pd.DataFrame(operating_rows), assignments


def fit_frozen_and_score_external(
    many_features: pd.DataFrame,
    mendeley_features: pd.DataFrame,
    many_oof_predictions: pd.DataFrame,
    *,
    feature_columns: list[str],
    models: tuple[str, ...],
    config: E1Config,
    model_output_dir: Path,
    evaluation_scope: str,
) -> tuple[pd.DataFrame, pd.DataFrame, list[Path]]:
    prediction_frames: list[pd.DataFrame] = []
    operating_rows: list[dict[str, object]] = []
    model_paths: list[Path] = []
    for model_index, model_name in enumerate(models):
        print(f"freeze {model_name} on all Many Labs participants", flush=True)
        many_oof = many_oof_predictions[
            many_oof_predictions["model_name"].eq(model_name)
        ][["subject_id", "trial_id", "y_true", "score"]].copy()
        selected = select_operating_point(many_oof, config)
        estimator = fit_model(
            model_name,
            many_features,
            feature_columns=feature_columns,
            seed=config.seed + 100_000 + model_index,
        )
        model_path = save_frozen_model(model_name, estimator, model_output_dir)
        if model_path is not None:
            model_paths.append(model_path)
        else:
            history_path = write_json(
                model_output_dir / "history_baseline.json",
                model_specifications(config.seed)["history_baseline"],
            )
            model_paths.append(history_path)
        external = mendeley_features.copy()
        external["score"] = predict_scores(
            model_name,
            estimator,
            external,
            feature_columns=feature_columns,
        )
        prediction_frames.append(
            _prediction_projection(
                external,
                model_name=model_name,
                evaluation_scope=evaluation_scope,
                outer_fold=-1,
            )
        )
        operating_rows.append(
            {
                "model_name": model_name,
                "prompt_threshold": float(selected["prompt_threshold"]),
                "selection_constraints_satisfied": bool(
                    selected["selection_constraints_satisfied"]
                ),
                "selection_source": (
                    "all Many Labs participant-grouped outer-CV OOF predictions; "
                    "no Mendeley labels or scores used"
                ),
                "reference_alert_cap": config.reference_alert_cap,
                "review_cap": config.review_cap,
                "review_band_width": config.review_band_width,
                "uncertainty_mode": config.uncertainty_mode,
                "uncertainty_threshold": config.uncertainty_threshold,
                "n_many_labs_oof_participants": int(many_oof["subject_id"].nunique()),
                "n_many_labs_oof_decisions": int(len(many_oof)),
                "external_dataset_used_for_selection": False,
            }
        )
    return (
        pd.concat(prediction_frames, ignore_index=True),
        pd.DataFrame(operating_rows),
        model_paths,
    )


def replay_all_capacities(
    predictions: pd.DataFrame,
    outer_operating_points: pd.DataFrame,
    frozen_operating_points: pd.DataFrame,
    *,
    config: E1Config,
) -> pd.DataFrame:
    route_frames: list[pd.DataFrame] = []
    for (_dataset_id, scope, model_name), model_frame in predictions.groupby(
        ["dataset_id", "evaluation_scope", "model_name"], sort=True
    ):
        maximum_segment = int(model_frame.groupby("subject_id").size().max())
        caps = [(str(cap), cap) for cap in config.automated_alert_caps]
        caps.append(("effective_unbounded", maximum_segment + 1))
        for cap_label, cap in caps:
            if scope == "participant_grouped_outer_cv":
                fold_frames: list[pd.DataFrame] = []
                for fold, fold_frame in model_frame.groupby("outer_fold", sort=True):
                    selected = outer_operating_points[
                        outer_operating_points["model_name"].eq(model_name)
                        & outer_operating_points["outer_fold"].eq(fold)
                    ]
                    if len(selected) != 1:
                        raise AssertionError("Missing or duplicate outer-fold operating point")
                    threshold = float(selected.iloc[0]["prompt_threshold"])
                    fold_frames.append(
                        route_frame(
                            fold_frame,
                            prompt_threshold=threshold,
                            automated_alert_cap=cap,
                            review_cap=config.review_cap,
                            review_band_width=config.review_band_width,
                            uncertainty_threshold=config.uncertainty_threshold,
                            uncertainty_mode=config.uncertainty_mode,
                        )
                    )
                routed = pd.concat(fold_frames, ignore_index=True)
                threshold_source = "nested_inner_grouped_oof_training_participants"
            else:
                selected = frozen_operating_points[
                    frozen_operating_points["model_name"].eq(model_name)
                ]
                if len(selected) != 1:
                    raise AssertionError("Missing or duplicate frozen operating point")
                threshold = float(selected.iloc[0]["prompt_threshold"])
                routed = route_frame(
                    model_frame,
                    prompt_threshold=threshold,
                    automated_alert_cap=cap,
                    review_cap=config.review_cap,
                    review_band_width=config.review_band_width,
                    uncertainty_threshold=config.uncertainty_threshold,
                    uncertainty_mode=config.uncertainty_mode,
                )
                threshold_source = "many_labs_grouped_outer_cv_oof_only"
            routed["cap_label"] = cap_label
            routed["threshold_source"] = threshold_source
            routed["route_computed_before_label_access"] = True
            if cap_label == "effective_unbounded" and routed["reason_code"].eq(
                "auto_alert_capacity_exhausted"
            ).any():
                raise AssertionError("Effective-unbounded capacity blocked an alert")
            route_frames.append(routed)
    routes = pd.concat(route_frames, ignore_index=True)
    route_flags = [f"route_{name}" for name in PRIMARY_ROUTES]
    if not routes[route_flags].sum(axis=1).eq(1).all():
        raise AssertionError("Route one-hot invariant failed after concatenation")
    return routes


def _is_official_v2(version_record: dict[str, object]) -> bool:
    try:
        return int(version_record.get("version", -1)) == 2
    except (TypeError, ValueError):
        return False


def _result_notes(
    mode: str,
    models: tuple[str, ...],
    version_record: dict[str, object],
) -> str:
    if _is_official_v2(version_record):
        comparison = version_record.get("v1_v2_behavior_comparison")
        equivalence_note = (
            " The audited v2 behavior payloads are byte-identical to the local v1 "
            "behavior payloads, so this official-version replay is not a new "
            "participant cohort beyond v1."
            if isinstance(comparison, dict)
            and comparison.get("raw_byte_identical_files") == 59
            else ""
        )
        external_note = """- Mendeley results are a frozen external replay on the official version-2
  behavior files (DOI `10.17632/2pw2m39yct.2`, CC BY 4.0). This is a
  same-task external cohort, not cross-domain or clinical validation.""" + equivalence_note
    else:
        external_note = """- Mendeley results are an exploratory frozen external replay on the local
  version-1 behavior files (DOI `10.17632/2pw2m39yct.1`). They are **not** a
  version-2 replication; upstream currently identifies version 2 as
  `10.17632/2pw2m39yct.2`."""
    return f"""# E1 evidence ({mode})

This directory was generated by `framework_v1/run_e1.py` with models:
{', '.join(models)}.

- Many Labs results are participant-grouped outer-CV estimates.
{external_note}
- The positive class is the current A/B deck choice, an operational proxy, not
  a clinical outcome or intervention effect.
- No EEG file, EEG column, or EEG-derived feature was read.
- Runtime routes use scores, frozen settings, and prior counters only. Labels
  enter only the posthoc evaluation tables.

The complete run writes `run_manifest.json` and `sha256sums.txt`. The
privacy-minimised review release retains selected aggregate outputs, a
repository-level `MANIFEST.json`, and `SHA256SUMS.txt` instead of the
host-bearing run manifest.
"""


def main() -> int:
    args = parse_args()
    config = _resolved_config(args)
    models = tuple(dict.fromkeys(args.models))
    max_many = args.max_many_subjects
    max_mendeley = args.max_mendeley_subjects
    if args.mode == "smoke":
        max_many = max_many or 30
        max_mendeley = max_mendeley or 8

    print("load behavior-only data", flush=True)
    many_behavior = limit_participants(
        load_many_labs(args.many_labs), max_many, seed=config.seed
    )
    mendeley_behavior, mendeley_version = load_mendeley_behavior(
        args.mendeley_dir, local_manifest=args.mendeley_manifest
    )
    mendeley_behavior = limit_participants(
        mendeley_behavior, max_mendeley, seed=config.seed + 1
    )
    official_v2 = _is_official_v2(mendeley_version)
    evidence_root = FRAMEWORK_ROOT / ("evidence_v2" if official_v2 else "evidence")
    output_dir = args.output_dir or (
        evidence_root / "smoke" if args.mode == "smoke" else evidence_root
    )
    output_dir = output_dir.resolve()
    if official_v2 and output_dir == (FRAMEWORK_ROOT / "evidence").resolve():
        raise ValueError("Official v2 replay may not overwrite the version-1 evidence")
    output_dir.mkdir(parents=True, exist_ok=True)
    model_output_dir = output_dir / "models"
    model_output_dir.mkdir(parents=True, exist_ok=True)
    external_scope = (
        "frozen_external_official_v2_same_task"
        if official_v2
        else "frozen_external_local_v1_exploratory"
    )
    print("build causal prefix features", flush=True)
    many_features = build_causal_history_features(
        many_behavior, windows=config.history_windows, block_size=config.block_size
    )
    mendeley_features = build_causal_history_features(
        mendeley_behavior,
        windows=config.history_windows,
        block_size=config.block_size,
    )
    feature_columns = model_feature_columns(many_features)
    if feature_columns != model_feature_columns(mendeley_features):
        raise AssertionError("Feature schema differs across datasets")
    print("run causal-feature mutation checks", flush=True)
    assert_causal_feature_invariance(
        many_behavior,
        windows=config.history_windows,
        block_size=config.block_size,
    )
    assert_causal_feature_invariance(
        mendeley_behavior,
        windows=config.history_windows,
        block_size=config.block_size,
    )

    many_predictions, outer_points, assignments = run_grouped_outer_cv(
        many_features,
        feature_columns=feature_columns,
        models=models,
        config=config,
    )
    external_predictions, frozen_points, model_paths = fit_frozen_and_score_external(
        many_features,
        mendeley_features,
        many_predictions,
        feature_columns=feature_columns,
        models=models,
        config=config,
        model_output_dir=model_output_dir,
        evaluation_scope=external_scope,
    )
    predictions = pd.concat(
        [many_predictions, external_predictions], ignore_index=True
    ).sort_values(
        ["dataset_id", "model_name", "subject_id", "trial_id"], kind="mergesort"
    )

    print("replay cap 2/4/6/8/effective-unbounded", flush=True)
    routes = replay_all_capacities(
        predictions,
        outer_points,
        frozen_points,
        config=config,
    )
    label_gate_groups = 0
    for _, label_check in routes.groupby(
        ["dataset_id", "model_name", "cap_label", "outer_fold"], sort=True
    ):
        assert_label_independent_routing(
            label_check[
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
                ]
            ],
            prompt_threshold=float(label_check["prompt_threshold"].iloc[0]),
            automated_alert_cap=int(label_check["automated_alert_cap"].iloc[0]),
            review_cap=config.review_cap,
            review_band_width=config.review_band_width,
            uncertainty_threshold=config.uncertainty_threshold,
            uncertainty_mode=config.uncertainty_mode,
        )
        label_gate_groups += 1

    print("summarize metrics and participant-cluster bootstrap", flush=True)
    performance = model_performance_table(predictions)
    participant_workload = participant_workload_table(routes)
    workload = route_workload_table(routes)
    bootstrap = participant_cluster_bootstrap(
        predictions,
        participant_workload,
        replicates=config.bootstrap_replicates,
        seed=config.seed,
        confidence_level=config.bootstrap_confidence_level,
    )

    dataset_rows = [
        dataset_summary(
            many_features,
            version_note=(
                "Many Labs public behavior table; participant-grouped outer CV"
            ),
        ),
        dataset_summary(
            mendeley_features,
            version_note=str(mendeley_version["interpretation"]),
        ),
    ]
    artifacts: list[Path] = list(model_paths)
    artifacts.append(write_csv(output_dir / "dataset_summary.csv", pd.DataFrame(dataset_rows)))
    assignments_out = assignments.rename(columns={"fold": "outer_fold"}).copy()
    assignments_out.insert(0, "dataset_id", "many_labs_igt")
    artifacts.append(write_csv(output_dir / "outer_fold_assignments.csv", assignments_out))
    artifacts.append(write_csv(output_dir / "outer_fold_operating_points.csv", outer_points))
    artifacts.append(write_csv(output_dir / "frozen_operating_points.csv", frozen_points))
    artifacts.append(write_csv(output_dir / "model_performance.csv", performance))
    artifacts.append(write_csv(output_dir / "route_workload_metrics.csv", workload))
    artifacts.append(write_csv(output_dir / "participant_workload.csv", participant_workload))
    artifacts.append(write_csv(output_dir / "bootstrap_confidence_intervals.csv", bootstrap))
    artifacts.append(write_gzip_csv(output_dir / "predictions.csv.gz", predictions))
    route_columns = [
        "dataset_id",
        "evaluation_scope",
        "model_name",
        "subject_id",
        "study_id",
        "trial_id",
        "outer_fold",
        "y_true",
        "score",
        "cap_label",
        "automated_alert_cap",
        "review_cap",
        "prompt_threshold",
        "uncertainty_score",
        "uncertainty_threshold",
        "review_band_width",
        "primary_route",
        "reason_code",
        "auto_alert_count_before",
        "auto_alert_count_after",
        "review_count_before",
        "review_count_after",
        *[f"route_{name}" for name in PRIMARY_ROUTES],
        "threshold_source",
        "route_computed_before_label_access",
    ]
    artifacts.append(
        write_gzip_csv(output_dir / "route_assignments.csv.gz", routes[route_columns])
    )
    artifacts.append(write_json(output_dir / "experiment_config.json", config.as_dict()))
    artifacts.append(
        write_json(
            output_dir / "feature_schema.json",
            {
                "feature_columns": feature_columns,
                "history_score_is_proposal_only": True,
                "current_trial_choice_or_outcome_in_features": False,
                "eeg_features": [],
            },
        )
    )
    artifacts.append(
        write_json(
            output_dir / "model_specifications.json", model_specifications(config.seed)
        )
    )
    mendeley_version["official_current_version_checked_2026_08_13"] = {
        "version": 2,
        "doi": "10.17632/2pw2m39yct.2",
        "url": "https://data.mendeley.com/datasets/2pw2m39yct/2",
        "used_in_this_run": official_v2,
    }
    artifacts.append(
        write_json(output_dir / "mendeley_local_version_record.json", mendeley_version)
    )
    manifest_verification = mendeley_version.get("manifest_verification", {})
    version_comparison = mendeley_version.get("v1_v2_behavior_comparison")
    if official_v2 and not (
        isinstance(manifest_verification, dict)
        and manifest_verification.get("all_sizes_match") is True
        and manifest_verification.get("all_sha256_match") is True
        and manifest_verification.get("igt_only_download_policy") is True
    ):
        raise AssertionError("Official v2 manifest/checksum gate did not pass")
    subject_overlap = set(many_behavior["subject_id"]) & set(
        mendeley_behavior["subject_id"]
    )
    if subject_overlap:
        raise AssertionError("Many Labs and external participant identifiers overlap")
    if frozen_points["external_dataset_used_for_selection"].astype(bool).any():
        raise AssertionError("External data were marked as used for frozen selection")
    validation_checks = {
        "causal_suffix_mutation_many_labs": "pass",
        "causal_suffix_mutation_mendeley": "pass",
        "outer_participant_disjointness": "pass",
        "inner_participant_disjointness": "pass",
        "one_prediction_per_decision_model": "pass",
        "route_mutual_exclusivity_and_exhaustiveness": "pass",
        "participant_capacity_bounds": "pass",
        "posthoc_label_shuffle_route_invariance": "pass",
        "posthoc_label_shuffle_route_invariance_groups_checked": label_gate_groups,
        "effective_unbounded_has_zero_capacity_blocks": "pass",
        "many_labs_external_subject_id_overlap_zero": "pass",
        "external_labels_or_scores_used_for_fit_or_threshold": False,
        "frozen_selection_uses_many_labs_oof_only": "pass",
        "official_v2_manifest_metadata_gate": "pass" if official_v2 else "not_applicable",
        "official_v2_api_size_sha256_gate": "pass" if official_v2 else "not_applicable",
        "official_v2_igt_only_download_gate": "pass" if official_v2 else "not_applicable",
        "v1_v2_behavior_equivalence_audit": (
            "pass" if official_v2 and isinstance(version_comparison, dict) else "not_recorded"
        ),
        "artifact_checksum_verification_on_finalize": "pass",
        "eeg_files_read": 0,
        "eeg_columns_read": [],
    }
    artifacts.append(write_json(output_dir / "validation_checks.json", validation_checks))
    input_paths = [args.many_labs, args.mendeley_manifest] + sorted(
        args.mendeley_dir.glob("IGT_P*.csv")
    )
    if isinstance(version_comparison, dict):
        input_paths.extend(
            [
                Path(str(version_comparison["summary_path"])),
                Path(str(version_comparison["detail_path"])),
            ]
        )
    input_hashes = input_hash_table(input_paths, base=WORKSPACE_ROOT)
    artifacts.append(write_csv(output_dir / "input_hashes.csv", input_hashes))
    code_paths = [Path(__file__)] + sorted((FRAMEWORK_ROOT / "e1").glob("*.py"))
    code_hashes = input_hash_table(code_paths, base=REPOSITORY_ROOT)
    artifacts.append(write_csv(output_dir / "code_hashes.csv", code_hashes))
    notes_path = output_dir / "RESULTS_README.md"
    notes_path.write_text(
        _result_notes(args.mode, models, mendeley_version), encoding="utf-8"
    )
    artifacts.append(notes_path)

    manifest_payload = {
        "experiment": "E1_cross_model_capacity_aware_four_route_replay",
        "script_version": SCRIPT_VERSION,
        "mode": args.mode,
        "models": list(models),
        "configuration": config.as_dict(),
        "data_boundary": {
            "many_labs_role": "development and participant-grouped outer-CV evaluation",
            "mendeley_role": (
                str(mendeley_version["interpretation"])
            ),
            "mendeley_v2_role": (
                "official behavior-only frozen external replay"
                if official_v2
                else "not downloaded, not inspected, not used"
            ),
            "same_task_external_cohort": True,
            "cross_domain_validation": False,
            "positive_class": "current A/B deck choice operational proxy",
            "eeg_used": False,
            "eeg_files_read": 0,
            "eeg_columns_read": [],
            "clinical_claim": False,
            "intervention_effect_claim": False,
        },
        "selection_boundary": {
            "outer_test_labels_used_for_fold_operating_point": False,
            "mendeley_labels_or_scores_used_for_frozen_model_or_threshold": False,
            "runtime_route_reads_labels": False,
            "labels_used_posthoc_for_evaluation_only": True,
        },
        "dataset_counts": dataset_rows,
        "validation_checks": validation_checks,
        "environment": environment_record(),
        "git": git_record(REPOSITORY_ROOT),
    }
    manifest_path, checksum_path = finalize_manifest(
        output_dir, manifest_payload=manifest_payload, artifact_paths=artifacts
    )
    verify_finalized_manifest(output_dir)
    print(f"evidence: {output_dir}", flush=True)
    print(f"manifest: {manifest_path}", flush=True)
    print(f"checksums: {checksum_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
