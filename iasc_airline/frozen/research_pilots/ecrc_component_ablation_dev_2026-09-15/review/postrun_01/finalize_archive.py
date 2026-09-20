"""Cross-check exported metrics and archive this completed local experiment."""
import csv
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

def save(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

review = read(HERE / "REVIEW.json")
freeze = read(ROOT / "review/prerun_01/FREEZE.json")
qa = read(ROOT / "review/prerun_01/QA.json")
expected_cells = len(freeze["requests"]["cases"]) * len(freeze["arms"])
if not review["technical_integrity_pass"] or review["failures"] or len(review["rows"]) != expected_cells:
    raise RuntimeError("Independent review incomplete")
if not qa["passed"] or any(sha(Path(p)) != h for p, h in freeze["sources"].items()):
    raise RuntimeError("QA or frozen source integrity failed")
if review["changed_sources"] or review["changed_vendor_sources"] or review["changed_prior_v2_sources"]:
    raise RuntimeError("Audited source drift")

with (ROOT / "ARM_METRICS.csv").open(encoding="utf-8", newline="") as stream:
    csv_rows = {r["arm"]: r for r in csv.DictReader(stream)}
if set(csv_rows) != set(freeze["arms"]):
    raise RuntimeError("Exported arm set differs")
fields = ["selected_candidate_count", "eligible_count", "ineligible_count",
          "unresolved_candidate_count", "eligible_completed", "eligible_missed",
          "ineligible_executed", "unresolved_executed", "unresolved_selector",
          "stage_actions_safe_and_complete", "native_calls"]
for arm in review["aggregate"]:
    exported = csv_rows[arm["arm"]]
    if any(int(exported[k]) != arm[k] for k in fields):
        raise RuntimeError("CSV does not match independent audited counts")
    if int(exported["source_request_count"]) != arm["request_cases"] or int(exported["native_writes"]) != arm["writes"]:
        raise RuntimeError("CSV request/write count mismatch")

status = {
    "status": "completed_and_independently_audited",
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "declared_cells": expected_cells, "completed_cells": len(review["rows"]),
    "source_requests_per_arm": len(freeze["requests"]["cases"]),
    "arms": freeze["arms"], "synthetic_qa_tests_passed": qa["tests"],
    "source_files_frozen": len(freeze["sources"]),
    "vendor_files_frozen": len(freeze["vendor_sources"]),
    "prior_v2_anchor_comparisons": len(review["prior_v2_exact_reproduction"]),
    "native_primary_calls": sum(r["native_calls"] for r in review["aggregate"]),
    "native_primary_writes": sum(r["writes"] for r in review["aggregate"]),
    "independent_review_passed": True, "csv_matches_independent_audit": True,
    "audit_sha256": sha(HERE / "REVIEW.json"),
    "results_report_sha256": sha(ROOT / "RESULTS_REVIEW_ZH.md"),
    "retained_auditor_failure_versions": ["REVIEW_v1.json", "REVIEW_v2.json"],
    "audit_corrections": ["Read SQLite copies to avoid creating source sidecars", "Distinguish released history from held reservations"],
    "native_reruns_for_audit_corrections": 0,
    "model_calls": 0, "model_api_cost_usd": 0,
    "full_task_success_established": False,
    "paper_changed": False, "overleaf_updated": False, "github_updated": False,
    "interpretation": "Same exposed development requests; retain ordinary-rules and clean-metadata ties. Claim-dependency ablation tests permission enforcement, not unique business intelligence. Unresolved cases remain incomplete."
}
save(HERE / "STATUS.json", status)
target = HERE / "EVIDENCE_SHA256.json"
files = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(ROOT.rglob("*")) if p.is_file() and p != target}
save(target, {"recorded_at": datetime.now(timezone.utc).isoformat(), "file_count": len(files), "files": files})
if any(sha(ROOT / p) != h for p, h in files.items()):
    raise RuntimeError("Archive changed while finalizing")
print(json.dumps({"status": status["status"], "cells": expected_cells, "archive_files": len(files), "audit_passed": True}))
