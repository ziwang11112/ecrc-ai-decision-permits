"""Frozen 11-request, three-condition native cancellation-stage development."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent
SCOPE = ROOT.parent / "ecrc_action_scope_dev_2026-09-15"
PRIOR = ROOT.parent / "ecrc_permission_business_2026-09-15"
NATIVE = ROOT.parent / "ecrc_airline_pilot_2026-09-15"
VENDOR = NATIVE / "vendor/tau2-bench"
PAPER = ROOT.parents[1] / "output/iasc_overleaf"
ARMS = ["direct_native_dispatch", "qualification_ecrc", "existing_rules_only"]
sys.path.extend([str(SCOPE), str(PRIOR), str(NATIVE)])


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup():
    from bootstrap import install
    isolation = install()
    from loguru import logger
    logger.remove()
    return isolation


def manifest():
    from scope_gate import core_files
    paths = list(ROOT.glob("*.py")) + [ROOT / "PROTOCOL.md", ROOT / "REQUESTS.json"]
    paths += [Path(p) for p in core_files()]
    paths += [SCOPE / "workflow.py", SCOPE / "test_scope_gate.py"]
    paths += [PRIOR / "independent_audit.py", PRIOR / "test_independent_audit.py"]
    paths += [NATIVE / "bootstrap.py", NATIVE / "native_evaluation.py"]
    paths += [PAPER / "main.tex", *sorted((PAPER / "content").glob("*.tex"))]
    vendor = read(NATIVE / "review/prerun_01/VENDOR_HASHES.json")
    for name, expected in vendor.items():
        if sha(VENDOR / name) != expected:
            raise RuntimeError("Pinned vendor source changed: " + name)
    return {str(p.resolve()): sha(p) for p in sorted(set(paths))}, vendor


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    isolation = setup()
    requests = read(ROOT / "REQUESTS.json")
    train = read(VENDOR / "data/tau2/domains/airline/split_tasks.json")["train"]
    included = [c["task_id"] for c in requests["cases"]]
    excluded = [c["task_id"] for c in requests["excluded_original_train"]]
    if len(included) != 11 or len(train) != 30 or len(set(included + excluded)) != 30 or set(included + excluded) != set(train):
        raise RuntimeError("Incomplete or duplicate train population accounting")
    scenarios = [{"id": t["id"], "user_scenario": t["user_scenario"], "initial_state": t["initial_state"]}
                 for t in read(VENDOR / "data/tau2/domains/airline/tasks.json") if t["id"] in train]
    if any(t["initial_state"] is not None for t in scenarios):
        raise RuntimeError("This frozen stage runner requires default initial state")
    sources, vendor = manifest()
    previous = read(SCOPE / "review/prerun_01/FREEZE.json")["sources"]
    preserved = {str(p.resolve()): sha(p) == previous[str(p.resolve())] for p in
                 [SCOPE / "workflow.py", SCOPE / "scope_gate.py", PRIOR / "ordinary_business.py", PRIOR / "ecrc_adapter.py", PRIOR / "independent_audit.py"]}
    if not all(preserved.values()):
        raise RuntimeError("A frozen actor/core/independent auditor changed")
    suite = unittest.defaultTestLoader.loadTestsFromNames(["test_selector_adapter", "test_case_evaluation", "test_scope_gate", "test_independent_audit"])
    with (out / "QA_LOG.txt").open("x", encoding="utf-8") as stream:
        qa = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    write(out / "QA.json", {"tests": qa.testsRun, "passed": qa.wasSuccessful(), "failures": len(qa.failures), "errors": len(qa.errors), "scope": "synthetic QA, not native episodes"})
    if not qa.wasSuccessful() or manifest() != (sources, vendor):
        raise RuntimeError("QA or source-integrity failure; no comparison executed")
    freeze = {"recorded_at": datetime.now(timezone.utc).isoformat(), "sources": sources, "vendor_sources": vendor,
              "requests": requests, "source_scenarios": scenarios, "arms": ARMS, "python": sys.version,
              "preserved_prior_components": preserved, "isolation": isolation,
              "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}}
    write(out / "FREEZE.json", freeze)
    for p in ROOT.glob("*.py"):
        (out / p.name).write_bytes(p.read_bytes())
    print(json.dumps({"frozen": True, "cases": len(included), "cells": len(included)*3, "qa_tests": qa.testsRun, "sources": len(sources), "vendor_sources": len(vendor)}), flush=True)


def one(case, arm, out):
    out.mkdir(parents=True, exist_ok=False)
    from tau2.domains.airline.environment import get_environment
    from tau2.data_model.message import AssistantMessage, UserMessage, ToolCall
    from tau2.environment.toolkit import get_tool_types
    from selector_adapter import resolve
    env = get_environment()
    before = env.tools.db.model_dump(mode="json")
    write(out / "BEFORE_DB.json", before)
    write(out / "CASE.json", case)
    messages = [UserMessage(role="user", content=json.dumps(case["request"], ensure_ascii=False)).model_dump(mode="json")]
    calls, confirmations = [], []
    resolution = None
    types = get_tool_types(env.tools)

    def caller(name, **arguments):
        if len(calls) >= 128:
            raise RuntimeError("Declared 128 native-call cap reached")
        call = ToolCall(id=f"call-{len(calls)+1}", name=name, arguments=deepcopy(arguments), requestor="assistant")
        messages.append(AssistantMessage(role="assistant", tool_calls=[call]).model_dump(mode="json"))
        response = env.get_response(call)
        payload = response.model_dump(mode="json")
        messages.append(payload)
        calls.append({**call.model_dump(mode="json"), "response": payload, "tool_type": types[name].value})
        write(out / "TOOL_CALLS.json", calls)
        write(out / "MESSAGES.json", messages)
        if response.error:
            raise RuntimeError(response.content)
        try:
            return json.loads(response.content)
        except (TypeError, json.JSONDecodeError):
            return response.content

    def confirm(proposal):
        if resolution is None or resolution["status"] != "resolved" or proposal["user_id"] != case["request"]["user_id"]:
            raise ValueError("No resolved request for confirmation")
        for a in proposal["actions"]:
            if a["name"] != "cancel_reservation" or a["arguments"]["reservation_id"] not in resolution["selected_ids"]:
                raise ValueError("Confirmation outside resolved selection")
        messages.extend([AssistantMessage(role="assistant", content=json.dumps(proposal, ensure_ascii=False)).model_dump(mode="json"),
                         UserMessage(role="user", content="yes").model_dump(mode="json")])
        confirmations.append({"proposal": deepcopy(proposal), "response": "yes"})
        return "yes"

    gate = None
    if arm == "qualification_ecrc":
        from scope_gate import ScopeGate
        gate = ScopeGate(out / "permission.sqlite")
    started, error = time.perf_counter(), None
    try:
        resolution = resolve(deepcopy(case["request"]), caller)
        write(out / "RESOLUTION.json", resolution)
        if resolution["status"] != "resolved":
            actor = {"status": "unresolved_selection", "reason": resolution["reason"], "actions": [], "candidates": []}
        elif arm == "existing_rules_only":
            from ordinary_business import run
            actor = run(deepcopy(resolution["resolved_request"]), caller, confirm)
        else:
            from workflow import run
            actor = run(deepcopy(resolution["resolved_request"]), caller, confirm, gate=gate)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        actor = {"status": "execution_error", "error": error}
    elapsed = time.perf_counter() - started
    messages.append(AssistantMessage(role="assistant", content=json.dumps({"status": actor["status"], "module_only": True}, ensure_ascii=False)).model_dump(mode="json"))
    after = env.tools.db.model_dump(mode="json")
    for name, value in (("AFTER_DB", after), ("ACTOR_RESULT", actor), ("TOOL_CALLS", calls), ("MESSAGES", messages), ("CONFIRMATIONS", confirmations), ("RESOLUTION", resolution)):
        write(out / (name + ".json"), value)
    if gate:
        write(out / "PERMISSION_STATE.json", gate.snapshot())
    # The independent evaluator sees the original selector, never only the
    # actor's derived IDs. Full benchmark criteria remain evaluator-private.
    from case_evaluation import evaluate
    assessed = evaluate(case["request"], messages, before, after, resolution["status"] if resolution else "unresolved")
    write(out / "CASE_EVALUATION.json", assessed)
    write(out / "EVALUATION_INPUT.json", {"task_id": case["task_id"], "actions": calls, "messages": messages,
                                         "termination_reason": "agent_stop", "actor_final_db_hash": env.get_db_hash()})
    evaluation = subprocess.run([sys.executable, "-B", str(NATIVE / "native_evaluation.py"), "--input", str(out / "EVALUATION_INPUT.json"),
                                 "--output", str(out / "NATIVE_EVALUATION.json")], capture_output=True, encoding="utf-8", timeout=60)
    (out / "evaluation.stdout.txt").write_text(evaluation.stdout, encoding="utf-8")
    (out / "evaluation.stderr.txt").write_text(evaluation.stderr, encoding="utf-8")
    native = read(out / "NATIVE_EVALUATION.json") if evaluation.returncode == 0 else None
    result = {"case_id": case["case_id"], "task_id": case["task_id"], "arm": arm, "execution_error": error,
              "native_calls": len(calls), "native_writes": sum(c["tool_type"] == "write" for c in calls),
              "native_errors": sum(bool(c["response"]["error"]) for c in calls), "elapsed_local_seconds": elapsed,
              "case_evaluation": assessed, "native_evaluation": native, "evaluation_returncode": evaluation.returncode,
              "model_calls": 0, "model_api_cost_usd": 0, "full_task_success_established": False, "native_receipt_registered": False}
    write(out / "RESULT.json", result)
    print(json.dumps({"case": case["task_id"], "arm": arm, "writes": result["native_writes"], "resolution": resolution["status"] if resolution else None,
                      "native_component_score": native["adapter_composed_native_reward"] if native else None, "execution_error": error}), flush=True)
    return result


def batch(out, freeze_path):
    isolation = setup()
    freeze = read(freeze_path)
    if manifest() != (freeze["sources"], freeze["vendor_sources"]):
        raise RuntimeError("Frozen source mismatch")
    out.mkdir(parents=True, exist_ok=False)
    write(out / "FREEZE.json", freeze)
    rows, comparisons = [], []
    for index, case in enumerate(freeze["requests"]["cases"]):
        arms = freeze["arms"][index % 3:] + freeze["arms"][:index % 3]
        for arm in arms:
            folder = out / (case["case_id"] + "__" + arm)
            try:
                rows.append(one(case, arm, folder))
            except Exception as exc:
                failed = {"case_id": case["case_id"], "task_id": case["task_id"], "arm": arm,
                          "cell_error": {"type": type(exc).__name__, "message": str(exc)}, "execution_error": "cell_incomplete",
                          "native_calls": None, "native_writes": None, "evaluation_returncode": None, "case_evaluation": None, "native_evaluation": None}
                folder.mkdir(parents=True, exist_ok=True)
                write(folder / "FAILED_RESULT.json", failed)
                rows.append(failed)
                print(json.dumps(failed), flush=True)
        folders = [out / (case["case_id"] + "__" + arm) for arm in freeze["arms"]]
        try:
            resolutions = [read(p / "RESOLUTION.json") for p in folders]
            actors = [read(p / "ACTOR_RESULT.json") for p in folders]
            befores = [read(p / "BEFORE_DB.json") for p in folders]
            comparisons.append({"case_id": case["case_id"], "same_resolution": all(r == resolutions[0] for r in resolutions),
                                "same_initial_db": all(b == befores[0] for b in befores),
                                "same_direct_ecrc_candidates": actors[0].get("candidates") == actors[1].get("candidates"),
                                "rules_ecrc_final_db_equal": read(folders[1] / "AFTER_DB.json") == read(folders[2] / "AFTER_DB.json")})
        except Exception as exc:
            comparisons.append({"case_id": case["case_id"], "comparison_error": str(exc)})
        write(out / "PROGRESS.json", {"completed_cells": len(rows), "declared_cells": 33, "last_case": case["case_id"]})
    unchanged = manifest() == (freeze["sources"], freeze["vendor_sources"])
    summary = {"stage": "exposed_initial_cancellation_stage_development", "rows": rows, "comparisons": comparisons,
               "sources_unchanged": unchanged, "model_calls": 0, "model_api_cost_usd": 0, "paper_changed": False,
               "isolation": isolation, "full_benchmark_run": False}
    write(out / "SUMMARY.json", summary)
    technical_failure = any(r["execution_error"] or r["evaluation_returncode"] or r.get("native_errors", 0) for r in rows)
    matching_failure = any(c.get("comparison_error") or not all(c.get(k) for k in ("same_resolution", "same_initial_db", "same_direct_ecrc_candidates")) for c in comparisons)
    if not unchanged or technical_failure or matching_failure:
        raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "run"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.out.resolve())
    else:
        if args.freeze is None:
            parser.error("run requires --freeze")
        batch(args.out.resolve(), args.freeze.resolve())
