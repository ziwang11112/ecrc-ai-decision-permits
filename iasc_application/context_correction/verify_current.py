"""Offline S9-C numerical reconciliation, with optional public event audit.

Python standard library only. Never executes candidates or contacts a service.
Full event mode requires the two complete, separately downloaded public bundles.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path, PurePosixPath
import statistics
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
IDENTITY = ("run_id", "batch_id", "arm", "policy", "condition")
SUMS = ("eligible_tasks", "timely_tasks", "durable_pass_tasks_by_deadline",
        "eventual_pass_tasks", "jobs", "actual_starts", "pass_jobs", "fail_jobs",
        "timeout_jobs", "http_posts", "response_drops", "cache_hits", "primary_retries",
        "drain_retries", "child_cpu_seconds", "suite_wall_seconds",
        "launcher_wall_seconds", "late_host_launches", "denied_decisions")
FLOATS = {"child_cpu_seconds", "suite_wall_seconds", "launcher_wall_seconds"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def table(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def numeric(value):
    if isinstance(value, str) and value in ("True", "False"):
        return value == "True"
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def equal(actual, expected, label):
    a, b = numeric(actual), numeric(expected)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        require(math.isfinite(a) and math.isfinite(b) and
                math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-8), label)
    else:
        require(a == b, label)


def compare(actual, expected, label):
    for key, value in expected.items():
        require(key in actual, f"{label}: missing {key}")
        equal(actual[key], value, f"{label}: {key}")


def unique(rows, keys):
    result = {tuple(row[k] for k in keys): row for row in rows}
    require(len(result) == len(rows), "Duplicate identities: " + repr(keys))
    return result


def check_source_map():
    source = read(HERE / "SOURCE_MAP.json")
    frozen = read(HERE / "FROZEN_PUBLIC_MANIFEST.json")
    entries = source["files"] + source["omitted_files"]
    by_source = unique(entries, ("source_path",))
    require(len(entries) == 1386, "Frozen archive coverage")
    for entry in frozen["files"]:
        row = by_source[(entry["path"],)]
        require((row["bytes"], row["sha256"]) == (entry["bytes"], entry["sha256"]),
                "Frozen source manifest mismatch: " + entry["path"])
    require(set(by_source) == {(r["path"],) for r in frozen["files"]} |
            {("PUBLIC_MANIFEST.json",)}, "Unexpected archived path")
    for row in source["files"]:
        path = PurePosixPath(row["path"])
        require(not path.is_absolute() and not any(p in (".", "..") or ":" in p for p in path.parts)
                and path.as_posix() == row["path"] and "\\" not in row["path"], "Unsafe source path")
        target = HERE.joinpath(*path.parts).resolve()
        require(target.is_relative_to(HERE) and target.is_file(), "Missing selected source")
        require(target.stat().st_size == row["bytes"] and sha(target) == row["sha256"],
                "Selected source changed: " + row["path"])
    return source


def from_jobs(jobs):
    require(bool(jobs), "Empty trajectory")
    require({int(j["launch_ordinal"]) for j in jobs} == set(range(1, len(jobs) + 1)), "Launch ordering")
    unique(jobs, ("operation_id",))
    unique(jobs, ("effect_id",))
    require(all(j["status"] in {"pass", "fail", "timeout"} and int(j["actual_starts"]) == 1
                for j in jobs), "Unexpected status or starts")
    passes = [j for j in jobs if j["status"] == "pass"]
    timely = {j["task_id"] for j in passes if j["reconciled_phase"] == "primary"
              and float(j["reconciled_elapsed_s"]) <= 5}
    eventual = {j["task_id"] for j in passes}
    durable = {j["task_id"] for j in passes if float(j["result_commit_elapsed_s"]) <= 5}
    dropped = sum(j["response_dropped"] == "True" for j in jobs)
    result = {"timely_tasks": len(timely), "eventual_pass_tasks": len(eventual),
              "durable_pass_tasks_by_deadline": len(durable), "jobs": len(jobs),
              "actual_starts": sum(int(j["actual_starts"]) for j in jobs),
              "response_drops": dropped,
              "late_host_launches": sum(float(j["launcher_start_elapsed_s"]) > 5 for j in jobs),
              "timely_task_ids": "|".join(sorted(timely)), "eventual_task_ids": "|".join(sorted(eventual))}
    result.update({status + "_jobs": sum(j["status"] == status for j in jobs)
                   for status in ("pass", "fail", "timeout")})
    result.update({key: sum(float(j[key]) for j in jobs) for key in FLOATS})
    return result


def numerical_check():
    analysis = HERE / "analysis/combined"
    runs, jobs = table(analysis / "S9_runs.csv"), table(analysis / "S9_jobs.csv")
    original_runs = table(HERE.parent / "analysis/S9_runs.csv")
    original_jobs = table(HERE.parent / "analysis/S9_jobs.csv")
    current = unique(runs, ("run_id",))
    original = unique(original_runs, ("run_id",))
    expected_ids = {(f"r{i:03d}",) for i in range(1, 145)}
    require(set(current) == set(original) == expected_ids, "All 144 original/current runs must remain")
    plan = read(HERE / "correction/GRID_PLAN.json")
    assembly = read(HERE / "correction/ASSEMBLY_AUDIT.json")
    require(assembly["all_candidates"] == 656 and assembly["changed_candidates"] == 11
            and len(assembly["changed"]) == 11
            and {r["task_id"] for r in assembly["changed"]} ==
            {"HumanEval/10", "HumanEval/32", "HumanEval/38", "HumanEval/50"}, "Bounded context correction")
    replacements = {c["original_run_id"] for c in plan["cells"]}
    retained = set(plan["retained_original_runs"])
    require(len(replacements) == 32 and len(retained) == 112 and not replacements & retained
            and replacements | retained == {x[0] for x in expected_ids}, "112+32 partition")
    for cell in plan["cells"]:
        compare(current[(cell["original_run_id"],)], {"batch_id": cell["batch"],
                **{k: cell[k] for k in ("arm", "policy", "condition")}}, "Replacement identity")
    expected_cells = set(itertools.product((f"evaluation_{i:02d}" for i in range(1, 19)),
                                          ("ecrc", "ordinary"), ("depth_first", "round_robin"),
                                          ("normal", "response_loss")))
    require(set(unique(runs, IDENTITY[1:])) == expected_cells, "Complete factorial grid")
    job_groups, old_job_groups = defaultdict(list), defaultdict(list)
    for row in jobs:
        require((row["run_id"],) in current, "Orphan current job")
        compare(row, {k: current[(row["run_id"],)][k] for k in IDENTITY}, "Job factors")
        job_groups[row["run_id"]].append(row)
    for row in original_jobs:
        require((row["run_id"],) in original, "Orphan historical job")
        old_job_groups[row["run_id"]].append(row)
    for run in runs:
        rid = run["run_id"]
        compare(run, from_jobs(job_groups[rid]), rid)
        equal(run["eligible_tasks"], 8, rid + " eligible tasks")
        equal(int(run["http_posts"]), int(run["jobs"]) + int(run["cache_hits"]), rid + " HTTP accounting")
        equal(int(run["cache_hits"]), int(run["primary_retries"]) + int(run["drain_retries"]), rid + " retry accounting")
        require(int(run["final_held"]) == 0 and int(run["final_committed"]) == int(run["jobs"])
                and int(run["stop_held"]) + int(run["stop_committed"]) <= 16, rid + " budget snapshots")
        if rid in retained:
            compare(run, original[(rid,)], rid + " retained original run")
            require(job_groups[rid] == old_job_groups[rid], rid + " retained original jobs")
    for run in original_runs:
        compare(run, from_jobs(old_job_groups[run["run_id"]]), "Historical " + run["run_id"])
    differences = table(analysis / "old_new_run_differences.csv")
    require(set(unique(differences, ("run_id",))) == expected_ids, "Complete old/new comparison")
    for row in differences:
        rid = row["run_id"]
        for key in SUMS:
            before, after = float(original[(rid,)][key]), float(current[(rid,)][key])
            compare(row, {key + "_old": before, key + "_corrected": after,
                          key + "_difference": after - before}, "Old/new " + rid)
    totals = {key: sum((float if key in FLOATS else int)(r[key]) for r in runs) for key in SUMS}
    summary = read(analysis / "corrected_summary.json")
    compare(summary["totals"], totals, "Combined totals")
    compare(summary["original_totals"], {key: sum(float(r[key]) for r in original_runs) for key in SUMS}, "Historical totals")
    for group in table(analysis / "S9_cells.csv"):
        subset = [r for r in runs if all(r[k] == group[k] for k in ("arm", "policy", "condition"))]
        sums = {key: sum(float(r[key]) for r in subset) for key in SUMS}
        compare(group, {**sums, "batches": 18, "timely_percent": 100 * sums["timely_tasks"] / 144,
                       "median_batch_complete_s": statistics.median(float(r["all_feedback_complete_elapsed_s"]) for r in subset),
                       "max_stop_held": max(int(r["stop_held"]) for r in subset),
                       "max_final_held": 0}, "Aggregated condition")
    cells = table(analysis / "S9_cells.csv")
    require(len(unique(cells, ("arm", "policy", "condition"))) == 8, "Eight aggregate cells")
    for supplied, frozen in zip(cells, summary["cells"]):
        compare(supplied, frozen, "Summary cell")
    pairs = table(analysis / "S9_paired_batches.csv")
    pair_keys = ("contrast", "batch_id", "arm", "policy", "condition")
    actual_pairs = unique(pairs, pair_keys)
    expected_pairs = {}
    for contrast, varying, left, right in (("round_robin_minus_depth_first", "policy", "round_robin", "depth_first"),
            ("ecrc_minus_ordinary", "arm", "ecrc", "ordinary"),
            ("response_loss_minus_normal", "condition", "response_loss", "normal")):
        match = [k for k in IDENTITY[1:] if k != varying]
        for left_run in (r for r in runs if r[varying] == left):
            right_run = next(r for r in runs if r[varying] == right and all(r[k] == left_run[k] for k in match))
            identity = {"contrast": contrast, **{k: left_run[k] if k in match else "paired" for k in IDENTITY[1:]}}
            key = tuple(identity[k] for k in pair_keys)
            expected_pairs[key] = {metric + "_difference": float(left_run[metric]) - float(right_run[metric])
                                  for metric in ("timely_tasks", "eventual_pass_tasks", "jobs", "child_cpu_seconds", "launcher_wall_seconds")}
    require(set(actual_pairs) == set(expected_pairs) and len(actual_pairs) == 216, "All paired contrasts")
    for key, expected in expected_pairs.items():
        compare(actual_pairs[key], expected, "Paired contrast")
    require(len(jobs) == 1769 and int(totals["response_drops"]) == 188 and len(original_jobs) == 1802,
            "Pinned current/historical totals")
    return {"current_runs": 144, "retained_original_runs": 112, "replacement_runs": 32,
            "historical_runs_preserved": 144, "superseded_original_runs_preserved": 32,
            "current_job_rows": len(jobs), "historical_job_rows": len(original_jobs),
            "paired_contrasts": len(pairs), "totals": totals}, runs, jobs


def full_event_check(original_root, correction_root, runs, jobs):
    require(not sys.flags.optimize, "Inherited auditors require assertions; do not use -O")
    original_root, correction_root = original_root.resolve(), correction_root.resolve()
    require(original_root != correction_root, "Original and correction bundles must be distinct")
    source = read(HERE / "SOURCE_MAP.json")
    for row in source["files"] + source["omitted_files"]:
        require(sha(correction_root / row["source_path"]) == row["sha256"], "Full correction differs from pinned archive")
    require(sha(original_root / "PUBLIC_INVENTORY.json") == sha(HERE.parent / "PUBLIC_INVENTORY.json"),
            "Original inventory differs from pinned release")
    # Subprocesses isolate the inherited auditors' same-named modules. Both are read-only.
    with tempfile.TemporaryDirectory(prefix="s9-public-audit-") as temporary:
        reports = []
        for index, (root, script, extra) in enumerate(((original_root, HERE.parent / "check_public.py", ["--public-only"]),
                                     (correction_root, HERE / "verify_public_context.py", []))):
            report = Path(temporary) / f"audit-{index}.json"
            subprocess.run([sys.executable, "-B", str(script), "--bundle", str(root),
                            *extra, "--out", str(report)], check=True, capture_output=True, text=True)
            reports.append(read(report))
    for filename in ("S9_runs.csv", "S9_jobs.csv"):
        require(sha(original_root / "analysis" / filename) == sha(HERE.parent / "analysis" / filename),
                "Historical Git table differs from pinned original archive")
    retained = read(HERE / "metadata/RETAINED_ORIGINAL_RUNS.json")["runs"]
    for row in retained:
        require(sha(original_root / row["original_public_path"]) == row["original_public_sha256"], "Retained summary binding")
    old_derived = reports[0]["independent_public_recalculation"]["runs"]
    old_derived = {r["run_id"]: r for r in old_derived if r["grid"] == "evaluation_v1"}
    new_derived = {r["run_id"]: r for r in reports[1]["derived"]["runs"]}
    require(len(old_derived) == 144 and len(new_derived) == 32, "Full historical/replacement event coverage")
    mapping = {"timely_tasks": "timely_tasks_recomputed", "eventual_pass_tasks": "eventual_tasks_recomputed",
               "actual_starts": "actual_starts_from_start_records", "response_drops": "response_drops_from_service_events",
               "cache_hits": "cache_hits_from_service_events", "stop_held": "stop_held_recomputed",
               "stop_committed": "stop_committed_recomputed", "final_held": "final_held_recomputed",
               "final_committed": "final_committed_recomputed", **{k: k + "_recomputed" for k in FLOATS}}
    for row in runs:
        derived = new_derived.get(row["run_id"], old_derived[row["run_id"]])
        compare(row, {k: derived[v] for k, v in mapping.items()}, "Event-derived " + row["run_id"])
    # Independently bind every exported current job row to commit, reconciliation,
    # trusted launcher/result and actual-start records already checked by auditors.
    grouped = defaultdict(list)
    for job in jobs:
        grouped[job["run_id"]].append(job)
    for row in runs:
        rid = row["run_id"]
        folder = (correction_root / "results/runs" if rid in new_derived else
                  original_root / "results/evaluation_v1") / rid
        events = read(folder / "client_events.jsonl.public.json")
        service = read(folder / "service_runs/service_events.jsonl.public.json")
        summary = read(folder / "run_summary.json.public.json")
        start = summary["started_at_counter_ns"]
        arms = {e["operation_id"]: e for e in events if e["event"] == "armed"}
        receipts = {e["effect_id"]: e for e in events if e["event"] == "reconciled"}
        commits = {e["idempotency_key"]: e for e in service if e["event"] == "result_commit_return"}
        for job in grouped[rid]:
            commit = commits[job["operation_id"]]
            receipt = receipts[int(job["effect_id"])]; result = receipt["result"]
            expected = {k: result[k] for k in ("task_id", "candidate_id", "status", "solution_sha256", "test_sha256", "runner_sha256", "actual_starts")}
            expected.update(effect_id=commit["effect_id"], result_hash=commit["result_hash"],
                            child_cpu_seconds=result["cpu_seconds"], suite_wall_seconds=result["wall_seconds"],
                            launcher_wall_seconds=result["launcher_wall_seconds"],
                            launch_ordinal=arms[job["operation_id"]]["launch_ordinal"],
                            launcher_start_elapsed_s=(result["host_launch_perf_counter_ns"] - start) / 1e9,
                            result_commit_elapsed_s=(commit["perf_counter_ns"] - start) / 1e9,
                            reconciled_elapsed_s=(receipt["perf_counter_ns"] - start) / 1e9,
                            reconciled_phase=receipt["phase"],
                            response_dropped=any(e["event"] == "response_drop" and e["idempotency_key"] == job["operation_id"] for e in service))
            compare(job, expected, "Event-derived job")
        compare(row, {"primary_retries": sum(e["event"] == "retry" and e["phase"] == "primary" for e in events),
                      "drain_retries": sum(e["event"] == "retry" and e["phase"] == "drain" for e in events),
                      "denied_decisions": sum(e["event"] == "issued" and e["route"] != "alert" for e in events),
                      "observed_stop_elapsed_s": next(e["elapsed_s"] for e in events if e["event"] == "primary_stopped"),
                      "all_feedback_complete_elapsed_s": next(e["elapsed_s"] for e in events if e["event"] == "trajectory_complete")}, "Event-derived workflow")
    return {"historical_formal_trajectories_checked": 144, "replacement_trajectories_checked": 32,
            "current_trajectories_reconciled": 144, "current_job_rows_bound_to_events": len(jobs),
            "retained_public_summary_hashes_verified": len(retained), "passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-root", type=Path)
    parser.add_argument("--correction-root", type=Path)
    parser.add_argument("--out", type=Path, help="Optional fresh JSON report path outside iasc_application; always prints JSON")
    args = parser.parse_args()
    require(bool(args.original_root) == bool(args.correction_root), "Supply both public bundle roots for full event mode")
    output = args.out.resolve() if args.out else None
    if output is not None:
        require(not output.exists() and not output.is_relative_to(HERE.parent), "Report must be fresh and outside iasc_application")
    source = check_source_map()
    report, runs, jobs = numerical_check()
    report.update(passed=True, mode="public-events" if args.original_root else "numerical-tables",
                  selected_archive_files_verified=len(source["files"]),
                  omitted_archive_files_indexed=len(source["omitted_files"]),
                  candidate_code_executed=False, network_used=False,
                  limits="CSV mode recalculates from public job/run tables, not raw events. Event mode verifies public projections, not private original result_hash bytes. Neither mode re-executes candidates or verifies new experimental execution.")
    if args.original_root:
        report["public_event_audit"] = full_event_check(args.original_root, args.correction_root, runs, jobs)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False); stream.write("\n")
    print(json.dumps(report, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
