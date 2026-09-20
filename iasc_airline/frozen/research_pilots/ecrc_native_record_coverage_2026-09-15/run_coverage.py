"""Fixed native-record comparison with unchanged actors and no benchmark gold."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / "ecrc_component_ablation_dev_2026-09-15"
sys.path.insert(0, str(OLD))
import run_ablation as inherited

ARMS = ["direct_native_dispatch", "qualification_ecrc", "existing_rules_only",
        "without_claim_evidence_requirement"]

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()

def manifest():
    old = read(OLD / "review/prerun_01/FREEZE.json")
    for name, expected in old["sources"].items():
        if sha(Path(name)) != expected:
            raise RuntimeError("Prior frozen source changed: " + name)
    for name, expected in old["vendor_sources"].items():
        if sha(inherited.VENDOR / name) != expected:
            raise RuntimeError("Pinned native source changed: " + name)
    selection = read(ROOT / "COHORT_SELECTION.json")
    sources = dict(old["sources"])
    for name, expected in selection["source_files"].items():
        if sha(Path(name)) != expected:
            raise RuntimeError("Cohort source changed: " + name)
        sources[name] = expected
    for path in [*ROOT.glob("*.py"), ROOT / "PROTOCOL.md", ROOT / "REQUESTS.json", ROOT / "COHORT_SELECTION.json",
                 OLD / "review/postrun_01/audit_outputs.py"]:
        sources[str(path.resolve())] = sha(path)
    return sources, old["vendor_sources"]

def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    isolation = inherited.setup()
    from prepare_cohort import verify
    verify()
    requests = read(ROOT / "REQUESTS.json")
    cases = requests["cases"]
    keys = [(c["request"]["user_id"], c["request"]["cancellation"]["reason"]) for c in cases]
    users = {u for u, _ in keys}
    if len(keys) != len(set(keys)) or set(keys) != {(u, r) for u in users for r in ("health", "other", "unspecified")}:
        raise RuntimeError("Cohort does not contain exactly three reason settings per account")
    if any(c.get("task_id") is not None for c in cases):
        raise RuntimeError("Constructed requests may not receive original task IDs")
    if len({c["case_id"] for c in cases}) != len(cases):
        raise RuntimeError("Duplicate case identity")
    sources, vendor = manifest()
    suite = unittest.defaultTestLoader.loadTestsFromNames(["test_ablation_gates", "test_selector_adapter",
                "test_case_evaluation", "test_scope_gate", "test_independent_audit"])
    with (out / "QA_LOG.txt").open("x", encoding="utf-8") as stream:
        qa = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    write(out / "QA.json", {"tests": qa.testsRun, "passed": qa.wasSuccessful(), "failures": len(qa.failures),
                           "errors": len(qa.errors), "scope": "Synthetic QA; no native request comparison"})
    if not qa.wasSuccessful() or manifest() != (sources, vendor):
        raise RuntimeError("QA or source-integrity failure")
    freeze = {"recorded_at": datetime.now(timezone.utc).isoformat(), "sources": sources, "vendor_sources": vendor,
              "requests": requests, "cohort": read(ROOT / "COHORT_SELECTION.json"),
              "arms": ARMS, "python": sys.version, "isolation": isolation,
              "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}}
    write(out / "FREEZE.json", freeze)
    for path in [*ROOT.glob("*.py"), ROOT / "PROTOCOL.md", ROOT / "REQUESTS.json", ROOT / "COHORT_SELECTION.json"]:
        (out / path.name).write_bytes(path.read_bytes())
    print(json.dumps({"frozen": True, "accounts": len(users), "requests": len(cases), "cells": len(cases)*len(ARMS),
                      "qa_tests": qa.testsRun, "sources": len(sources), "vendor_sources": len(vendor)}), flush=True)

def replay_native(calls, before, actor_hash):
    from tau2.domains.airline.environment import get_environment
    from tau2.data_model.message import ToolCall, ToolMessage
    from native_evaluation import _response_key
    replay = get_environment()
    initial_equal = replay.tools.db.model_dump(mode="json") == before
    if not initial_equal:
        raise RuntimeError("Replay starts from a different native database")
    for index, entry in enumerate(calls):
        call = ToolCall.model_validate({k: entry[k] for k in ("id", "name", "arguments", "requestor")})
        expected = ToolMessage.model_validate(entry["response"])
        actual = replay.get_response(call)
        if _response_key(actual) != _response_key(expected):
            raise RuntimeError("Native response replay mismatch at call " + str(index))
    actual_hash = replay.get_db_hash()
    if actual_hash != actor_hash:
        raise RuntimeError("Native final state replay mismatch")
    return {"schema_version": "generic_native_replay_no_task_gold_v1", "native_orchestrator_run": False,
            "native_full_task_evaluation_applicable": False, "official_task_score": None,
            "recorded_tool_call_count": len(calls), "all_recorded_tool_responses_reproduced": True,
            "actor_final_db_match_verified": True, "initial_db_match_verified": initial_equal,
            "actor_final_db_hash": actor_hash, "replay_final_db_hash": actual_hash, "model_calls": 0}

def one(case, arm, out, before_expected, before_file):
    """Same fact/confirmation/dispatch sequence as the frozen prior runner."""
    out.mkdir(parents=True, exist_ok=False)
    from tau2.domains.airline.environment import get_environment
    from tau2.data_model.message import AssistantMessage, UserMessage, ToolCall
    from tau2.environment.toolkit import get_tool_types
    from selector_adapter import resolve
    env = get_environment()
    before = env.tools.db.model_dump(mode="json")
    if before != before_expected:
        raise RuntimeError("Cell native initial state differs from shared original DB")
    write(out / "BEFORE_DB_REFERENCE.json", {"path": "../BEFORE_DB.json", "file_sha256": sha(before_file),
                                             "canonical_sha256": digest(before), "fresh_native_initial_state_verified": True})
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
        for action in proposal["actions"]:
            if action["name"] != "cancel_reservation" or action["arguments"]["reservation_id"] not in resolution["selected_ids"]:
                raise ValueError("Confirmation outside resolved selection")
        messages.extend([AssistantMessage(role="assistant", content=json.dumps(proposal, ensure_ascii=False)).model_dump(mode="json"),
                         UserMessage(role="user", content="yes").model_dump(mode="json")])
        confirmations.append({"proposal": deepcopy(proposal), "response": "yes"})
        return "yes"

    gate = None
    if arm not in ("direct_native_dispatch", "existing_rules_only"):
        from ablation_gates import make_gate
        gate = make_gate("full" if arm == "qualification_ecrc" else arm, out / "permission.sqlite")
        write(out / "GATE_CONFIGURATION.json", {"arm": arm, "class": type(gate).__name__,
                                                "core_class": type(gate.core).__name__, "policies": gate.policies})
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
    messages.append(AssistantMessage(role="assistant", content=json.dumps({"status": actor["status"], "module_only": True})).model_dump(mode="json"))
    after = env.tools.db.model_dump(mode="json")
    with gzip.open(out / "AFTER_DB.json.gz", "wt", encoding="utf-8", compresslevel=1) as stream:
        json.dump(after, stream, ensure_ascii=False)
    for name, value in (("ACTOR_RESULT", actor), ("TOOL_CALLS", calls), ("MESSAGES", messages),
                        ("CONFIRMATIONS", confirmations), ("RESOLUTION", resolution)):
        write(out / (name + ".json"), value)
    if gate:
        write(out / "PERMISSION_STATE.json", gate.snapshot())
    from case_evaluation import evaluate
    assessed = evaluate(case["request"], messages, before, after, resolution["status"] if resolution else "unresolved")
    write(out / "CASE_EVALUATION.json", assessed)
    native = replay_native(calls, before, env.get_db_hash())
    write(out / "NATIVE_REPLAY.json", native)
    result = {"case_id": case["case_id"], "task_id": None, "arm": arm, "execution_error": error,
              "native_calls": len(calls), "native_writes": sum(c["tool_type"] == "write" for c in calls),
              "native_errors": sum(bool(c["response"]["error"]) for c in calls), "elapsed_local_seconds": elapsed,
              "case_evaluation": assessed, "native_evaluation": native, "evaluation_returncode": 0,
              "model_calls": 0, "model_api_cost_usd": 0, "full_task_success_established": False,
              "native_receipt_registered": False}
    write(out / "RESULT.json", result)
    return result, digest(actor.get("candidates")), digest(resolution), digest(after)

def batch(out, freeze_path):
    isolation = inherited.setup()
    freeze = read(freeze_path)
    if manifest() != (freeze["sources"], freeze["vendor_sources"]):
        raise RuntimeError("Frozen source mismatch")
    out.mkdir(parents=True, exist_ok=False)
    write(out / "FREEZE.json", freeze)
    from tau2.domains.airline.environment import get_environment
    baseline_env = get_environment()
    before = baseline_env.tools.db.model_dump(mode="json")
    before_file = out / "BEFORE_DB.json"
    write(before_file, before)
    rows, comparisons = [], []
    for index, case in enumerate(freeze["requests"]["cases"]):
        sequence = ARMS[index % len(ARMS):] + ARMS[:index % len(ARMS)]
        hashes = {}
        for arm in sequence:
            folder = out / (case["case_id"] + "__" + arm)
            try:
                result, candidates, resolution, after = one(case, arm, folder, before, before_file)
                rows.append(result)
                hashes[arm] = {"candidates": candidates, "resolution": resolution, "after": after}
            except Exception as exc:
                failed = {"case_id": case["case_id"], "task_id": None, "arm": arm,
                          "cell_error": {"type": type(exc).__name__, "message": str(exc)}, "execution_error": "cell_incomplete",
                          "native_calls": None, "native_writes": None, "evaluation_returncode": None,
                          "case_evaluation": None, "native_evaluation": None}
                folder.mkdir(parents=True, exist_ok=True)
                write(folder / "FAILED_RESULT.json", failed)
                rows.append(failed)
        complete = set(hashes) == set(ARMS)
        comparison = {"case_id": case["case_id"], "all_cells_complete": complete,
                      "same_resolution": complete and len({v["resolution"] for v in hashes.values()}) == 1,
                      "same_candidate_proposals": complete and len({hashes[a]["candidates"] for a in ARMS if a != "existing_rules_only"}) == 1,
                      "rules_full_final_db_equal": complete and hashes["qualification_ecrc"]["after"] == hashes["existing_rules_only"]["after"],
                      "claim_off_raw_final_db_equal": complete and hashes["direct_native_dispatch"]["after"] == hashes["without_claim_evidence_requirement"]["after"],
                      "observable_hashes": hashes}
        comparisons.append(comparison)
        write(out / "PROGRESS.json", {"completed_cells": len(rows), "declared_cells": len(freeze["requests"]["cases"])*len(ARMS),
                                      "last_case": case["case_id"]})
        print(json.dumps({"case": index+1, "total_cases": len(freeze["requests"]["cases"]),
                          "completed_cells": len(rows), "complete": complete}), flush=True)
    unchanged = manifest() == (freeze["sources"], freeze["vendor_sources"])
    technical_failure = any(r["execution_error"] or r["evaluation_returncode"] or r.get("native_errors", 0)
                            or not (r.get("case_evaluation") or {}).get("metrics_valid", False) for r in rows)
    matching_failure = any(not all(c[k] for k in ("all_cells_complete", "same_resolution", "same_candidate_proposals")) for c in comparisons)
    summary = {"stage": "controlled_native_record_coverage", "rows": rows, "comparisons": comparisons,
               "sources_unchanged": unchanged, "technical_failure": technical_failure, "matching_failure": matching_failure,
               "model_calls": 0, "model_api_cost_usd": 0, "paper_changed": False,
               "isolation": isolation, "full_benchmark_run": False}
    write(out / "SUMMARY.json", summary)
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
