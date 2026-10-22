"""Recompute every published R1.2 scalar table from all 504 safe records.

Python standard library only. No ledger, credentials, API, original workspace,
candidate source, sandbox or external service is needed. This checks numerical
reproduction of the supplied scalar records, not a rerun of model/candidate jobs.
"""
import csv
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
TOLERANCE = 1e-12
ASSIGNMENT_FIELDS = ("episode", "batch_id", "study_budget", "condition", "arm", "model",
                     "provider", "repeat", "formal_study", "development_only")
TABLE_METADATA = ("run_status", "stop_reason", "formal_run_complete", "protocol_sha256", "analysis_source_sha256")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_analysis(path):
    spec = importlib.util.spec_from_file_location("_frozen_formal_analysis", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compare(actual, expected, path="tables", counts=None):
    if counts is None:
        counts = {"numeric_values_verified": 0, "maximum_absolute_difference": 0.0}
    if type(actual) in (int, float) and type(expected) in (int, float):
        if not math.isfinite(actual) or not math.isfinite(expected):
            raise ValueError("Nonfinite result at " + path)
        difference = abs(actual-expected)
        if difference > TOLERANCE:
            raise ValueError("Numerical mismatch at " + path)
        counts["numeric_values_verified"] += 1
        counts["maximum_absolute_difference"] = max(counts["maximum_absolute_difference"], difference)
    elif isinstance(actual, dict) and isinstance(expected, dict):
        if set(actual) != set(expected):
            raise ValueError("Field mismatch at " + path)
        for key in actual:
            compare(actual[key], expected[key], path + "." + key, counts)
    elif isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            raise ValueError("Length mismatch at " + path)
        for i, (a, b) in enumerate(zip(actual, expected)):
            compare(a, b, path + "[" + str(i) + "]", counts)
    elif type(actual) is not type(expected) or actual != expected:
        raise ValueError("Value/missingness mismatch at " + path)
    return counts


def csv_rows(document):
    strata, contrasts = [], []
    for s in document["strata"]:
        for metric, m in s["metrics"].items():
            strata.append(dict(budget=s["study_budget"],condition=s["condition"],control=s["arm"],metric=metric,
                planned_n=24,observed_n=m["observed_n"],missing_n=m["missing_n"],
                mean=m["fixed_denominator_point"],observed_sum=m["observed_sum"],
                ci_low=m["ci95"][0] if m["ci95"] else None,ci_high=m["ci95"][1] if m["ci95"] else None,
                lower_bound=m["fixed_denominator_lower_bound"],upper_bound=m["fixed_denominator_upper_bound"],
                lower_bound_ci_low=m["lower_bound_ci95"][0] if m["lower_bound_ci95"] else None,
                lower_bound_ci_high=m["lower_bound_ci95"][1] if m["lower_bound_ci95"] else None,
                upper_bound_ci_low=m["upper_bound_ci95"][0] if m["upper_bound_ci95"] else None,
                upper_bound_ci_high=m["upper_bound_ci95"][1] if m["upper_bound_ci95"] else None,
                applicable=m["applicable"]))
    for c in document["paired_contrasts"]:
        for metric, m in c["metrics"].items():
            contrasts.append(dict(contrast=c["contrast"],left="|".join(map(str,c["left"])),
                right="|".join(map(str,c["right"])),metric=metric,planned_pairs=24,
                complete_pairs=m["complete_pairs"],difference=m["point"],
                ci_low=m["ci95"][0] if m["ci95"] else None,ci_high=m["ci95"][1] if m["ci95"] else None,
                lower_bound=m["lower_bound"],upper_bound=m["upper_bound"],
                lower_bound_ci_low=m["lower_bound_ci95"][0] if m["lower_bound_ci95"] else None,
                lower_bound_ci_high=m["lower_bound_ci95"][1] if m["lower_bound_ci95"] else None,
                upper_bound_ci_low=m["upper_bound_ci95"][0] if m["upper_bound_ci95"] else None,
                upper_bound_ci_high=m["upper_bound_ci95"][1] if m["upper_bound_ci95"] else None))
    return {"all_strata.csv": strata, "all_paired_contrasts.csv": contrasts}


def csv_text(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def verify_csv(path, rows):
    expected = list(csv.DictReader(io.StringIO(csv_text(rows))))
    observed = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    # Metric-key order can differ between in-memory and sort_keys JSON output.
    key = lambda row: tuple(str(row[k]) for k in row if k in
                           ("budget", "condition", "control", "contrast", "left", "right", "metric"))
    if sorted(expected, key=key) != sorted(observed, key=key):
        raise ValueError("CSV projection mismatch: " + path.name)


def reproduce(directory):
    manifest = read(directory / "MANIFEST.json")
    expected_names = {"analysis.py", "SAFE_ASSIGNED_ROWS.json", "SAFE_PROTOCOL.json", "TABLES.json", "CONTINUATION_PROVENANCE.json",
                      "all_strata.csv", "all_paired_contrasts.csv", "README.md", "reproduce.py"}
    if set(manifest["files_sha256"]) != expected_names:
        raise ValueError("Unexpected bundle inventory")
    for name, expected in manifest["files_sha256"].items():
        if sha(directory / name) != expected:
            raise ValueError("Bundle checksum mismatch: " + name)
    analysis = load_analysis(directory / "analysis.py")
    safe_protocol = read(directory / "SAFE_PROTOCOL.json")
    continuation = read(directory / "CONTINUATION_PROVENANCE.json")
    records = read(directory / "SAFE_ASSIGNED_ROWS.json")
    rows = safe_protocol["rows"]
    analysis.validate_assignments(rows)
    if len(records) != 504 or len({r["episode"] for r in records}) != 504:
        raise ValueError("All 504 unique assigned records must remain")
    assignments = {r["episode"]:r for r in rows}
    for r in records:
        if {k:r[k] for k in ASSIGNMENT_FIELDS} != assignments[r["episode"]]:
            raise ValueError("Record/assignment mismatch")
        if set(r["metrics"]) != set(analysis.BOUNDS):
            raise ValueError("A prespecified metric is missing")
    expected = read(directory / "TABLES.json")
    rebuilt = analysis.analyze(rows, records)
    expected_core = {k:v for k,v in expected.items() if k not in TABLE_METADATA}
    verification = compare(rebuilt, expected_core)
    if expected["analysis_source_sha256"] != sha(directory / "analysis.py"):
        raise ValueError("Frozen analysis hash mismatch")
    if expected["protocol_sha256"] != safe_protocol["source_frozen_protocol_sha256"]:
        raise ValueError("Original frozen-protocol binding mismatch")
    if expected["run_status"] != "completed" or expected["formal_run_complete"] is not True:
        raise ValueError("Bundle is not a completed formal run")
    if (continuation["original_protocol_sha256"] != expected["protocol_sha256"]
            or continuation["preserved_previously_started_rows"] != 246
            or continuation["continued_never_started_rows"] != 258
            or continuation["previously_started_rows_replayed"] != 0
            or continuation["original_rows_preserved"] is not True):
        raise ValueError("Incomplete amended-execution provenance")
    if set(continuation["protected_episode_ids"]) | set(continuation["continued_episode_ids"]) != set(assignments):
        raise ValueError("Continuation provenance does not cover all assignments")
    if set(continuation["protected_episode_ids"]) & set(continuation["continued_episode_ids"]):
        raise ValueError("Continuation overlaps previously started rows")
    for name, flat in csv_rows(rebuilt).items():
        verify_csv(directory / name, flat)
    return dict(verified=True, amended_execution=True, retained_assigned_rows=504, batch_blocks=24, strata=21,
                paired_contrasts=51, absolute_numeric_tolerance=TOLERANCE,
                **verification, api_calls=0, candidate_executions=0)


if __name__ == "__main__":
    print(json.dumps(reproduce(Path(__file__).resolve().parent), indent=2))
