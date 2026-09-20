"""Cross-check reports against the independent audit, then hash the archive."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

review = read(HERE / "REVIEW.json")
freeze = read(ROOT / "review/prerun_01/FREEZE.json")
summary = read(ROOT / "runs/batch_01/SUMMARY.json")
metrics = read(ROOT / "AGGREGATE_METRICS.json")
qa = read(ROOT / "review/prerun_01/QA.json")
if not review["technical_integrity_pass"] or review["failures"] or not qa["passed"]:
    raise RuntimeError("QA/independent review has not passed")
if len(review["rows"]) != len(summary["rows"]) or len(review["pairs"]) != len(freeze["requests"]["cases"]):
    raise RuntimeError("Incomplete audited grid")
if not review["source_integrity"]["audit_pass"] or any(sha(Path(p)) != h for p, h in freeze["sources"].items()):
    raise RuntimeError("Frozen-source integrity failed")
expected_cells = len(freeze["requests"]["cases"]) * len(freeze["arms"])
if len(summary["rows"]) != expected_cells:
    raise RuntimeError("Actual cell denominator differs from protocol")
fields = ["selected_candidate_count", "eligible_count", "ineligible_count", "unresolved_candidate_count",
          "eligible_completed", "eligible_missed", "ineligible_executed", "unresolved_executed",
          "unresolved_selector", "stage_actions_safe_and_complete", "native_calls"]
mapping = {"native_writes": "writes", "unique_accounts_with_eligible_request": "eligible_unique_accounts",
           "unique_reservations_with_eligible_request": "eligible_unique_reservations",
           "missing_information_count": "unresolved_required_information_count",
           "transfer_required_count": "unresolved_or_transfer_count",
           "constructed_request_count": "retained_request_cells",
           "unique_accounts": "unique_accounts", "unique_reservations": "unique_records"}
for exported, independently_audited in ((metrics["arms"], review["aggregate"]),
                                       (metrics["by_reason"], review["reason_aggregate"])):
    checked = {(r["arm"], r.get("reason")): r for r in independently_audited}
    exported_keys = [(r["arm"], r.get("reason")) for r in exported]
    if len(exported_keys) != len(checked) or set(exported_keys) != set(checked):
        raise RuntimeError("Exported arm/reason groups differ from independent audit")
    for row in exported:
        audited = checked[(row["arm"], row.get("reason"))]
        if any(row[k] != audited[k] for k in fields):
            raise RuntimeError("Exported totals differ from independent audit")
        if any(row[k] != audited[v] for k, v in mapping.items()):
            raise RuntimeError("Exported category or unique-unit totals differ")
        cells = [r for r in review["rows"] if r["arm"] == row["arm"]
                 and (row.get("reason") is None or r["reason"] == row["reason"])]
        for field, category in (("missing_information_executed", "unresolved_required_information"),
                                ("transfer_required_executed", "unresolved_or_transfer")):
            reconstructed = sum(cell["categories"][rid] == category
                                for cell in cells for rid in cell["actual_cancelled_ids"])
            if row[field] != reconstructed:
                raise RuntimeError("Exported unresolved execution subtype differs from reconstructed effects")

status = {
    "status": "completed_and_independently_audited", "recorded_at": datetime.now(timezone.utc).isoformat(),
    "declared_cells": expected_cells, "completed_cells": len(summary["rows"]),
    "constructed_request_contexts": len(freeze["requests"]["cases"]),
    "unique_accounts": freeze["requests"]["selected_accounts"],
    "unique_reservations": freeze["requests"]["unique_selected_reservations"],
    "arms": freeze["arms"], "synthetic_qa_tests_passed": qa["tests"],
    "source_files_frozen": len(freeze["sources"]), "vendor_files_frozen": len(freeze["vendor_sources"]),
    "independent_review_passed": True, "cohort_reconstruction_passed": review["cohort_audit"]["audit_pass"],
    "paired_request_checks": len(review["pairs"]), "issued_permissions_checked": len(review["permissions"]),
    "native_primary_calls": sum(r["native_calls"] for r in metrics["arms"]),
    "native_primary_writes": sum(r["native_writes"] for r in metrics["arms"]),
    "native_replay_adds_independent_samples": False,
    "reports_match_independent_audit": True,
    "report_crosscheck_scope": "All arm and arm-by-reason structured totals, unique units, and separately reconstructed missing-information/transfer-required execution counts; narrative reviewed separately.",
    "audit_sha256": sha(HERE / "REVIEW.json"),
    "audit_script_sha256": sha(HERE / "audit_outputs.py"),
    "results_report_sha256": sha(ROOT / "RESULTS_REVIEW_ZH.md"),
    "postrun_wrapper_status": "Created after execution freeze; frozen original independent primitives reused",
    "model_calls": 0, "model_api_cost_usd": 0,
    "official_task_score": None, "full_task_success_established": False,
    "paper_changed": False, "overleaf_updated": False, "github_updated": False,
    "interpretation": "Native-record controlled integration coverage with three scripted paired contexts per account; not a new official benchmark, never-seen dataset, or live-user trial."
}
save(HERE / "STATUS.json", status)
target = HERE / "EVIDENCE_SHA256.json"
paths = [p for p in sorted(ROOT.rglob("*")) if p.is_file() and p != target]
files = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
save(target, {"recorded_at": datetime.now(timezone.utc).isoformat(), "file_count": len(files), "files": files})
if any(sha(ROOT / p) != h for p, h in files.items()):
    raise RuntimeError("Archive changed during finalization")
print(json.dumps({"status": status["status"], "cells": expected_cells, "archive_files": len(files),
                  "native_calls": status["native_primary_calls"], "native_writes": status["native_primary_writes"]}))
