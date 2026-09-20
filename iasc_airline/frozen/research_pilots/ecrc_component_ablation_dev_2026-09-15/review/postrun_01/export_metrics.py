"""Export all declared cells, including unresolved cases, without new execution."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
summary = json.loads((ROOT / "runs/batch_01/SUMMARY.json").read_text(encoding="utf-8"))
freeze = json.loads((ROOT / "review/prerun_01/FREEZE.json").read_text(encoding="utf-8"))
rows = summary["rows"]
expected = {(c["case_id"], a) for c in freeze["requests"]["cases"] for a in freeze["arms"]}
actual = {(r["case_id"], r["arm"]) for r in rows}
if actual != expected or len(rows) != len(expected):
    raise RuntimeError("Missing, duplicate or undeclared cells")

fields = ["selected_candidate_count", "eligible_count", "ineligible_count",
          "unresolved_candidate_count", "eligible_completed", "eligible_missed",
          "ineligible_executed", "unresolved_executed", "unresolved_selector",
          "stage_actions_safe_and_complete", "out_of_selection_executed_count"]
cells = []
for row in rows:
    if row["execution_error"] or row["evaluation_returncode"] or not row["case_evaluation"]["metrics_valid"]:
        raise RuntimeError("Invalid cell; inspect retained result before making a summary")
    ev = row["case_evaluation"]
    cells.append({"case_id": row["case_id"], "task_id": row["task_id"], "arm": row["arm"],
                  **{k: int(ev[k]) for k in fields},
                  "native_calls": row["native_calls"], "native_writes": row["native_writes"],
                  "native_errors": row["native_errors"],
                  "native_component_score_diagnostic_only": row["native_evaluation"]["adapter_composed_native_reward"],
                  "elapsed_local_stage_seconds_diagnostic_only": row["elapsed_local_seconds"],
                  "full_task_success_established": False})

arms = []
for arm in freeze["arms"]:
    group = [c for c in cells if c["arm"] == arm]
    arms.append({"arm": arm, "source_request_count": len(group),
                 **{k: sum(c[k] for c in group) for k in fields},
                 **{k: sum(c[k] for c in group) for k in ("native_calls", "native_writes", "native_errors")},
                 "native_component_score_one_count_diagnostic_only": sum(c["native_component_score_diagnostic_only"] == 1 for c in group),
                 "full_task_success_established": False})

for name, values in (("CASE_METRICS.csv", cells), ("ARM_METRICS.csv", arms)):
    with (ROOT / name).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(values[0]))
        writer.writeheader()
        writer.writerows(values)
print(json.dumps({"exported_cells": len(cells), "exported_arms": len(arms),
                  "native_calls": sum(c["native_calls"] for c in cells),
                  "native_writes": sum(c["native_writes"] for c in cells)}, indent=2))
