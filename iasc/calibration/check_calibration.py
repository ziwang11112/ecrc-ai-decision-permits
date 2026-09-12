"""Read-only calibration audit; reconstruct only score sets actually archived.

No model fitting, threshold change, or write to an original artifact occurs.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import platform
import sys

sys.dont_write_bytecode = True
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE
SOURCE = HERE / "input/source"
EVIDENCE = HERE / "input/evidence"
sys.path.insert(0, str(SOURCE))
from e1.config import E1Config
from e1.routing import route_frame, policy_metrics, threshold_grid


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def choose(rows, require_false_limit=True):
    eligible = [r for r in rows if r["n_action_routes"] > 0 and np.isfinite(r["action_precision"])
                and r["action_precision"] >= .60 and
                (not require_false_limit or r["false_actions_per_100"] <= 9)]
    assert eligible, "This audit only compares recorded feasible selections"
    return max(eligible, key=lambda r: (r["event_coverage_by_action"], r["action_precision"],
                                      -r["false_actions_per_100"], -r["action_route_rate"], r["prompt_threshold"]))


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    files = [EVIDENCE / name for name in ("predictions.csv.gz", "outer_fold_assignments.csv",
              "outer_fold_operating_points.csv", "frozen_operating_points.csv", "experiment_config.json")]
    files += [SOURCE / "e1/routing.py", SOURCE / "e1/config.py", SOURCE / "e1/models.py", SOURCE / "e1/__init__.py", HERE / "input/SOURCE_MANIFEST.json", HERE / "input/ENTRYPOINT_PROVENANCE.json", Path(__file__)]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in files}
    source_manifest = json.loads((HERE / "input/SOURCE_MANIFEST.json").read_text())
    for entry in source_manifest["files"]:
        assert sha(HERE / entry["path"]) == entry["sha256"]
    config_values = json.loads((EVIDENCE / "experiment_config.json").read_text())
    assert config_values["reference_alert_cap"] == 8 and config_values["review_cap"] == 2
    assert config_values["action_precision_floor"] == .60 and config_values["false_action_limit_per_100"] == 9
    cfg = E1Config()
    preds = pd.read_csv(EVIDENCE / "predictions.csv.gz")
    preds = preds[preds.dataset_id == "many_labs_igt"].copy()
    folds = pd.read_csv(EVIDENCE / "outer_fold_assignments.csv")
    old_outer = pd.read_csv(EVIDENCE / "outer_fold_operating_points.csv")
    old_global = pd.read_csv(EVIDENCE / "frozen_operating_points.csv")
    reference = preds[preds.model_name == "history_baseline"].copy()
    lengths = reference.groupby("subject_id").size()
    assert len(lengths) == 617 and lengths.sum() == 66525 and lengths.min() == 95
    for model, frame in preds.groupby("model_name"):
        assert frame.groupby("subject_id").size().equals(lengths)
        assert not frame.duplicated(["subject_id", "trial_id"]).any()
    selected_rows = []
    for row in old_outer.to_dict("records"):
        ids = set(folds.loc[folds.outer_fold != row["outer_fold"], "subject_id"])
        m, n = len(ids), int(lengths.loc[sorted(ids)].sum())
        assert m == row["n_training_participants"] == row["n_calibration_participants"]
        assert n == row["n_calibration_decisions"] == row["n_decisions"]
        assert row["n_action_routes"] == row["n_alert"] + row["n_human_review"] <= 10*m
        assert row["n_false_action_routes"] == row["n_action_routes"] - row["n_true_action_routes"]
        assert abs(row["n_true_action_routes"] / row["n_action_routes"] - row["action_precision"]) < 1e-14
        assert abs(100*row["n_false_action_routes"] / n - row["false_actions_per_100"]) < 1e-14
        assert row["selection_constraints_satisfied"] and row["action_precision"] >= .60
        selected_rows.append({k: row[k] for k in ("model_name", "outer_fold", "prompt_threshold", "action_precision", "false_actions_per_100")} |
                             {"n_calibration_participants": m, "n_calibration_decisions": n,
                              "min_episode_length": int(lengths.loc[sorted(ids)].min()),
                              "precision_margin": row["action_precision"]-.60,
                              "false_limit_slack": 9-row["false_actions_per_100"],
                              "max_false_per_100_implied_by_precision_and_capacity": 400*m/n})
    pd.DataFrame(selected_rows).to_csv(out / "calibration_selected_audit.csv", index=False)

    grid_rows, summaries = [], []
    sets = [("global_development_oof", model, -1, group.copy()) for model, group in preds.groupby("model_name", sort=True)]
    # History requires no fitted model: its score is identical in any inner fold.
    for fold in sorted(folds.outer_fold.unique()):
        ids = set(folds.loc[folds.outer_fold != fold, "subject_id"])
        sets.append(("outer_training_history_exact", "history_baseline", int(fold), reference[reference.subject_id.isin(ids)].copy()))
    for scope, model, fold, frame in sets:
        rows = []
        for threshold in threshold_grid(cfg):
            routed = route_frame(frame[["subject_id", "trial_id", "y_true", "score"]],
                                 prompt_threshold=float(threshold), automated_alert_cap=8, review_cap=2,
                                 review_band_width=.03, uncertainty_threshold=.90, uncertainty_mode="probability_margin")
            row = {"scope": scope, "model_name": model, "outer_fold": fold, "prompt_threshold": float(threshold), **policy_metrics(routed)}
            rows.append(row)
        best = choose(rows)
        without = choose(rows, False)
        original = old_global[old_global.model_name == model].iloc[0] if fold == -1 else old_outer[(old_outer.model_name == model) & (old_outer.outer_fold == fold)].iloc[0]
        assert best["prompt_threshold"] == float(original.prompt_threshold) == without["prompt_threshold"]
        if fold != -1:
            for key in ("n_decisions", "n_action_routes", "n_true_action_routes", "n_false_action_routes", "action_precision", "false_actions_per_100"):
                assert abs(best[key] - float(original[key])) < 1e-12
        summary = {"scope": scope, "model_name": model, "outer_fold": fold, "n_grid": len(rows),
                   "n_precision_eligible": sum(r["n_action_routes"] > 0 and r["action_precision"] >= .6 for r in rows),
                   "n_precision_eligible_but_false_limit_failing": sum(r["n_action_routes"] > 0 and r["action_precision"] >= .6 and r["false_actions_per_100"] > 9 for r in rows),
                   "n_false_limit_failing_any_grid": sum(r["false_actions_per_100"] > 9 for r in rows),
                   "max_false_per_100_any_grid": max(r["false_actions_per_100"] for r in rows),
                   "selected_threshold": best["prompt_threshold"], "threshold_without_false_filter": without["prompt_threshold"],
                   "matches_archived_threshold": True}
        summaries.append(summary)
        grid_rows.extend(rows)
        print(json.dumps(summary), flush=True)
    pd.DataFrame(grid_rows).to_csv(out / "calibration_reconstructed_grids.csv", index=False)
    pd.DataFrame(summaries).to_csv(out / "calibration_grid_summary.csv", index=False)
    assert all(sha(ROOT / name) == value for name, value in hashes.items())
    report = {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
              "inputs_unchanged": True, "input_hashes": hashes, "models_refitted": False,
              "n_subjects": len(lengths), "n_decisions": int(lengths.sum()),
              "episode_length_distribution": {str(k): int(v) for k, v in lengths.value_counts().sort_index().items()},
              "universal_bound_using_minimum_95": 400/95,
              "bound_using_actual_full_calibration_size": 400*617/66525,
              "all_15_selected_outer_rows_verified": True,
              "full_fitted_inner_calibration_predictions_available": False,
              "reconstructed_grids": summaries,
              "limitation": "Ten fitted-model outer-training calibration grids are not archived; global OOF scores cannot replace their inner OOF predictions."}
    report["original_audit_input_hashes"] = source_manifest["original_audit_input_hashes"]
    report["portable_input_manifest_sha256"] = sha(HERE / "input/SOURCE_MANIFEST.json")
    report["entrypoint_provenance"] = source_manifest["entrypoint"]
    report["entrypoint_required_or_executed"] = False
    for entry in source_manifest["files"]:
        assert sha(HERE / entry["path"]) == entry["sha256"]
    (out / "calibration_audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "out")
    args = parser.parse_args()
    main(args.out.resolve())
