"""Fixed synthetic boundary comparison; unchanged actors/checker/core/evaluator."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import importlib.metadata
from pathlib import Path
import sys
import time
import unittest
from boundary_common import (ROOT, ARMS, inherited, canonical, digest, fixture_environment,
                             manifest, read, sha, within, write)
import json


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    isolation = inherited.setup()
    from prepare_boundary import verify
    verification = verify()
    requests = read(ROOT / "REQUESTS.json")
    index = read(ROOT / "FIXTURE_INDEX.json")
    sources, vendor = manifest()
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        "test_boundary_plumbing", "test_ablation_gates", "test_selector_adapter",
        "test_case_evaluation", "test_scope_gate", "test_independent_audit"])
    with (out / "QA_LOG.txt").open("x", encoding="utf-8") as stream:
        qa = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    write(out / "QA.json", {"tests": qa.testsRun, "passed": qa.wasSuccessful(),
          "failures": len(qa.failures), "errors": len(qa.errors), "fixture_verification": verification,
          "scope": "Synthetic/mechanical QA only; no comparative native cells", "comparison_executed": False})
    if not qa.wasSuccessful() or manifest() != (sources, vendor):
        raise RuntimeError("QA or source-integrity failure")
    freeze = {"recorded_at": datetime.now(timezone.utc).isoformat(), "sources": sources,
              "vendor_sources": vendor, "requests": requests, "arms": ARMS,
              "fixtures": index["fixtures"], "base_db": index["base_db"],
              "fixture_index": index, "case_specs": read(ROOT / "CASE_SPECS.json"),
              "expected_boundaries": read(ROOT / "EXPECTED_BOUNDARIES.json"),
              "expected_boundaries_are_not_metric_or_technical_pass_inputs": True,
              "python": sys.version, "isolation": isolation,
              "study": "explicitly_modified_synthetic_boundaries_not_official_benchmark",
              "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}}
    write(out / "FREEZE.json", freeze)
    for path in [*ROOT.glob("*.py"), ROOT / "PROTOCOL.md", ROOT / "README.md",
                 ROOT / "REQUESTS.json", ROOT / "CASE_SPECS.json", ROOT / "EXPECTED_BOUNDARIES.json",
                 ROOT / "FIXTURE_INDEX.json"]:
        (out / path.name).write_bytes(path.read_bytes())
    print(json.dumps({"frozen": True, "cases": len(requests["cases"]), "cells": len(requests["cases"])*len(ARMS),
                      "qa_tests": qa.testsRun, "sources": len(sources), "vendor_sources": len(vendor),
                      "comparison_executed": False}), flush=True)


def replay_native(calls, before, actor_hash):
    from tau2.data_model.message import ToolCall, ToolMessage
    from native_evaluation import _response_key
    replay = fixture_environment(before)
    initial_equal = replay.tools.db.model_dump(mode="json") == before
    if not initial_equal:
        raise RuntimeError("Replay starts from a different synthetic database")
    responses = []
    for index, entry in enumerate(calls):
        call = ToolCall.model_validate({k: entry[k] for k in ("id", "name", "arguments", "requestor")})
        expected = ToolMessage.model_validate(entry["response"])
        actual = replay.get_response(call)
        responses.append(actual.model_dump(mode="json"))
        if _response_key(actual) != _response_key(expected):
            raise RuntimeError("Native response replay mismatch at call " + str(index))
    actual_hash = replay.get_db_hash()
    if actual_hash != actor_hash:
        raise RuntimeError("Native final state replay mismatch")
    return {"schema_version": "synthetic_fixture_generic_native_replay_v1", "native_orchestrator_run": False,
            "native_full_task_evaluation_applicable": False, "official_task_score": None,
            "recorded_tool_call_count": len(calls), "all_recorded_tool_responses_reproduced": True,
            "actor_final_db_match_verified": True, "initial_db_match_verified": initial_equal,
            "actor_final_db_hash": actor_hash, "replay_final_db_hash": actual_hash, "model_calls": 0,
            "replay_responses_canonical_sha256": digest(responses), "replay_responses_count": len(responses)}, responses


def one(case, arm, out, before_expected, before_file):
    """Same fact/confirmation/dispatch sequence as the frozen prior runner."""
    out.mkdir(parents=True, exist_ok=False)
    from tau2.data_model.message import AssistantMessage, UserMessage, ToolCall
    from tau2.environment.toolkit import get_tool_types
    from selector_adapter import resolve
    env = fixture_environment(before_expected)
    before = env.tools.db.model_dump(mode="json")
    if before != before_expected:
        raise RuntimeError("Cell initial state differs from the explicit synthetic fixture")
    write(out / "BEFORE_DB_REFERENCE.json", {"path": "../" + before_file.relative_to(out.parent).as_posix(), "file_sha256": sha(before_file),
                                             "canonical_sha256": digest(before), "fresh_native_initial_state_verified": True,
                                             "explicitly_modified_synthetic_fixture": True})
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
    native, replay_responses = replay_native(calls, before, env.get_db_hash())
    write(out / "NATIVE_REPLAY_RESPONSES.json", replay_responses)
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
    if freeze["arms"] != ARMS:
        raise RuntimeError("Frozen arm order mismatch")
    # Copy exact frozen fixture bytes; no fixture generation during comparisons.
    relative_files = [freeze["base_db"]["path"]]
    for entry in freeze["fixtures"]:
        relative_files.extend([entry["before_path"], entry["patch_path"]])
    for relative in relative_files:
        source, target = within(ROOT, relative), within(out, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    fixtures = {entry["case_id"]: entry for entry in freeze["fixtures"]}
    if set(fixtures) != {c["case_id"] for c in freeze["requests"]["cases"]}:
        raise RuntimeError("Frozen fixture and case grid mismatch")
    rows, comparisons = [], []
    for index, case in enumerate(freeze["requests"]["cases"]):
        entry = fixtures[case["case_id"]]
        before_file = within(out, entry["before_path"])
        before = read(before_file)
        if sha(before_file) != entry["before_file_sha256"] or digest(before) != entry["before_canonical_sha256"]:
            raise RuntimeError("Copied per-case BEFORE binding failure")
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
    summary = {"stage": "controlled_synthetic_airline_boundaries", "rows": rows, "comparisons": comparisons,
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
