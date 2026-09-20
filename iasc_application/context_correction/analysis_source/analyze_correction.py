"""Read-only raw audit and descriptive aggregation of the versioned S9 correction.

No workflow/service import or candidate execution. Reuses the historical independent
raw-artifact auditor, with a separately checked assembled-source catalog. Outputs are
new and never replace historical data. Run only after all 32 replacements finish.
"""
from __future__ import annotations

import argparse
import ast
import collections
import csv
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import symtable
import sys
import traceback
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
ORIGINAL = HERE.parent / "iasc_application_2026-09-12"
ADAPTER = WORKSPACE / "qa/iasc_application_pilot_2026-09-12/statistics/audit/raw_adapter.py"
OLD_ANALYZER = WORKSPACE / "qa/iasc_application_pilot_2026-09-12/analyze_application.py"
PRIOR_AUDIT = WORKSPACE / "qa/iasc_manuscript_refinement_2026-09-13/S9_CONTEXT_AUDIT.json"
BATCHES = {"evaluation_01", "evaluation_10", "evaluation_14", "evaluation_15"}
SUMS = ["eligible_tasks", "timely_tasks", "durable_pass_tasks_by_deadline", "eventual_pass_tasks",
        "jobs", "actual_starts", "pass_jobs", "fail_jobs", "timeout_jobs", "http_posts",
        "response_drops", "cache_hits", "primary_retries", "drain_retries", "child_cpu_seconds",
        "suite_wall_seconds", "launcher_wall_seconds", "late_host_launches", "denied_decisions"]


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def lines(p):
    return [json.loads(s) for s in Path(p).read_text(encoding="utf-8-sig").splitlines() if s.strip()]


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def digest(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def text_sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def write(p, value):
    Path(p).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def csvwrite(p, rows):
    if not rows:
        raise ValueError("Refusing empty output without a declared schema: " + str(p))
    with Path(p).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)


class Checks:
    def __init__(self):
        self.rows = []

    def require(self, name, passed, detail=None):
        self.rows.append({"check": name, "pass": bool(passed), "detail": detail})
        if not passed:
            raise ValueError(name + (": " + str(detail) if detail is not None else ""))


def independent_assembly(old, new, checks):
    """Check public snippets and original byte preservation without assembly helpers."""
    with gzip.open(ORIGINAL / "workload/sources/HumanEval.jsonl.gz", "rt", encoding="utf-8") as f:
        public = {x["task_id"]: {k: x[k] for k in ("task_id", "prompt", "entry_point")}
                  for x in map(json.loads, f)}
    helpers = {}
    for tid, task in public.items():
        helpers[tid] = [n for n in ast.parse(task["prompt"]).body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name != task["entry_point"]]
    inventory = {tid: [n.name for n in ns] for tid, ns in helpers.items() if ns}
    checks.require("public_helper_inventory", inventory == {"HumanEval/10": ["is_palindrome"],
                   "HumanEval/32": ["poly"], "HumanEval/38": ["encode_cyclic"], "HumanEval/50": ["encode_shift"]}, inventory)
    checks.require("catalog_top_level_unchanged", {k: v for k, v in new.items() if k not in ("jobs", "context_correction")} ==
                   {k: v for k, v in old.items() if k != "jobs"})
    checks.require("656_candidates_same_order", len(old["jobs"]) == len(new["jobs"]) == 656 and
                   [j["candidate_id"] for j in old["jobs"]] == [j["candidate_id"] for j in new["jobs"]])
    mutable = {"solution", "solution_sha256", "job_hash", "job_digest", "decision_id", "used_evidence_ids", "context_correction"}
    changes = []
    for before, after in zip(old["jobs"], new["jobs"]):
        cid, tid = before["candidate_id"], before["task_id"]
        prov = after["context_correction"]
        checks.require("unchanged_non_source_fields/" + cid,
                       {k: v for k, v in before.items() if k not in mutable} == {k: v for k, v in after.items() if k not in mutable})
        checks.require("original_public_context_hashes/" + cid,
                       prov["original_solution"] == before["solution"] and
                       prov["original_solution_sha256"] == before["solution_sha256"] == text_sha(before["solution"]) and
                       prov["original_decision_id"] == before["decision_id"] and
                       prov["public_prompt"] == public[tid]["prompt"] and
                       prov["public_prompt_sha256"] == text_sha(public[tid]["prompt"]) and
                       prov["context_sha256"] == text_sha(prov["context_source"]) and
                       prov["assembled_solution_sha256"] == after["solution_sha256"] == text_sha(after["solution"]))
        try:
            symbols = symtable.symtable(before["solution"], "archived_candidate", "exec")
            bound = {s.get_name() for s in symbols.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
            missing = [n.name for n in helpers[tid] if n.name not in bound] if before["solution"].strip() else []
        except SyntaxError:
            missing = []
        checks.require("exact_missing_public_helpers/" + cid, prov["added_helper_names"] == missing)
        if missing:
            ctx = prov["context_source"]
            public_nodes = ast.parse(public[tid]["prompt"]).body
            added_nodes = ast.parse(ctx).body
            allowed = [n for n in public_nodes if isinstance(n, (ast.Import, ast.ImportFrom)) or
                       isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in missing]
            dumps = [ast.dump(n, include_attributes=False) for n in allowed]
            checks.require("context_only_exact_public_nodes/" + cid,
                           all(ast.dump(n, include_attributes=False) in dumps for n in added_nodes) and
                           [n.name for n in added_nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] == missing)
            segments = [ast.get_source_segment(public[tid]["prompt"], next(n for n in allowed
                        if ast.dump(n, include_attributes=False) == ast.dump(a, include_attributes=False))) for a in added_nodes]
            checks.require("exact_public_bytes_and_original_suffix/" + cid,
                           ctx == "\n\n".join(segments) + "\n\n" and after["solution"] == ctx + before["solution"])
            ast.parse(after["solution"])
            changes.append({"task_id": tid, "candidate_id": cid, "batch_id": after["batch_id"], "rank": after["rank"],
                            "original_solution_sha256": before["solution_sha256"], "assembled_solution_sha256": after["solution_sha256"],
                            "public_prompt_sha256": prov["public_prompt_sha256"], "context_sha256": prov["context_sha256"],
                            "added_helper_names": "|".join(missing)})
        else:
            checks.require("no_unneeded_source_change/" + cid, after["solution"] == before["solution"] and prov["context_source"] == "")
        bind = {k: after[k] for k in ("task_id", "candidate_id", "solution_sha256", "test_sha256", "runner_sha256")}
        checks.require("assembled_job_decision_evidence_binding/" + cid,
                       after["job_hash"] == after["job_digest"] == digest(bind) and after["decision_id"] == "verify:" + digest(bind)
                       and after["used_evidence_ids"] == ["job:" + digest(bind)])
    checks.require("11_sources_four_batches", len(changes) == 11 and {r["batch_id"] for r in changes} == BATCHES)
    return changes


def policy_check(folder, checks):
    s, ev = read(folder / "run_summary.json"), lines(folder / "client_events.jsonl")
    inp = read(folder / "input_batch.json")
    tasks = inp["task_ids"]
    used = {t: 0 for t in tasks}
    passed, cursor, pending, selected, stopped = set(), 0, None, None, False
    for i, e in enumerate(ev):
        tag = s["run_id"] + "/" + str(i)
        if e["event"] == "issued":
            checks.require("new_choice_without_pending_or_drain/" + tag, pending is None and not stopped)
            start = 0 if s["policy"] == "depth_first" else cursor
            candidates = [(start + offset) % len(tasks) for offset in range(len(tasks))]
            index = next((j for j in candidates if tasks[j] not in passed and used[tasks[j]] < 4), None)
            expected = None if index is None else (tasks[index], inp["candidate_ids"][tasks[index]][used[tasks[index]]])
            checks.require("feedback_dependent_policy_choice/" + tag, expected == (e["task_id"], e["candidate_id"]))
            if s["policy"] == "round_robin":
                cursor = (index + 1) % len(tasks)
            selected = e
        elif e["event"] == "armed":
            checks.require("arm_current_choice_after_observed_deadline_guard/" + tag,
                           selected is not None and selected["decision_id"] == e["decision_id"] and
                           selected["elapsed_s"] < s["deadline_seconds"] and pending is None and not stopped)
            used[e["task_id"]] += 1
            pending = e["permit_id"]
        elif e["event"] == "reconciled":
            checks.require("reconciliation_of_current_pending/" + tag, pending == e["permit_id"])
            pending = None
            if e["result"]["status"] == "pass":
                passed.add(e["task_id"])
        elif e["event"] == "primary_stopped":
            stopped = True
    checks.require("all_armed_feedback_reconciled/" + s["run_id"], pending is None)


def extract(folder, module):
    """Same column definitions as original S9 analyzer, recomputed from raw logs/DB."""
    s = read(folder / "run_summary.json")
    ev, se = lines(folder / "client_events.jsonl"), lines(folder / "service_runs/service_events.jsonl")
    start, deadline = s["started_at_counter_ns"], s["deadline_seconds"]
    elapsed = lambda e: (e["perf_counter_ns"] - start) / 1e9
    rec = {e["effect_id"]: e for e in ev if e["event"] == "reconciled"}
    arms = {e["operation_id"]: e for e in ev if e["event"] == "armed"}
    commits = {e["idempotency_key"]: e for e in se if e["event"] == "result_commit_return"}
    timely = {e["task_id"] for e in rec.values() if e["result"]["status"] == "pass" and e["phase"] == "primary" and elapsed(e) <= deadline}
    eventual = {e["task_id"] for e in rec.values() if e["result"]["status"] == "pass"}
    durable, counts, jobrows = set(), collections.Counter(), []
    with module.connection(folder / "sink.sqlite") as db:
        results = module.table(db, "job_results")
    for result in sorted(results, key=lambda r: r["effect_id"]):
        raw = json.loads(result["result_json"])
        if digest(raw) != result["result_hash"]:
            raise ValueError("Raw result hash mismatch: " + str(folder))
        key, feedback = result["idempotency_key"], rec[result["effect_id"]]
        commit = elapsed(commits[key])
        if raw["status"] == "pass" and commit <= deadline:
            durable.add(raw["task_id"])
        counts[raw["status"]] += 1
        j = {k: s[k] for k in ("run_id", "batch_id", "arm", "policy", "condition")}
        j.update(task_id=raw["task_id"], candidate_id=raw["candidate_id"], operation_id=key,
                 effect_id=result["effect_id"], status=raw["status"], result_hash=result["result_hash"],
                 solution_sha256=raw["solution_sha256"], test_sha256=raw["test_sha256"], runner_sha256=raw["runner_sha256"],
                 launch_ordinal=arms[key]["launch_ordinal"], actual_starts=raw["actual_starts"],
                 child_cpu_seconds=raw["cpu_seconds"], suite_wall_seconds=raw["wall_seconds"],
                 launcher_wall_seconds=raw["launcher_wall_seconds"],
                 launcher_start_elapsed_s=(raw["host_launch_perf_counter_ns"] - start) / 1e9,
                 result_commit_elapsed_s=commit, reconciled_elapsed_s=elapsed(feedback), reconciled_phase=feedback["phase"],
                 response_dropped=any(e["event"] == "response_drop" and e["idempotency_key"] == key for e in se))
        jobrows.append(j)
    stop, final = read(folder / "stop_observed_snapshot.json"), read(folder / "final_client_snapshot.json")
    r = {k: s[k] for k in ("run_id", "batch_id", "arm", "policy", "condition")}
    r.update(eligible_tasks=len(s["eligible_task_ids"]), timely_tasks=len(timely), durable_pass_tasks_by_deadline=len(durable),
             eventual_pass_tasks=len(eventual), jobs=len(results), actual_starts=sum(j["actual_starts"] for j in jobrows),
             pass_jobs=counts["pass"], fail_jobs=counts["fail"], timeout_jobs=counts["timeout"], http_posts=s["http_posts"],
             response_drops=sum(e["event"] == "response_drop" for e in se), cache_hits=sum(e["event"] == "cache_hit" for e in se),
             primary_retries=sum(e["event"] == "retry" and e["phase"] == "primary" for e in ev),
             drain_retries=sum(e["event"] == "retry" and e["phase"] == "drain" for e in ev),
             **{k: sum(j[k] for j in jobrows) for k in ("child_cpu_seconds", "suite_wall_seconds", "launcher_wall_seconds")},
             observed_stop_elapsed_s=next(e["elapsed_s"] for e in ev if e["event"] == "primary_stopped"),
             all_feedback_complete_elapsed_s=next(e["elapsed_s"] for e in ev if e["event"] == "trajectory_complete"),
             stop_held=stop["reserved"], stop_committed=stop["committed"], final_held=final["reserved"], final_committed=final["committed"],
             late_host_launches=sum(j["launcher_start_elapsed_s"] > deadline for j in jobrows),
             denied_decisions=sum(e["event"] == "issued" and e["route"] != "alert" for e in ev),
             timely_task_ids="|".join(sorted(timely)), eventual_task_ids="|".join(sorted(eventual)))
    return r, jobrows


def aggregate(rows):
    groups = []
    for condition in ("normal", "response_loss"):
        for policy in ("depth_first", "round_robin"):
            for arm in ("ecrc", "ordinary"):
                subset = [r for r in rows if (r["condition"], r["policy"], r["arm"]) == (condition, policy, arm)]
                g = dict(condition=condition, policy=policy, arm=arm, batches=len(subset))
                g.update({k: sum(r[k] for r in subset) for k in SUMS})
                g.update(timely_percent=100 * g["timely_tasks"] / g["eligible_tasks"],
                         median_batch_complete_s=statistics.median(r["all_feedback_complete_elapsed_s"] for r in subset),
                         max_stop_held=max(r["stop_held"] for r in subset), max_final_held=max(r["final_held"] for r in subset))
                groups.append(g)
    pairs = []
    for contrast, match, varying, left, right in [
            ("round_robin_minus_depth_first", ["arm", "condition"], "policy", "round_robin", "depth_first"),
            ("ecrc_minus_ordinary", ["policy", "condition"], "arm", "ecrc", "ordinary"),
            ("response_loss_minus_normal", ["arm", "policy"], "condition", "response_loss", "normal")]:
        for l in (r for r in rows if r[varying] == left):
            matches = [r for r in rows if r["batch_id"] == l["batch_id"] and r[varying] == right and all(r[k] == l[k] for k in match)]
            if len(matches) != 1:
                raise ValueError("Paired cell missing or ambiguous")
            r = matches[0]
            p = dict(contrast=contrast, batch_id=l["batch_id"], arm=l["arm"] if "arm" in match else "paired",
                     policy=l["policy"] if "policy" in match else "paired", condition=l["condition"] if "condition" in match else "paired")
            p.update({k + "_difference": l[k] - r[k] for k in ("timely_tasks", "eventual_pass_tasks", "jobs", "child_cpu_seconds", "launcher_wall_seconds")})
            pairs.append(p)
    return groups, pairs


def run(out):
    c = Checks()
    spec = importlib.util.spec_from_file_location("s9_correction_readonly_raw_auditor", ADAPTER)
    rawmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rawmod)
    adapter = rawmod.Adapter(SimpleNamespace(output_dir=out / "raw", pilot_root=ORIGINAL, catalog=None))
    oldplan, plan = read(ORIGINAL / "evaluation_v1/GRID_PLAN.json"), read(HERE / "GRID_PLAN.json")
    fp, oldfp = read(HERE / "FINAL_PROTOCOL.json"), read(ORIGINAL / "FINAL_PROTOCOL.json")
    completed = read(HERE / "runs/SUMMARY.json")
    c.require("all32_completed_no_technical_failures", completed["observed_runs"] == completed["planned_runs"] == 32 and
              completed["technical_failures"] == 0 and completed["automatic_reruns"] == 0)
    expected = [{**cell, "original_run_index": i, "original_run_id": f"r{i:03d}"}
                for i, cell in enumerate(oldplan["cells"], 1) if cell["batch"] in BATCHES]
    c.require("exact_fixed_32_grid_subsequence", plan["cells"] == expected and len(expected) == 32 and len(oldplan["cells"]) == 144)
    newids = {cell["original_run_id"] for cell in expected}
    retained = {f"r{i:03d}" for i in range(1, 145)} - newids
    c.require("exact_112_retained", set(plan["retained_original_runs"]) == retained and len(retained) == 112)
    c.require("exact_new_run_directory_inventory", {p.parent.name for p in (HERE / "runs").rglob("run_summary.json")} == newids)
    c.require("new_plan_and_outcome_order", read(HERE / "runs/GRID_PLAN.json")["cells"] == expected and
              [r["run_id"] for r in lines(HERE / "runs/outcomes.jsonl")] == [r["original_run_id"] for r in expected])
    c.require("same_runtime_and_execution_settings", fp["source_hashes"] == oldfp["source_hashes"] and
              all(fp[k] == oldfp[k] for k in ("budget", "deadline_seconds", "recovery_backoff_seconds", "arms", "policies", "conditions", "runner_sha256")))
    source_bindings = {str(Path(__file__).resolve()): sha(__file__), str(ADAPTER): sha(ADAPTER), str(OLD_ANALYZER): sha(OLD_ANALYZER),
                       str(HERE / "FINAL_PROTOCOL.json"): sha(HERE / "FINAL_PROTOCOL.json"), str(PRIOR_AUDIT): sha(PRIOR_AUDIT)}
    for base, bindings, prefix in [(WORKSPACE, read(HERE / "PRESERVATION_BASELINE.json"), "protected_original"),
                                  (ORIGINAL, fp["source_hashes"], "original_runtime"),
                                  (HERE, fp["correction_source_hashes"], "frozen_correction"),
                                  (WORKSPACE, read(PRIOR_AUDIT)["raw_input_hashes"], "original_saved_run")]:
        for name, expected_hash in bindings.items():
            path = base / name.replace("\\", "/")
            observed_hash = sha(path)
            c.require(prefix + "/" + name, observed_hash == expected_hash)
            source_bindings[str(path.resolve())] = observed_hash
    adapter.catalog()  # Independently reconstructs original selection without archived labels.
    oldcat, newcat = adapter.cat, read(HERE / "corrected_catalog.json")
    changes = independent_assembly(oldcat, newcat, c)
    c.require("new_catalog_frozen_hash", sha(HERE / "corrected_catalog.json") == fp["catalog_sha256"] == read(HERE / "ASSEMBLY_AUDIT.json")["corrected_catalog_sha256"])
    by_version = {}
    for version, cat, path in [("original_v1", oldcat, ORIGINAL / "bound_catalog.json"),
                               ("context_corrected_v1", newcat, HERE / "corrected_catalog.json")]:
        by_version[version] = (cat, sha(path), {(j["task_id"], j["candidate_id"]): j for j in cat["jobs"]},
                               {j["decision_id"]: j for j in cat["jobs"]})
    rows, jobs, index, oldrows, contextjobs, inputs = [], [], [], [], [], collections.defaultdict(set)
    changed_ids = {r["candidate_id"] for r in changes}
    for i, cell in enumerate(oldplan["cells"], 1):
        rid = f"r{i:03d}"
        oldfolder = ORIGINAL / "evaluation_v1" / rid
        original_row, _ = extract(oldfolder, rawmod)
        oldrows.append(original_row)
        version = "context_corrected_v1" if rid in newids else "original_v1"
        folder = HERE / "runs" / rid if rid in newids else oldfolder
        s = read(folder / "run_summary.json")
        c.require("run_factor_and_protocol_identity/" + rid, s["run_id"] == rid and
                  s["batch_id"] == cell["batch"] and all(s[k] == cell[k] for k in ("condition", "policy", "arm")) and
                  s["formal_protocol_sha256"] == sha((HERE if rid in newids else ORIGINAL) / "FINAL_PROTOCOL.json"))
        adapter.cat, adapter.cat_hash, adapter.by_candidate, adapter.by_decision = by_version[version]
        adapter.run(folder / "run_summary.json")
        policy_check(folder, c)
        r, jj = extract(folder, rawmod)
        rows.append(r)
        jobs.extend(jj)
        inputs[r["batch_id"]].add(s["inputs_hash"])
        mapping = dict(original_run_index=i, run_id=rid, batch_id=r["batch_id"], condition=r["condition"], policy=r["policy"], arm=r["arm"],
                       context_version=version, selected_path=str(folder.resolve()), original_path=str(oldfolder.resolve()),
                       catalog_sha256=adapter.cat_hash, formal_protocol_sha256=s["formal_protocol_sha256"], inputs_hash=s["inputs_hash"])
        for name in ("run_summary.json", "input_batch.json", "client_events.jsonl", "client.sqlite", "sink.sqlite", "service_runs/service_events.jsonl"):
            mapping[name.replace("/", "_").replace(".", "_") + "_sha256"] = sha(folder / name)
        index.append(mapping)
        for e in lines(folder / "client_events.jsonl"):
            if e["event"] == "reconciled" and e["candidate_id"] in changed_ids:
                job = adapter.by_candidate[(e["task_id"], e["candidate_id"])]
                contextjobs.append(dict(run_id=rid, context_version=version, task_id=e["task_id"], candidate_id=e["candidate_id"],
                                        status=e["result"]["status"], error_type=e["result"].get("error_type"),
                                        original_solution_sha256=job.get("context_correction", {}).get("original_solution_sha256", job["solution_sha256"]),
                                        executed_solution_sha256=job["solution_sha256"], result_hash=e["result_hash"]))
        if i % 24 == 0:
            print(json.dumps({"audited_runs": i, "planned": 144, "jobs": len(jobs)}), flush=True)
    c.require("paired_initial_inputs_identical_within_batch", len(inputs) == 18 and all(len(x) == 1 for x in inputs.values()))
    c.require("all_144_runs_and144_unique_tasks", len(rows) == 144 and len({t for r in adapter.runs for t in r["eligible_task_ids"]}) == 144)
    failures = [x for x in adapter.checks if not x["pass"]]
    write(out / "raw/RAW_AUDIT.json", {"status": "FAIL" if failures else "PASS", "checks": len(adapter.checks), "failures": failures,
                                     "runs": adapter.run_counts, "source_files_sha256": adapter.sources})
    write(out / "raw/raw_checks.json", adapter.checks)
    csvwrite(out / "raw/raw_run_counts.csv", adapter.run_counts)
    c.require("all_independent_raw_checks_pass", not failures, failures[:5])
    cells, pairs = aggregate(rows)
    oldcells, oldpairs = aggregate(oldrows)
    c.require("8_cells18_batches144_denominator", len(cells) == 8 and all(g["batches"] == 18 and g["eligible_tasks"] == 144 for g in cells))
    c.require("216_fixed_paired_contrasts", len(pairs) == 216 and
              set(collections.Counter(p["contrast"] for p in pairs).values()) == {72})
    differences = []
    for new, old in zip(rows, oldrows):
        d = {k: new[k] for k in ("run_id", "batch_id", "arm", "policy", "condition")}
        d["context_version"] = "context_corrected_v1" if new["run_id"] in newids else "original_v1_retained"
        d.update({k + "_old": old[k] for k in SUMS})
        d.update({k + "_corrected": new[k] for k in SUMS})
        d.update({k + "_difference": new[k] - old[k] for k in SUMS})
        differences.append(d)
        if new["run_id"] in retained:
            c.require("retained_numerical_row_identical/" + new["run_id"], new == old)
    totals = {k: sum(r[k] for r in rows) for k in SUMS}
    original_totals = {k: sum(r[k] for r in oldrows) for k in SUMS}
    counts = adapter.run_counts
    duplicate_effects = sum(r["effects"] - r["armed_jobs"] for r in counts)
    c.require("no_duplicate_effect_and_one_actual_start_per_job", duplicate_effects == 0 and
              all(r["effects"] == r["actual_starts"] == r["armed_jobs"] == r["receipts"] == r["durable_results"] for r in counts))
    c.require("drops_equal_cached_recovery", totals["response_drops"] == totals["cache_hits"] and
              all(r["response_drops"] == r["cache_hits"] for r in rows))
    for name, data in [("S9_runs.csv", rows), ("S9_jobs.csv", jobs), ("S9_cells.csv", cells), ("S9_paired_batches.csv", pairs),
                       ("cell_summary.csv", cells), ("paired_batches.csv", pairs), ("merged_run_index.csv", index),
                       ("old_new_run_differences.csv", differences), ("original_cell_summary.csv", oldcells),
                       ("original_paired_batches.csv", oldpairs), ("assembly_source_mapping.csv", changes), ("context_job_outcomes.csv", contextjobs)]:
        csvwrite(out / name, data)
    summary = {"status": "PASS", "planned_runs": 144, "observed_runs": len(rows), "retained_original_runs": 112,
               "replacement_runs": 32, "unique_eligible_tasks": 144, "paired_contrasts": len(pairs),
               "original_protocol_sha256": sha(ORIGINAL / "FINAL_PROTOCOL.json"), "protocol_sha256": sha(HERE / "FINAL_PROTOCOL.json"),
               "source_grid_sha256": sha(HERE / "GRID_PLAN.json"), "totals": totals, "original_totals": original_totals,
               "corrected_minus_original": {k: totals[k] - original_totals[k] for k in SUMS},
               "max_final_held": max(r["final_held"] for r in rows), "max_stop_held": max(r["stop_held"] for r in rows),
               "duplicate_effects": duplicate_effects, "assembly_changed_candidates": len(changes), "assembly_changed_tasks": 4,
               "launcher_wall_median_seconds": statistics.median(j["launcher_wall_seconds"] for j in jobs),
               "launcher_wall_max_seconds": max(j["launcher_wall_seconds"] for j in jobs), "cells": cells,
               "audit": {"raw_checks": len(adapter.checks), "raw_failures": len(failures), "additional_checks": len(c.rows),
                         "source_bindings": len(source_bindings)},
               "scope": "Descriptive mixed-version correction: 112 original plus all32 predetermined replacement trajectories; 144 previously exposed tasks, not1152 independent tasks.",
               "limits": ["Finite official-suite acceptance is not general program correctness.",
                          "New and retained timings come from different sessions; old/new differences do not isolate a causal context effect.",
                          "The observed-before-arm admission guard is not a strict physical start deadline.",
                          "No new model generation, hidden-outcome selection, candidate execution or experiment was performed by this analyzer."]}
    write(out / "corrected_summary.json", summary)
    write(out / "S9_SUMMARY.json", summary)
    write(out / "checks.json", c.rows)
    write(out / "SOURCE_MANIFEST.json", {**source_bindings, **adapter.sources})
    # Re-read hashes after analysis to demonstrate that read-only auditing did not alter inputs.
    changed_after = [name for name, expected_hash in {**source_bindings, **adapter.sources}.items() if sha(name) != expected_hash]
    if changed_after:
        raise ValueError("Inputs changed during analysis: " + repr(changed_after))
    write(out / "COMPLETION.json", {"status": "PASS", "input_hashes_unchanged_after": True,
                                   "outputs": {p.name: sha(p) for p in out.iterdir() if p.is_file()}})
    print(json.dumps({k: summary[k] for k in ("status", "observed_runs", "paired_contrasts", "totals", "max_final_held", "duplicate_effects")}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "analysis_v1", help="New output directory; refuses overwrite.")
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error("Do not use optimized Python: retained auditor guards must remain active.")
    args.out.mkdir(parents=True, exist_ok=False)
    try:
        run(args.out.resolve())
    except Exception as exc:
        write(args.out / "ANALYSIS_FAILURE.json", {"status": "FAIL_OR_INCOMPLETE", "error_type": type(exc).__name__,
                                                  "message": str(exc), "traceback": traceback.format_exc()})
        raise


if __name__ == "__main__":
    main()
