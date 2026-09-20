"""Freeze and run a versioned 32-cell context correction through original S9.

This entry point imports the original workflow read-only; no original study
source, catalog, protocol, output, or result is overwritten.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback

sys.dont_write_bytecode = True
from context_catalog import HERE, ORIGINAL, BATCHES, canonical, file_sha, read, write_new

LOCAL_FILES = ("context_catalog.py", "run_correction.py", "test_context.py", "PROTOCOL.md",
               "corrected_catalog.json", "ASSEMBLY_AUDIT.json", "GRID_PLAN.json", "PRESERVATION_BASELINE.json")


def preserved():
    baseline = read(HERE / "PRESERVATION_BASELINE.json")
    changed = [name for name, expected in baseline.items() if file_sha(HERE.parents[1] / name) != expected]
    if changed:
        raise ValueError("Original protected source/input changed: " + repr(changed))
    return {"files_checked": len(baseline), "changed": changed}


def validate_inputs():
    preserved()
    audit = read(HERE / "ASSEMBLY_AUDIT.json")
    if audit["corrected_catalog_sha256"] != file_sha(HERE / "corrected_catalog.json"):
        raise ValueError("Corrected catalog hash differs")
    plan = read(HERE / "GRID_PLAN.json")
    original = read(ORIGINAL / "evaluation_v1/GRID_PLAN.json")
    expected = [{**cell, "original_run_index": i, "original_run_id": f"r{i:03d}"}
                for i, cell in enumerate(original["cells"], 1) if cell["batch"] in BATCHES]
    if plan["cells"] != expected or len(expected) != 32 or plan["planned_runs"] != 32:
        raise ValueError("Replacement cells or original-index order differ")
    if len(plan["retained_original_runs"]) != 112:
        raise ValueError("Retained original run count differs")
    return plan


def freeze():
    if (HERE / "runs").exists():
        raise FileExistsError("Cannot freeze after execution started")
    validate_inputs()
    protocol = read(ORIGINAL / "FINAL_PROTOCOL.json")
    historical = {k: protocol[k] for k in ("planned_runs", "stopping", "order", "statistical_reporting",
                                           "pre_freeze_development_checks")}
    # The frozen original run_one supports a catalog-specific protocol, and
    # checks these original source hashes against its unchanged own HERE.
    protocol.update(frozen=True, frozen_at_utc=datetime.now(timezone.utc).isoformat(),
                    study_type="post-study public-context input correction; versioned replacement of four batches",
                    correction_version="public-helper-context-v1",
                    original_protocol_sha256=file_sha(ORIGINAL / "FINAL_PROTOCOL.json"),
                    original_catalog_sha256=protocol["catalog_sha256"],
                    catalog_sha256=file_sha(HERE / "corrected_catalog.json"),
                    workload_catalog_sha256=file_sha(HERE / "corrected_catalog.json"),
                    evaluation_batch_ids=BATCHES, budget=16, deadline_seconds=5, recovery_backoff_seconds=1.0,
                    corrected_planned_trajectories=32, retained_original_trajectories=112,
                    planned_runs=32,
                    stopping="Run the fixed 32-cell correction once, preserve all failures, no automatic reruns or outcome-based exclusions.",
                    order="Exact subsequence of the original 144-cell GRID_PLAN, retaining original indices and factor order.",
                    statistical_reporting="All 32 replacement cells retained; combine with explicitly versioned 112 original cells for descriptive corrected totals. No inferential or timing-causality claim.",
                    no_recalibration=True, no_formal_warmup=True,
                    correction_source_hashes={name: file_sha(HERE / name) for name in LOCAL_FILES},
                    result_composition="All 8 cells from each affected batch are replaced; 112 untouched original cells remain explicitly versioned. No selection by replacement outcome.",
                    timing_limit="Replacement and retained trajectories are measured in different sessions. Cross-version totals are descriptive and do not identify the causal effect of context restoration alone.")
    # Derived original run-count metadata is explicitly preserved as historical,
    # rather than accidentally presenting a copied 144-cell denominator as new.
    protocol["original_protocol_metadata"] = historical
    protocol["pre_freeze_development_checks"] = {"scope": "Original historical checks retained under original_protocol_metadata; new synthetic context QA separately recorded."}
    write_new(HERE / "FINAL_PROTOCOL.json", protocol)
    print(canonical({"frozen": True, "protocol_sha256": file_sha(HERE / "FINAL_PROTOCOL.json"), "planned_runs": 32}))


def verified_protocol():
    if sys.flags.optimize:
        raise ValueError("Python optimization is forbidden; original assertion guards must remain active")
    plan = validate_inputs()
    fp = read(HERE / "FINAL_PROTOCOL.json")
    if fp.get("frozen") is not True or fp.get("correction_version") != "public-helper-context-v1":
        raise ValueError("Frozen correction protocol required")
    if (fp["budget"], fp["deadline_seconds"], fp["recovery_backoff_seconds"]) != (16, 5, 1.0):
        raise ValueError("Original execution controls changed")
    if set(fp["correction_source_hashes"]) != set(LOCAL_FILES):
        raise ValueError("Incomplete correction source binding")
    for name, expected in fp["correction_source_hashes"].items():
        if file_sha(HERE / name) != expected:
            raise ValueError("Correction frozen file changed: " + name)
    if fp["source_hashes"] != read(ORIGINAL / "FINAL_PROTOCOL.json")["source_hashes"]:
        raise ValueError("Original runtime source binding changed")
    return fp, plan


def load_original_workflow():
    sys.path.insert(0, str(ORIGINAL))
    spec = importlib.util.spec_from_file_location("s9_original_workflow_context_correction", ORIGINAL / "run_workflow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.HERE.resolve() != ORIGINAL.resolve():
        raise ValueError("Imported workflow root differs")
    return module.run_one


def run():
    fp, plan = verified_protocol()
    run_one = load_original_workflow()
    destination = HERE / "runs"
    destination.mkdir(exist_ok=False)
    write_new(destination / "GRID_PLAN.json", {**plan, "protocol_sha256": file_sha(HERE / "FINAL_PROTOCOL.json"),
                                              "catalog_sha256": file_sha(HERE / "corrected_catalog.json")})
    rows, started = [], time.time()
    for ordinal, cell in enumerate(plan["cells"], 1):
        # Short names retain original scientific identity and avoid MAX_PATH.
        folder = destination / cell["original_run_id"]
        try:
            row = run_one(catalog_path=HERE / "corrected_catalog.json", batch_id=cell["batch"],
                          arm=cell["arm"], policy=cell["policy"], condition=cell["condition"],
                          budget=16, deadline=5, backoff=1.0, out=folder,
                          formal_protocol=HERE / "FINAL_PROTOCOL.json")
        except BaseException as exc:
            folder.mkdir(exist_ok=True)
            row = {"run_id": cell["original_run_id"], "batch_id": cell["batch"], "arm": cell["arm"],
                   "policy": cell["policy"], "condition": cell["condition"], "passed_technical": False,
                   "failure": {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}}
            # Original run_one can already record setup_failure.json. Preserve it.
            write_new(folder / "correction_failure.json", row)
        row = {**row, "context_version": "public-helper-context-v1", "original_run_index": cell["original_run_index"]}
        rows.append(row)
        with (destination / "outcomes.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(canonical(row) + "\n")
        progress = {"finished": ordinal, "planned": 32,
                    "failed_technical": sum(not value["passed_technical"] for value in rows),
                    "last": {k: row.get(k) for k in ("run_id", "n_timely_pass", "passed_technical")}}
        print(canonical(progress), flush=True)
    summary = {"planned_runs": 32, "observed_runs": len(rows), "all_runs_retained": len(rows) == 32,
               "technical_failures": sum(not value["passed_technical"] for value in rows),
               "elapsed_wall_seconds": time.time() - started, "model_calls": 0, "automatic_reruns": 0,
               "retained_original_runs": 112, "preservation": preserved()}
    write_new(destination / "SUMMARY.json", summary)
    print(canonical(summary), flush=True)
    return int(summary["technical_failures"] > 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.freeze == args.run:
        parser.error("Specify exactly one of --freeze or --run")
    if args.freeze:
        freeze()
    else:
        raise SystemExit(run())
