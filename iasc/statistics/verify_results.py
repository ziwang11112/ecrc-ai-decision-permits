"""Independent arithmetic verification; does not import run_analysis.py.

Reconstructs every point and every bootstrap quantity from original copied
participant inputs, using eligibility-indexed arrays and rowwise reductions.
"""
from pathlib import Path
import argparse
import hashlib
import json

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
KEYS = ["analysis", "dataset_id", "model_name", "capacity_basis"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(out, repeat=None):
    points = pd.read_csv(out / "arm_estimates.csv")
    comparisons = pd.read_csv(out / "paired_comparisons.csv")
    arm_draws = pd.read_csv(out / "bootstrap_arm_draws.csv.gz")
    pair_draws = pd.read_csv(out / "bootstrap_contrast_draws.csv.gz")
    original = pd.read_csv(HERE / "input/online_participant_statistics.csv.gz")
    candidate = pd.read_csv(HERE / "input/frozen_participant_statistics.csv.gz")
    idx = ["dataset_id", "model_name", "subject_id"]
    candidate = candidate[candidate.region == "alert_candidates"].set_index(idx)
    reconstructed, bootstrap_checked, worst = {}, 0, 0.0
    weights_by_dataset = {}
    for dataset, cohort in (("many_labs_igt", "development"), ("mendeley_igt_official_v2", "external")):
        matrix = pd.read_csv(out / ("bootstrap_multiplicities_" + cohort + ".csv.gz"))
        assert matrix.replicate.tolist() == list(range(2000))
        ids = matrix.columns[1:].tolist()
        weights = matrix.iloc[:, 1:].to_numpy()
        assert (weights.sum(axis=1) == len(ids)).all()
        expected = np.random.default_rng(20260912).multinomial(len(ids), np.full(len(ids), 1/len(ids)), size=2000)
        assert np.array_equal(weights, expected)
        weights_by_dataset[dataset] = (ids, weights)

    def close(a, b):
        nonlocal worst
        a, b = np.asarray(a, float), np.asarray(b, float)
        assert np.array_equal(np.isnan(a), np.isnan(b)), (a, b)
        finite = np.isfinite(a) & np.isfinite(b)
        gap = float(np.max(np.abs(a[finite]-b[finite]))) if finite.any() else 0.0
        worst = max(worst, gap)
        assert gap < 1e-12, gap

    def quantiles(values):
        finite = values[np.isfinite(values)]
        return np.percentile(finite, [2.5, 97.5]) if len(finite) else np.array([np.nan, np.nan])

    for row in points.to_dict("records"):
        dataset, model = row["dataset_id"], row["model_name"]
        ids, weights = weights_by_dataset[dataset]
        budget = row["capacity_basis"] if row["analysis"] == "online" else "eight_per_episode"
        allocator = row["allocator"] if row["analysis"] == "online" else "fifo"
        f = original[(original.dataset_id == dataset) & (original.model_name == model) &
                     (original.capacity_basis == budget) & (original.allocator == allocator)].set_index("subject_id").loc[ids]
        alerts, tp, positive = f.n_alert.to_numpy(), f.n_alert_positive.to_numpy(), f.n_positive.to_numpy()
        if row["allocator"] == "capacity_removed":
            q = candidate.loc[[(dataset, model, sid) for sid in ids]]
            alerts, tp = q.n_subset.to_numpy(), q.n_positive.to_numpy()
        den = alerts if row["metric"] == "alert_precision" else positive
        valid = den > 0
        values = tp[valid] / den[valid]
        pool = tp.sum() / den.sum() if den.sum() else np.nan
        macro = values.mean() if valid.any() else np.nan
        close([row["pooled_estimate"], row["macro_estimate"]], [pool, macro])
        assert row["n_valid"] == valid.sum() and row["n_zero_denominator"] == (~valid).sum()
        assert row["n_zero_alert"] == (alerts == 0).sum() and row["n_zero_positive"] == (positive == 0).sum()
        boot_pool = np.sum(weights*tp, axis=1) / np.sum(weights*den, axis=1)
        boot_macro = np.sum(weights[:, valid]*values, axis=1) / np.sum(weights[:, valid], axis=1)
        close(quantiles(boot_pool), [row["pooled_ci_low"], row["pooled_ci_high"]])
        close(quantiles(boot_macro), [row["macro_ci_low"], row["macro_ci_high"]])
        subset = arm_draws
        for key in KEYS + ["allocator", "metric"]:
            subset = subset[subset[key] == row[key]]
        subset = subset.sort_values("replicate")
        assert len(subset) == 2000
        close(subset.pooled, boot_pool); close(subset.macro, boot_macro)
        key = tuple(row[k] for k in KEYS + ["allocator", "metric"])
        reconstructed[key] = dict(tp=tp, den=den, valid=valid, values=values, pooled=pool, macro=macro,
                                  pooled_draws=boot_pool, macro_draws=boot_macro)
        bootstrap_checked += 4

    for row in comparisons.to_dict("records"):
        base = tuple(row[k] for k in KEYS)
        r = reconstructed[base + (row["reference"], row["metric"])]
        c = reconstructed[base + (row["comparison"], row["metric"])]
        _, weights = weights_by_dataset[row["dataset_id"]]
        common = r["valid"] & c["valid"]
        rv, cv = r["tp"][common]/r["den"][common], c["tp"][common]/c["den"][common]
        assert row["n_common_valid"] == common.sum()
        assert row["n_reference_only"] == (r["valid"] & ~c["valid"]).sum()
        assert row["n_comparison_only"] == (c["valid"] & ~r["valid"]).sum()
        assert row["n_neither_valid"] == (~r["valid"] & ~c["valid"]).sum()
        close(row["pooled_difference"], c["pooled"]-r["pooled"])
        close(row["arm_macro_difference"], c["macro"]-r["macro"])
        close(row["common_macro_difference"], np.mean(cv-rv))
        boot_r = np.sum(weights[:, common]*rv, axis=1)/np.sum(weights[:, common], axis=1)
        boot_c = np.sum(weights[:, common]*cv, axis=1)/np.sum(weights[:, common], axis=1)
        arrays = {"pooled_difference": c["pooled_draws"]-r["pooled_draws"],
                  "arm_macro_difference": c["macro_draws"]-r["macro_draws"],
                  "common_macro_difference": np.sum(weights[:, common]*(cv-rv), axis=1)/np.sum(weights[:, common], axis=1),
                  "common_reference": boot_r, "common_comparison": boot_c}
        subset = pair_draws
        for key in KEYS + ["reference", "comparison", "metric"]:
            subset = subset[subset[key] == row[key]]
        subset = subset.sort_values("replicate")
        assert len(subset) == 2000
        for key, values in arrays.items():
            close(subset[key], values)
            close(quantiles(values), [row[key+"_ci_low"], row[key+"_ci_high"]])
            bootstrap_checked += 1
    assert len(points) == 72 and len(comparisons) == 36
    manifest = json.loads((out / "manifest.json").read_text())
    for name, expected in manifest["inputs"].items():
        assert sha(HERE / name) == expected
    for name, expected in manifest["outputs"].items():
        assert sha(out / name) == expected
    matches = None
    if repeat is not None:
        assert {p.name for p in out.iterdir()} == {p.name for p in repeat.iterdir()}
        matches = {p.name: sha(p) == sha(repeat/p.name) for p in sorted(out.iterdir())}
        assert all(matches.values())
    result = {"status": "passed", "original_count_inputs_independently_used": True,
              "analysis_implementation_imported": False, "arm_metric_points_checked": len(points),
              "paired_metric_comparisons_checked": len(comparisons), "bootstrap_vectors_checked": bootstrap_checked,
              "replicates_per_vector": 2000, "maximum_absolute_gap": worst,
              "all_manifest_inputs_outputs_match": True, "repeat_files_byte_identical": matches,
              "verification_script_sha256": sha(Path(__file__))}
    (HERE / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE/"out")
    parser.add_argument("--repeat", type=Path)
    args = parser.parse_args()
    main(args.out.resolve(), args.repeat.resolve() if args.repeat else None)
