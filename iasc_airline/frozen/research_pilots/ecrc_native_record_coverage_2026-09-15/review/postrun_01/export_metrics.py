"""Retain every completed fixed cell; export controlled, not population, counts."""
from collections import defaultdict
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save_csv(name, records):
    with (ROOT / name).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

freeze = read(ROOT / "review/prerun_01/FREEZE.json")
summary = read(ROOT / "runs/batch_01/SUMMARY.json")
review = read(ROOT / "review/postrun_01/REVIEW.json")
if not review["technical_integrity_pass"] or review["failures"]:
    raise RuntimeError("Independent audit has not passed; retain failures before exporting claims")
cases = {c["case_id"]: c for c in freeze["requests"]["cases"]}
expected = {(k, arm) for k in cases for arm in freeze["arms"]}
rows = summary["rows"]
if len(rows) != len(expected) or {(r["case_id"], r["arm"]) for r in rows} != expected:
    raise RuntimeError("Missing, duplicate or undeclared cells")

fields = ["selected_candidate_count", "eligible_count", "ineligible_count", "unresolved_candidate_count",
          "eligible_completed", "eligible_missed", "ineligible_executed", "unresolved_executed",
          "unresolved_selector", "stage_actions_safe_and_complete", "out_of_selection_executed_count"]
cells = []
for row in rows:
    ev, case = row["case_evaluation"], cases[row["case_id"]]
    if row["execution_error"] or row["evaluation_returncode"] or not ev["metrics_valid"]:
        raise RuntimeError("Invalid cell may not disappear from the report")
    categories = ev["candidates"]
    missing = [c for c in categories if c["category"] == "unresolved_required_information"]
    transfer = [c for c in categories if c["category"] == "unresolved_or_transfer"]
    cells.append({"case_id": row["case_id"], "arm": row["arm"], "user_id": case["request"]["user_id"],
                  "reservation_id": case["request"]["cancellation"]["selector"]["ids"][0],
                  "reason": case["request"]["cancellation"]["reason"],
                  **{k: int(ev[k]) for k in fields},
                  "missing_information_count": len(missing),
                  "missing_information_executed": sum(c["executed"] for c in missing),
                  "transfer_required_count": len(transfer),
                  "transfer_required_executed": sum(c["executed"] for c in transfer),
                  "native_calls": row["native_calls"], "native_writes": row["native_writes"],
                  "native_errors": row["native_errors"],
                  "native_replay_verified": row["native_evaluation"]["all_recorded_tool_responses_reproduced"],
                  "full_task_success_established": False})

extra_counts = ["missing_information_count", "missing_information_executed", "transfer_required_count",
                "transfer_required_executed", "native_calls", "native_writes", "native_errors"]

def aggregate(group, identifiers):
    positives = [r for r in group if r["eligible_count"] > 0]
    return {**identifiers, "constructed_request_count": len(group),
            "unique_accounts": len({r["user_id"] for r in group}),
            "unique_reservations": len({r["reservation_id"] for r in group}),
            "unique_accounts_with_eligible_request": len({r["user_id"] for r in positives}),
            "unique_reservations_with_eligible_request": len({r["reservation_id"] for r in positives}),
            **{k: sum(r[k] for r in group) for k in fields + extra_counts},
            "full_task_success_established": False}

arms = [aggregate([r for r in cells if r["arm"] == a], {"arm": a}) for a in freeze["arms"]]
reasons = [aggregate([r for r in cells if r["arm"] == a and r["reason"] == reason], {"arm": a, "reason": reason})
           for a in freeze["arms"] for reason in ("health", "other", "unspecified")]
for name, values in (("CASE_METRICS.csv", cells), ("ARM_METRICS.csv", arms), ("REASON_METRICS.csv", reasons)):
    save_csv(name, values)
with (ROOT / "AGGREGATE_METRICS.json").open("x", encoding="utf-8") as stream:
    json.dump({"arms": arms, "by_reason": reasons,
               "denominator": "100 fixed native accounts, one reservation each, three constructed paired reason settings; not independent benchmark tasks"},
              stream, ensure_ascii=False, indent=2)
    stream.write("\n")
print(json.dumps({"exported_cells": len(cells), "arms": arms}, ensure_ascii=False))
