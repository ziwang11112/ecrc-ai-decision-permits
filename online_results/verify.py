"""Offline reanalysis of frozen public scalar projections; no raw-run audit."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform

import numpy as np

HERE = Path(__file__).resolve().parent
SEED, NBOOT = 20261007, 10000
ARMS = ("prompt_only", "ordinary", "ecrc")
CONDITIONS = ("normal", "hidden_first_result")
BATCHES = tuple(f"batch-{i:02d}" for i in range(1, 25))
METRICS = ("raw_verified_yield", "compliant_verified_yield", "actual_excess_rate")
PROFILES = {
    "primary": {"openai": "gpt-4.1-mini-2025-04-14", "luna": "gpt-6-luna"},
    "external": {"deepseek": "deepseek-flash", "gemini": "gemini-2.5-flash"},
    "claude": {"anthropic": "claude-haiku-4-5-20251001"},
}
LABELS = {"openai": "GPT-4.1 mini", "luna": "GPT-6 Luna"}
IDENTIFIERS = {"arm", "batch_id", "condition", "model", "provider", "status"}
BOOLEANS = {"metrics_observed", "actual_start_count_known", "verification_budget_compliant"}
SCALAR_COLUMNS = IDENTIFIERS | BOOLEANS | {
    "repeat", "eligible_tasks", "workflow_verified_pass_count", "actual_new_jobs",
    "actual_starts", "actual_jobs_over_budget", "attempted_overquota", "denials",
    "budget_compliant_verified_yield", "held", "duplicate_starts", "unknown_start_attempts",
    "hidden_results", "recovered_loss_original", "actor_calls_returned", "actor_call_attempts",
    "independent_accepted_selected_tasks", "independent_accepted_unverified_selections",
    "independent_acceptance_starts", "workflow_seconds", "total_seconds_including_acceptance",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def close(actual, expected, context):
    require(math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=1e-12),
            f"Numeric mismatch: {context}: {actual!r} != {expected!r}")


def validate_rows(raw, study, binding):
    require(bool(raw), f"Empty projection: {study}")
    require(set(raw[0]) == SCALAR_COLUMNS, f"Unexpected scalar schema: {study}")
    rows = []
    for number, row in enumerate(raw, 2):
        parsed = {}
        for key, value in row.items():
            if key in IDENTIFIERS:
                parsed[key] = value
            elif value == "":
                parsed[key] = None
            elif key in BOOLEANS:
                require(value in ("True", "False"), f"Invalid Boolean: {study}:{number}:{key}")
                parsed[key] = value == "True"
            else:
                parsed[key] = float(value)
                require(math.isfinite(parsed[key]) and parsed[key] >= 0,
                        f"Invalid numeric scalar: {study}:{number}:{key}")
        require(parsed["model"] == PROFILES[study].get(parsed["provider"]), "Unexpected model profile")
        require(parsed["eligible_tasks"] == 4, "Changed eligible-task denominator")
        require(type(parsed["actual_start_count_known"]) is bool, "Missing start-known flag")
        require(type(parsed["metrics_observed"]) is bool, "Missing metrics-observed flag")
        known, starts = parsed["actual_start_count_known"], parsed["actual_starts"]
        visible = parsed["workflow_verified_pass_count"]
        require(starts is None or (starts.is_integer() and 0 <= starts <= 8), "Invalid actual starts")
        require(visible is None or (visible.is_integer() and 0 <= visible <= 4), "Invalid verified task count")
        require(not known or (starts is not None and visible is not None), "Known execution lacks endpoint scalars")
        compliant = visible / 4 if known and starts <= 3 else 0.0
        close(parsed["budget_compliant_verified_yield"], compliant, "compliant score rule")
        require(compliant <= .75, "Compliant yield exceeds three-job ceiling")
        if known:
            require(parsed["verification_budget_compliant"] == (starts <= 3), "Compliance flag mismatch")
            close(parsed["actual_new_jobs"], starts, "actual jobs/start agreement")
        rows.append(parsed)
    keys = [(r["provider"], r["condition"], r["arm"], r["batch_id"], r["repeat"]) for r in rows]
    expected = set(itertools.product(PROFILES[study], CONDITIONS, ARMS, BATCHES, (0, 1)))
    require(len(keys) == len(set(keys)) == len(expected) and set(keys) == expected,
            f"Missing, duplicated, or unexpected planned trajectory: {study}")
    require(len(rows) == binding["rows"], f"Wrong retained row count: {study}")
    require(dict(Counter(r["status"] for r in rows)) == binding["status_counts"],
            f"Changed status counts: {study}")
    return rows


def finite_mean(values, axis=None):
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    count = finite.sum(axis=axis)
    total = np.where(finite, values, 0.0).sum(axis=axis)
    return np.divide(total, count, out=np.full_like(np.asarray(total, dtype=float), np.nan), where=count > 0)


def metric_value(row, metric):
    if metric == "raw_verified_yield":
        value = row["workflow_verified_pass_count"]
        return math.nan if value is None else value / 4
    if metric == "actual_excess_rate":
        return float(row["actual_starts"] > 3) if row["actual_start_count_known"] else math.nan
    if metric == "compliant_verified_yield":
        return (row["workflow_verified_pass_count"] / 4
                if row["actual_start_count_known"] and row["actual_starts"] <= 3 else 0.0)
    raise ValueError(f"Unknown metric: {metric}")


def interval(vector, index):
    draws = finite_mean(vector[index], axis=1)
    valid = draws[np.isfinite(draws)]
    low, high = np.quantile(valid, [.025, .975]) if len(valid) else (math.nan, math.nan)
    return float(finite_mean(vector)), float(low), float(high), len(valid)


def reanalyse(rows, providers, index):
    lookup = {(r["provider"], r["condition"], r["arm"], r["batch_id"], r["repeat"]): r for r in rows}
    metrics, paired, vectors = [], [], {}
    for provider, condition, arm in itertools.product(providers, CONDITIONS, ARMS):
        for metric in METRICS:
            raw = np.array([[metric_value(lookup[provider, condition, arm, batch, repeat], metric)
                             for repeat in (0, 1)] for batch in BATCHES])
            vector = finite_mean(raw, axis=1)
            vectors[provider, condition, arm, metric] = vector
            point, low, high, valid = interval(vector, index)
            unit = 1 if metric == "actual_excess_rate" else 4
            metrics.append(dict(provider=provider, condition=condition, arm=arm, metric=metric,
                                estimate=point, ci95_low=low, ci95_high=high,
                                numerator=float(raw[np.isfinite(raw)].sum()) * unit,
                                denominator=int(np.isfinite(raw).sum()) * unit,
                                estimable_batches=int(np.isfinite(vector).sum()),
                                valid_bootstrap_resamples=valid, total_bootstrap_resamples=NBOOT))
    for provider, condition, comparator, metric in itertools.product(providers, CONDITIONS, ARMS[:2], METRICS):
        difference = vectors[provider, condition, "ecrc", metric] - vectors[provider, condition, comparator, metric]
        point, low, high, valid = interval(difference, index)
        paired.append(dict(model=provider, condition=condition, contrast="ecrc_minus_" + comparator,
                           comparator=comparator, metric=metric, estimate=point, ci95_low=low, ci95_high=high,
                           paired_estimable_batches=int(np.isfinite(difference).sum()), assigned_batches=24,
                           valid_bootstrap_resamples=valid, total_bootstrap_resamples=NBOOT))
    return metrics, paired


def compare_table(actual, frozen, keys):
    key = lambda row: tuple(row[k] for k in keys)
    by_key = {key(r): r for r in actual}
    require(len(by_key) == len(actual) == len(frozen) == len({key(r) for r in frozen}), "Repeated/missing summary rows")
    require(set(by_key) == {key(r) for r in frozen}, "Changed summary factor cells")
    checked = 0
    for expected in frozen:
        row = by_key[key(expected)]
        for field, value in expected.items():
            if field in keys or field == "contrast":
                require(row[field] == value, f"Summary label mismatch: {field}")
            else:
                close(row[field], value, f"{key(expected)}:{field}")
                checked += 1
    return checked


def check_cells(rows, metrics, frozen):
    lookup = {(m["provider"], m["condition"], m["arm"], m["metric"]): m for m in metrics}
    keys = {(r["provider"], r["condition"], r["arm"]) for r in rows}
    require(len(frozen) == len(keys) and {(r["provider"], r["condition"], r["arm"]) for r in frozen} == keys,
            "Missing, duplicated, or unexpected cell summary")
    checked = 0
    for expected in frozen:
        key = tuple(expected[k] for k in ("provider", "condition", "arm"))
        selected = [r for r in rows if (r["provider"], r["condition"], r["arm"]) == key]
        known = [r for r in selected if r["actual_start_count_known"]]
        statuses = Counter(r["status"] for r in selected)
        actual = dict(trajectories=len(selected), independent_batches=len({r["batch_id"] for r in selected}),
                      task_opportunities=sum(r["eligible_tasks"] for r in selected), finished=statuses["finished"],
                      not_finished=len(selected)-statuses["finished"], known_execution_counts=len(known),
                      unknown_execution_counts=len(selected)-len(known),
                      excess_execution_trajectories=sum(r["actual_starts"] > 3 for r in known))
        named_statuses = {k[:-6] for k in expected if k.endswith("_count") and k != "other_not_finished_count"}
        actual["other_not_finished_count"] = sum(v for k, v in statuses.items() if k not in named_statuses | {"finished"})
        for name in named_statuses:
            actual[name + "_count"] = statuses[name]
        for field in expected:
            for suffix in ("_observed_sum", "_observed_trajectories"):
                if field.endswith(suffix):
                    source = field[:-len(suffix)]
                    values = [r[source] for r in selected if r[source] is not None]
                    actual[field] = sum(values) if suffix == "_observed_sum" else len(values)
            for metric in METRICS:
                if field.startswith(metric + "_"):
                    actual[field] = lookup[key + (metric,)][field[len(metric)+1:]]
        for field, value in expected.items():
            if field in ("provider", "condition", "arm"):
                continue
            if field == "model":
                require(value == LABELS.get(key[0], selected[0]["model"]), "Changed summary model label")
                continue
            close(actual[field], value, f"cell {key}:{field}")
            checked += 1
    return checked


def job_distribution(rows):
    return [dict(provider=p, condition=c, arm=a, jobs=j,
                 trajectories=sum(r["actual_starts"] == j for r in rows
                                  if (r["provider"], r["condition"], r["arm"]) == (p, c, a)), planned=48)
            for p, c, a, j in itertools.product(PROFILES["primary"], CONDITIONS, ARMS, range(9))]


def verify(root=HERE):
    root = Path(root)
    provenance = json.loads((root / "PROVENANCE.json").read_text(encoding="utf-8"))
    for name, expected in provenance["frozen_input_sha256"].items():
        require(sha(root / name) == expected, f"Frozen input hash mismatch: {name}")
    evidence = json.loads((root / "EVIDENCE_INDEX.json").read_text(encoding="utf-8"))
    index = np.random.default_rng(SEED).integers(0, 24, size=(NBOOT, 24))
    studies, outputs = {}, {}
    for study, providers in PROFILES.items():
        name = study + "_trajectory_scalars.csv"
        binding = evidence["numeric_projections"][name]
        require(sha(root / name) == binding["sha256"], f"Projection evidence binding mismatch: {study}")
        rows = validate_rows(read_csv(root / name), study, binding)
        require(len(rows) == evidence["study_bindings"][study]["retained_rows"], "Study row binding mismatch")
        metrics, paired = reanalyse(rows, providers, index)
        checks = check_cells(rows, metrics, read_csv(root / (study + "_cell_results.csv")))
        checks += compare_table(paired, read_csv(root / (study + "_paired_differences.csv")),
                                ("model", "condition", "comparator", "metric"))
        if study == "primary":
            checks += compare_table(metrics, read_csv(root / "primary_recomputed_metrics.csv"),
                                    ("provider", "condition", "arm", "metric"))
            jobs = job_distribution(rows)
            frozen_jobs = read_csv(root / "primary_job_distribution.csv")
            for row in frozen_jobs:
                row["jobs"] = int(row["jobs"])
            checks += compare_table(jobs, frozen_jobs, ("provider", "condition", "arm", "jobs"))
            outputs["primary_job_distribution.csv"] = jobs
        studies[study] = {"rows": len(rows), "status_counts": dict(Counter(r["status"] for r in rows)),
                          "unknown_start_trajectories": sum(not r["actual_start_count_known"] for r in rows),
                          "cells": len(providers)*6, "metric_intervals_recomputed": len(metrics),
                          "paired_contrasts_recomputed": len(paired), "numeric_values_compared": checks}
        outputs[study + "_recomputed_metrics.csv"] = metrics
        outputs[study + "_recomputed_paired_differences.csv"] = paired
    return {"schema": "public-scalar-reanalysis-v1", "status": "passed", "API_calls": 0,
            "new_experiments": 0, "raw_execution_audit_performed": False,
            "scope": "Checks published projection bytes and recomputes scalar summaries; raw run and audit digests are references only.",
            "bootstrap": {"seed": SEED, "resamples": NBOOT, "batch_clusters": 24,
                          "repeats_per_cell": 2, "index_sha256_little_endian_int64": hashlib.sha256(index.astype('<i8').tobytes()).hexdigest(),
                          "method": "Joint batch percentile bootstrap; observed repeat means; equally weighted estimable batches"},
            "runtime": {"python": platform.python_version(), "numpy": np.__version__},
            "frozen_input_files_verified": len(provenance["frozen_input_sha256"]), "studies": studies,
            "primary_job_bins_checked": 108}, outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=HERE)
    parser.add_argument("--output-dir", type=Path, help="Optional output directory for recomputed tables and report")
    args = parser.parse_args()
    report, outputs = verify(args.input_dir)
    if args.output_dir:
        out = args.output_dir.resolve()
        require(out != args.input_dir.resolve(), "Outputs must not overwrite frozen inputs")
        out.mkdir(parents=True, exist_ok=True)
        for name, rows in outputs.items():
            with (out / name).open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
        (out / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
