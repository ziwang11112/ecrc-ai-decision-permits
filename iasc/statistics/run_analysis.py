"""Portable, frozen-count participant-equal alert-policy sensitivity.

Read PROTOCOL.md. No model, threshold, route, or original result is changed.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SEED, REPS = 20260912, 2000
COHORTS = {"many_labs_igt": "Development", "mendeley_igt_official_v2": "External"}
MODELS = ("hist_gradient_boosting", "history_baseline", "regularised_logistic")
BASES = ("eight_per_episode", "eight_per_100_planned")
GROUP = ["analysis", "dataset_id", "model_name", "capacity_basis"]
METRICS = ("alert_precision", "alert_coverage")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ratio(numerator, denominator):
    a, b = np.broadcast_arrays(np.asarray(numerator, float), np.asarray(denominator, float))
    return np.divide(a, b, out=np.full(a.shape, np.nan), where=b > 0)


def json_write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def csv_write(path, frame):
    text = frame.to_csv(index=False, float_format="%.17g", lineterminator="\n")
    if path.name.endswith(".gz"):
        path.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    else:
        path.write_text(text, encoding="utf-8")


def ci(values):
    values = np.asarray(values, float)
    finite = values[np.isfinite(values)]
    limits = np.quantile(finite, [.025, .975]) if len(finite) else [np.nan, np.nan]
    return {"ci_low": float(limits[0]), "ci_high": float(limits[1]), "finite_replicates": int(len(finite))}


def with_prefix(prefix, values):
    return {prefix + "_" + k: v for k, v in values.items()}


def calculate(t, d, weights):
    valid = d > 0
    rates = ratio(t, d)
    pooled_draws = ratio(weights @ t, weights @ d)
    macro_draws = ratio(weights @ np.nan_to_num(rates), weights @ valid.astype(float))
    return {"pooled": float(ratio(t.sum(), d.sum())),
            "macro": float(ratio(np.nansum(rates), valid.sum())),
            "n_valid": int(valid.sum()), "valid": valid, "rates": rates,
            "pooled_draws": pooled_draws, "macro_draws": macro_draws}


def common_calculate(reference, comparison, weights):
    common = reference["valid"] & comparison["valid"]
    values_r = np.where(common, reference["rates"], 0.0)
    values_c = np.where(common, comparison["rates"], 0.0)
    n = int(common.sum())
    den = weights @ common.astype(float)
    mean_r = float(ratio(values_r.sum(), n))
    mean_c = float(ratio(values_c.sum(), n))
    return {"n_common_valid": n,
            "n_reference_only": int((reference["valid"] & ~comparison["valid"]).sum()),
            "n_comparison_only": int((comparison["valid"] & ~reference["valid"]).sum()),
            "n_neither_valid": int((~reference["valid"] & ~comparison["valid"]).sum()),
            "reference_mean": mean_r, "comparison_mean": mean_c,
            "difference": float(ratio((values_c - values_r).sum(), n)),
            "reference_draws": ratio(weights @ values_r, den),
            "comparison_draws": ratio(weights @ values_c, den),
            "difference_draws": ratio(weights @ (values_c - values_r), den),
            "eligible_multiplicity": den}


def fixture_checks():
    # Includes zero positives, zero alerts, different arm-specific populations,
    # a nonempty common precision population, and a replicate with none eligible.
    p = np.array([0, 2, 4, 3], float)
    ar, tr = np.array([0, 2, 4, 0], float), np.array([0, 1, 3, 0], float)
    ac, tc = np.array([1, 0, 2, 0], float), np.array([0, 0, 1, 0], float)
    weights = np.array([[1, 1, 1, 1], [0, 2, 1, 0], [0, 0, 0, 4]], float)
    r, c = calculate(tr, ar, weights), calculate(tc, ac, weights)
    common = common_calculate(r, c, weights)
    assert np.isclose(r["macro"], .625) and np.isclose(c["macro"], .25)
    assert np.isclose(c["macro"] - r["macro"], -.375)
    assert common["n_common_valid"] == 1 and np.isclose(common["difference"], -.25)
    assert np.isnan(common["difference_draws"][-1])
    rr, cc = calculate(tr, p, weights), calculate(tc, p, weights)
    assert np.isclose(rr["macro"], 5/12) and np.isclose(cc["macro"], 1/12)
    count = 0
    for t, d in ((tr, ar), (tc, ac), (tr, p), (tc, p)):
        result = calculate(t, d, weights)
        for j, mult in enumerate(weights.astype(int)):
            indices = np.repeat(np.arange(4), mult)
            valid = d[indices] > 0
            explicit = np.mean(t[indices][valid] / d[indices][valid]) if valid.any() else np.nan
            assert np.allclose(result["macro_draws"][j], explicit, equal_nan=True)
            assert np.allclose(result["pooled_draws"][j], ratio(t[indices].sum(), d[indices].sum()), equal_nan=True)
            count += 1
    return {"hand_computable_zero_denominator_fixture_pass": True, "explicit_duplication_checks": count,
            "arm_specific_and_common_population_differences_distinguished": True}


def inputs_and_counts(folder):
    recorded = json.loads((folder / "INPUT_MANIFEST.json").read_text())
    for row in recorded["inputs"]:
        assert sha(folder / row["name"]) == row["sha256"], row["name"]
    online = pd.read_csv(folder / "online_participant_statistics.csv.gz")
    sequence = pd.read_csv(folder / "frozen_participant_statistics.csv.gz")
    required = ["dataset_id", "model_name", "subject_id", "study_id", "capacity_basis", "allocator",
                "planned_horizon", "n_decisions", "n_positive", "n_alert", "n_alert_positive"]
    harmonized = online[required].rename(columns={"n_alert_positive": "n_true_alert"}).copy()
    harmonized.insert(0, "analysis", "online")
    fixed = harmonized[(harmonized.capacity_basis == "eight_per_episode") & (harmonized.allocator == "fifo")].copy()
    fixed["analysis"] = "capacity_removal"
    fixed["capacity_basis"] = "separate_8_2_vs_unbounded"
    fixed["allocator"] = "fixed_8_2"
    keys = ["dataset_id", "model_name", "subject_id"]
    full = sequence[sequence.region == "full_episode"][keys + ["n_subset", "n_positive"]]
    cand = sequence[sequence.region == "alert_candidates"][keys + ["n_subset", "n_positive"]]
    assert not full.duplicated(keys).any() and not cand.duplicated(keys).any()
    for k, f in online.groupby(keys, sort=True):
        assert f.n_decisions.nunique() == f.n_positive.nunique() == 1
    merged = fixed.merge(full, on=keys, validate="one_to_one", suffixes=("", "_full"))
    assert len(merged) == len(fixed)
    assert (merged.n_decisions == merged.n_subset).all() and (merged.n_positive == merged.n_positive_full).all()
    removed = fixed.merge(cand.rename(columns={"n_subset": "uncapped_alert", "n_positive": "uncapped_true_alert"}), on=keys, validate="one_to_one")
    assert len(removed) == len(fixed) and removed.uncapped_alert.notna().all()
    # Existing S3 candidate counts and S4 candidate sufficient statistics agree.
    ref_cand = online[(online.capacity_basis == "eight_per_episode") & (online.allocator == "fifo")][keys + ["n_candidate", "n_candidate_positive"]]
    cross = removed.merge(ref_cand, on=keys, validate="one_to_one")
    assert (cross.uncapped_alert == cross.n_candidate).all()
    assert (cross.uncapped_true_alert == cross.n_candidate_positive).all()
    assert (removed.uncapped_alert >= removed.n_alert).all()
    removed["n_alert"] = removed.pop("uncapped_alert")
    removed["n_true_alert"] = removed.pop("uncapped_true_alert")
    removed["allocator"] = "capacity_removed"
    counts = pd.concat([harmonized, fixed, removed], ignore_index=True)
    assert not counts.duplicated(GROUP + ["allocator", "subject_id"]).any()
    for col in ["n_decisions", "n_positive", "n_alert", "n_true_alert"]:
        assert np.isfinite(counts[col]).all() and (counts[col] >= 0).all()
        assert (counts[col] == counts[col].astype(int)).all()
        counts[col] = counts[col].astype(int)
    assert (counts.n_true_alert <= counts.n_alert).all() and (counts.n_alert <= counts.n_decisions).all()
    assert (counts.n_true_alert <= counts.n_positive).all() and (counts.n_positive <= counts.n_decisions).all()
    assert set(counts.dataset_id) == set(COHORTS) and set(counts.model_name) == set(MODELS)
    return counts.sort_values(GROUP + ["allocator", "subject_id"]).reset_index(drop=True), recorded


def check_archived(counts, folder):
    s3 = pd.read_csv(folder / "online_estimates.csv")
    a4 = pd.read_csv(folder / "a4_permission_grid.csv")
    rows = []
    for values, group in counts.groupby(GROUP + ["allocator"], sort=True):
        meta = dict(zip(GROUP + ["allocator"], values))
        if meta["analysis"] == "online":
            reference = s3[(s3.dataset_id == meta["dataset_id"]) & (s3.model_name == meta["model_name"]) &
                           (s3.capacity_basis == meta["capacity_basis"]) & (s3.allocator == meta["allocator"])]
        else:
            arm = "separate_capacity_8_2" if meta["allocator"] == "fixed_8_2" else "capacity_off"
            reference = a4[(a4.dataset_id == meta["dataset_id"]) & (a4.model_name == meta["model_name"]) & (a4.arm == arm)]
        assert len(reference) == 1
        reference = reference.iloc[0]
        expected = {"n_decisions": group.n_decisions.sum(), "n_alert": group.n_alert.sum(),
                    "alert_precision": ratio(group.n_true_alert.sum(), group.n_alert.sum()),
                    "alert_coverage": ratio(group.n_true_alert.sum(), group.n_positive.sum()),
                    "false_alerts_per_100": 100 * ratio(group.n_alert.sum() - group.n_true_alert.sum(), group.n_decisions.sum())}
        gaps = {key: abs(float(value) - float(reference[key])) for key, value in expected.items()}
        assert max(gaps.values()) < 1e-12, (meta, gaps)
        rows.append(meta | {"max_absolute_gap": max(gaps.values()), "reference": "S3" if meta["analysis"] == "online" else "A4"})
    assert len(rows) == 36
    return pd.DataFrame(rows)


def main(out):
    assert not out.exists(), "Use a fresh directory; retain previous runs"
    folder = HERE / "input"
    tracked = list(folder.iterdir()) + [Path(__file__).resolve(), HERE / "PROTOCOL.md"]
    before = {str(p.relative_to(HERE)).replace("\\", "/"): sha(p) for p in tracked if p.is_file()}
    counts, source_manifest = inputs_and_counts(folder)
    archived = check_archived(counts, folder)
    checks = fixture_checks()
    out.mkdir(parents=True)
    csv_write(out / "harmonized_participant_counts.csv.gz", counts)
    csv_write(out / "archived_pooled_reproduction.csv", archived)
    weights_by_cohort, ids_by_cohort, orders = {}, {}, []
    for dataset in sorted(COHORTS):
        ids = sorted(counts.loc[counts.dataset_id == dataset, "subject_id"].unique())
        expected_n = 617 if dataset == "many_labs_igt" else 59
        assert len(ids) == expected_n
        ids_by_cohort[dataset] = ids
        rng = np.random.default_rng(SEED)
        weights = rng.multinomial(len(ids), np.full(len(ids), 1/len(ids)), size=REPS)
        weights_by_cohort[dataset] = weights
        matrix = pd.DataFrame(weights, columns=ids)
        matrix.insert(0, "replicate", range(REPS))
        csv_write(out / ("bootstrap_multiplicities_" + COHORTS[dataset].lower() + ".csv.gz"), matrix)
        orders.extend({"dataset_id": dataset, "position": j, "subject_id": sid} for j, sid in enumerate(ids))
    csv_write(out / "participant_order.csv", pd.DataFrame(orders))

    estimates, contrasts, arm_draws, contrast_draws = [], [], [], []
    for values, group in counts.groupby(GROUP, sort=True):
        meta = dict(zip(GROUP, values)) | {"cohort": COHORTS[values[1]]}
        ref_arm, cmp_arm = ("fifo", "paced") if meta["analysis"] == "online" else ("fixed_8_2", "capacity_removed")
        assert set(group.allocator) == {ref_arm, cmp_arm}
        ids = ids_by_cohort[meta["dataset_id"]]
        weights = weights_by_cohort[meta["dataset_id"]]
        data = {}
        for arm in [ref_arm, cmp_arm]:
            frame = group[group.allocator == arm].sort_values("subject_id")
            assert frame.subject_id.tolist() == ids
            data[arm] = frame
        assert np.array_equal(data[ref_arm][["n_decisions", "n_positive"]].to_numpy(), data[cmp_arm][["n_decisions", "n_positive"]].to_numpy())
        for metric in METRICS:
            results = {}
            for arm in [ref_arm, cmp_arm]:
                frame = data[arm]
                t = frame.n_true_alert.to_numpy(float)
                d = frame.n_alert.to_numpy(float) if metric == "alert_precision" else frame.n_positive.to_numpy(float)
                result = calculate(t, d, weights)
                results[arm] = result
                row = meta | {"allocator": arm, "metric": metric, "n_participants": len(ids),
                              "n_valid": result["n_valid"], "n_zero_denominator": len(ids)-result["n_valid"],
                              "n_zero_alert": int((frame.n_alert == 0).sum()), "n_zero_positive": int((frame.n_positive == 0).sum()),
                              "n_decisions": int(frame.n_decisions.sum()), "n_positive": int(frame.n_positive.sum()),
                              "n_alert": int(frame.n_alert.sum()), "n_true_alert": int(frame.n_true_alert.sum()),
                              "pooled_estimate": result["pooled"], "macro_estimate": result["macro"]}
                row.update(with_prefix("pooled", ci(result["pooled_draws"])))
                row.update(with_prefix("macro", ci(result["macro_draws"])))
                estimates.append(row)
                arm_draws.append(pd.DataFrame(meta | {"allocator": arm, "metric": metric, "replicate": np.arange(REPS),
                                                      "pooled": result["pooled_draws"], "macro": result["macro_draws"],
                                                      "eligible_multiplicity": weights @ result["valid"].astype(float)}))
            r, c = results[ref_arm], results[cmp_arm]
            common = common_calculate(r, c, weights)
            row = meta | {"reference": ref_arm, "comparison": cmp_arm, "metric": metric,
                          "n_participants": len(ids), "n_valid_reference": r["n_valid"], "n_valid_comparison": c["n_valid"]}
            row.update({key: common[key] for key in ("n_common_valid", "n_reference_only", "n_comparison_only", "n_neither_valid")})
            row.update({"pooled_reference": r["pooled"], "pooled_comparison": c["pooled"], "pooled_difference": c["pooled"]-r["pooled"],
                        "macro_reference": r["macro"], "macro_comparison": c["macro"], "arm_macro_difference": c["macro"]-r["macro"],
                        "common_reference": common["reference_mean"], "common_comparison": common["comparison_mean"],
                        "common_macro_difference": common["difference"]})
            arrays = {"pooled_difference": c["pooled_draws"]-r["pooled_draws"],
                      "arm_macro_difference": c["macro_draws"]-r["macro_draws"],
                      "common_macro_difference": common["difference_draws"],
                      "common_reference": common["reference_draws"], "common_comparison": common["comparison_draws"]}
            for key, array in arrays.items():
                row.update(with_prefix(key, ci(array)))
            contrasts.append(row)
            contrast_draws.append(pd.DataFrame(meta | {"reference": ref_arm, "comparison": cmp_arm, "metric": metric,
                                                       "replicate": np.arange(REPS), **arrays,
                                                       "common_eligible_multiplicity": common["eligible_multiplicity"]}))
    points, changes = pd.DataFrame(estimates), pd.DataFrame(contrasts)
    assert len(points) == 72 and len(changes) == 36
    assert len(points[points.analysis == "online"]) == 48 and len(changes[changes.analysis == "online"]) == 24
    csv_write(out / "arm_estimates.csv", points)
    csv_write(out / "paired_comparisons.csv", changes)
    csv_write(out / "bootstrap_arm_draws.csv.gz", pd.concat(arm_draws, ignore_index=True))
    csv_write(out / "bootstrap_contrast_draws.csv.gz", pd.concat(contrast_draws, ignore_index=True))
    checks.update({"all_planned_arm_cells": 36, "all_planned_comparisons": 18, "metrics_per_cell": 2,
                   "harmonized_participant_rows": len(counts), "archived_pooled_cells_reproduced": len(archived),
                   "max_archived_pooled_gap": float(archived.max_absolute_gap.max()),
                   "all_common_and_arm_inventories_aligned": True,
                   "all_counts_integer_and_consistent": True,
                   "finite_bootstrap_arm_estimates_min": int(points[["pooled_finite_replicates", "macro_finite_replicates"]].min().min()),
                   "finite_bootstrap_contrasts_min": int(changes[["pooled_difference_finite_replicates", "arm_macro_difference_finite_replicates", "common_macro_difference_finite_replicates"]].min().min())})
    after = {name: sha(HERE / name) for name in before}
    assert before == after
    checks["all_input_hashes_unchanged"] = True
    json_write(out / "validation.json", checks)
    manifest = {"protocol": "post hoc participant-equal alert-policy sensitivity, locked 2026-09-12",
                "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                "seed": SEED, "replicates": REPS, "models_refitted": False, "thresholds_reselected": False,
                "new_routes_computed": False, "original_inputs_modified": False,
                "inputs": before, "source_inputs": source_manifest["inputs"],
                "outputs": {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}}
    json_write(out / "manifest.json", manifest)
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "out")
    args = parser.parse_args()
    main(args.out.resolve())
