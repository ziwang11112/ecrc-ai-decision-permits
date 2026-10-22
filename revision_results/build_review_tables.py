"""Create numerical CSV tables from frozen results; never rerun experiments.

Only the supplied output directory is written. Standard library only. The raw
condition and field names are retained in CSV. This public helper has no
manuscript captions, presentation fragments or document output.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

CONDITIONS = [(1, "normal"), (1, "hidden_first_result"),
              (3, "normal"), (3, "hidden_first_result"),
              (5, "normal"), (5, "hidden_first_result"),
              (3, "missing_required_metadata_hidden_first_result")]
ARMS = ["prompt_only", "ordinary", "ecrc"]
PAIRS = [("ecrc", "prompt_only"), ("ordinary", "prompt_only"), ("ecrc", "ordinary")]
STATUSES = ["finished", "model_response_error", "provider_failure", "turn_limit", "interrupted"]


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()










def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r1-data", type=Path, required=True)
    parser.add_argument("--primary-contrasts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    inputs = [args.r1_data / "SAFE_ASSIGNED_ROWS.json", args.r1_data / "all_paired_contrasts.csv", args.primary_contrasts]
    input_hashes = {str(p.resolve()): sha(p) for p in inputs}
    assigned = json.loads(inputs[0].read_text(encoding="utf-8"))
    contrasts = read_csv(inputs[1])
    primary = [r for r in read_csv(inputs[2]) if r["metric"] == "compliant_verified_yield"]
    assert len(assigned) == 504 and len(contrasts) == 357 and len(primary) == 8
    assert len({r["episode"] for r in assigned}) == 504
    assert set(r["outcome_status"] for r in assigned) == set(STATUSES)
    assert all(r["metrics"]["model_truncated"] == 1 for r in assigned if r["outcome_status"] == "model_response_error")

    arm_rows = [r for r in contrasts if r["contrast"] == "arm" and r["metric"] == "compliant_verified_yield"]
    selected = []
    for budget, condition in CONDITIONS:
        for left, right in PAIRS:
            matches = [r for r in arm_rows if r["left"] == f"{budget}|{condition}|{left}" and r["right"] == f"{budget}|{condition}|{right}"]
            assert len(matches) == 1
            row = matches[0]
            assert int(row["planned_pairs"]) == int(row["complete_pairs"]) == 24
            assert row["difference"] and row["ci_low"] and row["ci_high"]
            selected.append(row)
    assert len(selected) == 21

    missing_acceptance = [r for r in contrasts if r["contrast"] == "arm" and
        r["metric"] == "independent_accepted_yield" and int(r["complete_pairs"]) < int(r["planned_pairs"])]
    assert len(missing_acceptance) == 4
    for row in missing_acceptance:
        assert row["difference"] == row["ci_low"] == row["ci_high"] == ""
        assert all(row[key] for key in ("lower_bound", "upper_bound", "lower_bound_ci_low", "lower_bound_ci_high", "upper_bound_ci_low", "upper_bound_ci_high"))

    termination = []
    for budget, condition in CONDITIONS:
        for arm in ARMS:
            group = [r for r in assigned if (r["study_budget"], r["condition"], r["arm"]) == (budget, condition, arm)]
            assert len(group) == 24
            counts = Counter(r["outcome_status"] for r in group)
            incomplete = [r for r in group if r["outcome_status"] != "finished"]
            assert all(r["metrics"]["actual_starts"] is not None and r["metrics"]["raw_verified_yield"] is not None for r in incomplete)
            visible = sum(r["metrics"]["raw_verified_yield"] * 4 for r in incomplete)
            assert visible.is_integer() if isinstance(visible, float) else True
            record = {"study_budget": budget, "condition": condition, "arm": arm, "planned": 24,
                      **{s: counts[s] for s in STATUSES},
                      "nonfinished_starts": sum(r["metrics"]["actual_starts"] for r in incomplete),
                      "nonfinished_visible_passes": int(visible),
                      "unknown_final_acceptance": sum(r["metrics"]["independent_accepted_yield"] is None for r in group)}
            assert sum(record[s] for s in STATUSES) == 24
            termination.append(record)
    totals = {s: sum(r[s] for r in termination) for s in STATUSES}
    assert totals == {"finished": 465, "model_response_error": 24, "provider_failure": 8, "turn_limit": 5, "interrupted": 2}
    assert sum(r["nonfinished_starts"] for r in termination) == 43
    assert sum(r["nonfinished_visible_passes"] for r in termination) == 18
    assert sum(r["unknown_final_acceptance"] for r in termination) == 2

    write_csv(args.out / "primary_compliant_paired.csv", primary)
    write_csv(args.out / "additional_compliant_paired.csv", selected)
    write_csv(args.out / "additional_acceptance_bounds.csv", missing_acceptance)
    write_csv(args.out / "additional_termination_summary.csv", termination)
    assert all(sha(path) == input_hashes[str(path.resolve())] for path in inputs)
    report = {"input_sha256": input_hashes, "assigned": 504, "strata": len(termination),
              "primary_compliant_contrasts": len(primary), "additional_compliant_contrasts": len(selected),
              "incomplete_acceptance_contrasts_preserved_as_bounds": len(missing_acceptance),
              "outcome_status_totals": totals, "nonfinished_starts": 43,
              "nonfinished_visible_passes": 18, "input_files_unchanged": True,
              "model_calls": 0, "candidate_executions": 0}
    (args.out / "REVIEW_TABLES_VERIFICATION.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
