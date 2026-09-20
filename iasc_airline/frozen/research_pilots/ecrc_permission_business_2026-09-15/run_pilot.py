"""Freeze, test and run a bounded native business permission component pilot."""
from __future__ import annotations

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
PREVIOUS = ROOT.parent / "ecrc_airline_pilot_2026-09-15"
VENDOR = PREVIOUS / "vendor/tau2-bench"
PAPER = ROOT.parents[1] / "output/iasc_overleaf"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup():
    sys.path.append(str(PREVIOUS))
    from bootstrap import install
    isolation = install()
    from loguru import logger
    logger.remove()
    return isolation


def manifest():
    from ecrc_adapter import core_files
    paths = list(ROOT.glob("*.py")) + [ROOT / "PLAN.json", ROOT / "REQUESTS.json"]
    paths += [Path(p) for p in core_files()]
    paths += [PREVIOUS / "bootstrap.py", PREVIOUS / "native_evaluation.py"]
    paths += [PAPER / "main.tex", *sorted((PAPER / "content").glob("*.tex"))]
    vendor_hashes = read(PREVIOUS / "review/prerun_01/VENDOR_HASHES.json")
    for name, expected in vendor_hashes.items():
        if sha(VENDOR / name) != expected:
            raise RuntimeError("Pinned native file changed: " + name)
    return {str(p.resolve()): sha(p) for p in sorted(set(paths))}, vendor_hashes


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    isolation = setup()
    before, vendor = manifest()
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        "test_ecrc_adapter", "test_independent_audit", "test_ordinary_business",
    ])
    with (out / "QA_LOG.txt").open("x", encoding="utf-8") as handle:
        result = unittest.TextTestRunner(stream=handle, verbosity=2).run(suite)
    after, vendor_after = manifest()
    qa = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
          "skipped": len(result.skipped), "passed": result.wasSuccessful(),
          "sources_unchanged": before == after and vendor == vendor_after,
          "scope": "synthetic component QA only, not native task episodes", "isolation": isolation}
    write(out / "QA.json", qa)
    if not qa["passed"] or not qa["sources_unchanged"]:
        print(json.dumps(qa))
        raise SystemExit(2)
    tasks = read(VENDOR / "data/tau2/domains/airline/tasks.json")
    entries = read(ROOT / "REQUESTS.json")
    for case in entries["cases"]:
        original = next(t for t in tasks if t["id"] == case["task_id"])
        if original.get("initial_state") is not None:
            raise RuntimeError("This component pilot supports default initial state only")
    freeze = {"recorded_at": datetime.now(timezone.utc).isoformat(), "sources": before,
              "vendor_sources": vendor, "plan": read(ROOT / "PLAN.json"), "requests": entries,
              "python": sys.version,
              "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
              "qa": qa, "model_calls": 0}
    write(out / "FREEZE.json", freeze)
    for path in ROOT.glob("*.py"):
        (out / path.name).write_bytes(path.read_bytes())
    print(json.dumps({"frozen": True, "tests": qa["tests"], "source_files": len(before), "native_files": len(vendor)}))


def one(case, arm, condition, out):
    out.mkdir(parents=True, exist_ok=False)
    from tau2.domains.airline.environment import get_environment
    from tau2.data_model.message import AssistantMessage, UserMessage, ToolCall
    from tau2.environment.toolkit import get_tool_types
    from ordinary_business import run
    from bridge import envelopes
    from independent_audit import audit

    env = get_environment()
    before = env.tools.db.model_dump(mode="json")
    write(out / "BEFORE_DB.json", before)
    write(out / "CASE.json", case)
    messages = [UserMessage(role="user", content=json.dumps(case["request"], ensure_ascii=False)).model_dump(mode="json")]
    calls = []
    confirmations = []
    permissions = []
    types = get_tool_types(env.tools)
    gate = None
    if arm == "ecrc":
        from ecrc_adapter import PermissionGate
        gate = PermissionGate(out / "permission.sqlite")

    def caller(name, **arguments):
        if len(calls) >= 128:
            raise RuntimeError("Declared native-call cap reached")
        call = ToolCall(id=f"call-{len(calls)+1}", name=name, arguments=deepcopy(arguments), requestor="assistant")
        messages.append(AssistantMessage(role="assistant", tool_calls=[call]).model_dump(mode="json"))
        response = env.get_response(call)
        payload = response.model_dump(mode="json")
        messages.append(payload)
        calls.append({**call.model_dump(mode="json"), "response": payload,
                      "tool_type": types[name].value})
        write(out / "MESSAGES.json", messages)
        write(out / "TOOL_CALLS.json", calls)
        if response.error:
            raise RuntimeError(response.content)
        try:
            return json.loads(response.content)
        except (TypeError, json.JSONDecodeError):
            return response.content

    def confirm(proposal):
        if proposal["user_id"] != case["request"]["user_id"]:
            raise ValueError("Wrong confirmation user")
        messages.append(AssistantMessage(role="assistant", content=json.dumps(proposal, ensure_ascii=False)).model_dump(mode="json"))
        messages.append(UserMessage(role="user", content="yes").model_dump(mode="json"))
        confirmations.append({"proposal": deepcopy(proposal), "response": "yes"})
        return "yes"

    def authorize(action, context, business_basis):
        args, diagnostic = envelopes(action, context, condition)
        started = time.perf_counter()
        result = gate.authorize(**args)
        if result["allowed"]:
            gate.assert_action_binding(result, action)
        seconds = time.perf_counter() - started
        permissions.append({"input": args, "result": result, "diagnostic": diagnostic, "gate_seconds": seconds})
        return result

    started = time.perf_counter()
    error = None
    try:
        actor = run(deepcopy(case["request"]), caller, confirm, authorize=authorize if gate else None)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        actor = {"status": "execution_error", "error": error, "actions": [], "reported_verified_actions": 0}
    seconds = time.perf_counter() - started
    messages.append(AssistantMessage(role="assistant", content=json.dumps({"status": actor["status"], "verified_actions": actor["reported_verified_actions"], "unresolved": actor.get("unresolved", [])}, ensure_ascii=False)).model_dump(mode="json"))
    after = env.tools.db.model_dump(mode="json")
    for name, value in (("AFTER_DB", after), ("ACTOR_RESULT", actor), ("MESSAGES", messages),
                        ("TOOL_CALLS", calls), ("CONFIRMATIONS", confirmations), ("PERMISSIONS", permissions)):
        write(out / (name + ".json"), value)
    if gate:
        write(out / "PERMISSION_STATE.json", gate.snapshot())
    write(out / "EVALUATION_INPUT.json", {"task_id": case["task_id"], "actions": calls, "messages": messages,
                                         "termination_reason": "agent_stop", "actor_final_db_hash": env.get_db_hash()})
    evaluation = subprocess.run([sys.executable, "-B", str(PREVIOUS / "native_evaluation.py"),
                                 "--input", str(out / "EVALUATION_INPUT.json"),
                                 "--output", str(out / "NATIVE_EVALUATION.json")],
                                capture_output=True, encoding="utf-8", timeout=60)
    (out / "evaluation.stdout.txt").write_text(evaluation.stdout, encoding="utf-8")
    (out / "evaluation.stderr.txt").write_text(evaluation.stderr, encoding="utf-8")
    independent = audit(case["request"], messages, before, after)
    write(out / "INDEPENDENT_AUDIT.json", independent)
    native = read(out / "NATIVE_EVALUATION.json") if evaluation.returncode == 0 else None
    writes = [c for c in calls if c["tool_type"] == "write"]
    diagnostic_expected = None if condition == "normal" else bool(permissions) and all(
        not p["result"]["allowed"] and not p["result"]["armed"] for p in permissions) and not writes
    result = {
        "case_id": case["case_id"], "task_id": case["task_id"], "arm": arm, "condition": condition,
        "native_full_goal_in_scope": case["native_full_goal_in_scope"],
        "actor_status": actor["status"], "execution_error": error,
        "native_call_count": len(calls), "native_write_count": len(writes),
        "native_errors": sum(c["response"]["error"] for c in calls),
        "observed_local_seconds": seconds, "gate_seconds": sum(p["gate_seconds"] for p in permissions),
        "permission_proposals": len(permissions), "allowed_permissions": sum(p["result"]["allowed"] for p in permissions),
        "diagnostic_expected_denial_met": diagnostic_expected,
        "native_evaluation_returncode": evaluation.returncode, "native_evaluation": native,
        "independent_audit": independent, "model_calls": 0, "model_api_cost_usd": 0,
        "official_dialogue_rollout": False, "lifecycle_recovery_tested": False,
        "native_effect_receipt_registered_in_ecrc": False,
        "note": "Metadata probes preserve native business facts; reduced completion is retained, not counted as business improvement.",
    }
    write(out / "RESULT.json", result)
    print(json.dumps({"case": case["case_id"], "arm": arm, "condition": condition, "writes": len(writes),
                      "native_score": native["adapter_composed_native_reward"] if native else None,
                      "business_complete": independent["business_actions_safe_and_complete"],
                      "metadata_probe_pass": diagnostic_expected, "execution_error": error}), flush=True)
    return result


def batch(out, freeze_path):
    isolation = setup()
    freeze = read(freeze_path)
    current, vendor = manifest()
    if current != freeze["sources"] or vendor != freeze["vendor_sources"]:
        raise RuntimeError("Sources changed since successful QA/freeze")
    out.mkdir(parents=True, exist_ok=False)
    write(out / "FREEZE.json", freeze)
    rows = []
    cases = freeze["requests"]["cases"]
    for index, case in enumerate(cases):
        arms = freeze["plan"]["normal_arms"] if index % 2 == 0 else list(reversed(freeze["plan"]["normal_arms"]))
        for arm in arms:
            rows.append(one(case, arm, "normal", out / (case["case_id"] + "__" + arm)))
    diagnostic = next(c for c in cases if c["case_id"] == freeze["plan"]["diagnostic_case_id"])
    for condition in freeze["plan"]["diagnostic_conditions"]:
        rows.append(one(diagnostic, "ecrc", condition, out / (diagnostic["case_id"] + "__" + condition)))
    after, vendor_after = manifest()
    compact = [{k: v for k, v in row.items() if k not in {"native_evaluation", "independent_audit"}} |
               {"native_score": row["native_evaluation"]["adapter_composed_native_reward"] if row["native_evaluation"] else None,
                "business_complete": row["independent_audit"]["business_actions_safe_and_complete"],
                "policy_subset_safe": row["independent_audit"]["all_checked_requirements_pass"],
                "expected_business_actions": row["independent_audit"]["expected_action_count"],
                "audit_violations": row["independent_audit"]["violations"],
                "missing_actions": row["independent_audit"]["missing_expected_actions"],
                "unsupported_scope": row["independent_audit"]["unsupported_or_unresolved_scope"]} for row in rows]
    summary = {"stage": "bounded_component_development_complete", "rows": compact,
               "sources_unchanged": current == after and vendor == vendor_after,
               "model_calls": 0, "model_api_cost_usd": 0, "paper_changed": False, "isolation": isolation,
               "ordinary_business_superiority_established": False,
               "valid_effect_recovery_claim": False}
    write(out / "SUMMARY.json", summary)
    print(json.dumps({"completed_cells": len(rows), "sources_unchanged": summary["sources_unchanged"]}), flush=True)
    if not summary["sources_unchanged"] or any(r["execution_error"] or r["native_evaluation_returncode"] for r in rows):
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
