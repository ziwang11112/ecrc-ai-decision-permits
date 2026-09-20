"""Freeze and execute one declared action-scope development comparison."""
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
PRIOR = ROOT.parent / "ecrc_permission_business_2026-09-15"
NATIVE = ROOT.parent / "ecrc_airline_pilot_2026-09-15"
VENDOR = NATIVE / "vendor/tau2-bench"
PAPER = ROOT.parents[1] / "output/iasc_overleaf"
ARMS = ["direct_native_dispatch", "qualification_ecrc", "existing_rules_only"]
sys.path.extend([str(PRIOR), str(NATIVE)])


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
    from ecrc_adapter import core_files
    paths = list(ROOT.glob("*.py")) + [ROOT / "PROTOCOL.md"]
    paths += [PRIOR / name for name in ("REQUESTS.json", "ordinary_business.py", "ecrc_adapter.py", "independent_audit.py", "test_independent_audit.py")]
    paths += [NATIVE / "bootstrap.py", NATIVE / "native_evaluation.py"]
    paths += [Path(p) for p in core_files()]
    paths += [PAPER / "main.tex", *sorted((PAPER / "content").glob("*.tex"))]
    vendor = read(NATIVE / "review/prerun_01/VENDOR_HASHES.json")
    for name, expected in vendor.items():
        if sha(VENDOR / name) != expected:
            raise RuntimeError("Pinned source changed: " + name)
    return {str(p.resolve()): sha(p) for p in sorted(set(paths))}, vendor


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    isolation = setup()
    sources, vendor = manifest()
    prior_freeze = read(PRIOR / "review/prerun_01/FREEZE.json")
    preserved = {str(PRIOR / name): sha(PRIOR / name) == prior_freeze["sources"][str((PRIOR / name).resolve())]
                 for name in ("ordinary_business.py", "ecrc_adapter.py", "independent_audit.py", "REQUESTS.json")}
    if not all(preserved.values()):
        raise RuntimeError("Previous frozen workflow or evaluator changed")
    suite = unittest.defaultTestLoader.loadTestsFromNames(["test_scope_gate", "test_independent_audit"])
    with (out / "QA_LOG.txt").open("x", encoding="utf-8") as stream:
        qa = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    write(out / "QA.json", {"tests": qa.testsRun, "passed": qa.wasSuccessful(), "failures": len(qa.failures), "errors": len(qa.errors), "scope": "synthetic QA, not native episodes"})
    if not qa.wasSuccessful() or manifest() != (sources, vendor):
        raise RuntimeError("QA or immutability failed; no native comparison executed")
    case = next(c for c in read(PRIOR / "REQUESTS.json")["cases"] if c["case_id"] == "train_7_direct_cancellation_module")
    freeze = {"recorded_at": datetime.now(timezone.utc).isoformat(), "sources": sources, "vendor_sources": vendor,
              "case": case, "arms": ARMS, "python": sys.version, "isolation": isolation,
              "prior_frozen_dependencies_unchanged": preserved,
              "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}}
    write(out / "FREEZE.json", freeze)
    for p in ROOT.glob("*.py"):
        (out / p.name).write_bytes(p.read_bytes())
    print(json.dumps({"frozen": True, "qa_tests": qa.testsRun, "source_files": len(sources), "vendor_files": len(vendor)}))


def one(case, arm, out):
    out.mkdir(parents=True, exist_ok=False)
    from tau2.domains.airline.environment import get_environment
    from tau2.data_model.message import AssistantMessage, UserMessage, ToolCall
    from tau2.environment.toolkit import get_tool_types
    from independent_audit import audit
    env = get_environment()
    before = env.tools.db.model_dump(mode="json")
    write(out / "BEFORE_DB.json", before)
    write(out / "CASE.json", case)
    messages = [UserMessage(role="user", content=json.dumps(case["request"], ensure_ascii=False)).model_dump(mode="json")]
    calls, confirmations = [], []
    types = get_tool_types(env.tools)

    def caller(name, **arguments):
        if len(calls) >= 128:
            raise RuntimeError("Native call cap reached")
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
        request = case["request"]
        if proposal["user_id"] != request["user_id"]:
            raise ValueError("Confirmation account mismatch")
        for a in proposal["actions"]:
            if a["name"] != "cancel_reservation" or a["arguments"]["reservation_id"] not in request["cancellation"]["selector"]["ids"]:
                raise ValueError("Scripted confirmation outside original user request")
        messages.extend([AssistantMessage(role="assistant", content=json.dumps(proposal, ensure_ascii=False)).model_dump(mode="json"),
                         UserMessage(role="user", content="yes").model_dump(mode="json")])
        confirmations.append({"proposal": deepcopy(proposal), "response": "yes"})
        return "yes"

    gate = None
    if arm == "qualification_ecrc":
        from scope_gate import ScopeGate
        gate = ScopeGate(out / "permission.sqlite")
    started = time.perf_counter()
    error = None
    try:
        if arm == "existing_rules_only":
            from ordinary_business import run
            actor = run(deepcopy(case["request"]), caller, confirm)
        else:
            from workflow import run
            actor = run(deepcopy(case["request"]), caller, confirm, gate=gate)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        actor = {"status": "execution_error", "error": error}
    elapsed = time.perf_counter() - started
    messages.append(AssistantMessage(role="assistant", content=json.dumps({"status": actor["status"], "module_only": True}, ensure_ascii=False)).model_dump(mode="json"))
    after = env.tools.db.model_dump(mode="json")
    for name, value in (("AFTER_DB", after), ("ACTOR_RESULT", actor), ("TOOL_CALLS", calls), ("MESSAGES", messages), ("CONFIRMATIONS", confirmations)):
        write(out / (name + ".json"), value)
    if gate:
        write(out / "PERMISSION_STATE.json", gate.snapshot())
    independent = audit(case["request"], messages, before, after)
    write(out / "INDEPENDENT_AUDIT.json", independent)
    write(out / "EVALUATION_INPUT.json", {"task_id": case["task_id"], "actions": calls, "messages": messages,
                                         "termination_reason": "agent_stop", "actor_final_db_hash": env.get_db_hash()})
    evaluation = subprocess.run([sys.executable, "-B", str(NATIVE / "native_evaluation.py"), "--input", str(out / "EVALUATION_INPUT.json"),
                                 "--output", str(out / "NATIVE_EVALUATION.json")], capture_output=True, encoding="utf-8", timeout=60)
    (out / "evaluation.stdout.txt").write_text(evaluation.stdout, encoding="utf-8")
    (out / "evaluation.stderr.txt").write_text(evaluation.stderr, encoding="utf-8")
    native = read(out / "NATIVE_EVALUATION.json") if evaluation.returncode == 0 else None
    result = {"arm": arm, "execution_error": error, "native_calls": len(calls), "native_writes": sum(c["tool_type"] == "write" for c in calls),
              "native_errors": sum(bool(c["response"]["error"]) for c in calls), "elapsed_local_seconds": elapsed,
              "audit": independent, "native_evaluation": native, "evaluation_returncode": evaluation.returncode,
              "model_calls": 0, "model_api_cost_usd": 0, "full_task_success": False, "native_receipt_registered": False}
    write(out / "RESULT.json", result)
    print(json.dumps({"arm": arm, "native_writes": result["native_writes"], "module_safe_complete": independent["business_actions_safe_and_complete"],
                      "native_full_task_score": native["adapter_composed_native_reward"] if native else None, "execution_error": error}), flush=True)
    return result


def batch(out, freeze_path):
    isolation = setup()
    freeze = read(freeze_path)
    if manifest() != (freeze["sources"], freeze["vendor_sources"]):
        raise RuntimeError("Frozen source mismatch")
    out.mkdir(parents=True, exist_ok=False)
    write(out / "FREEZE.json", freeze)
    rows = []
    for arm in freeze["arms"]:
        try:
            rows.append(one(freeze["case"], arm, out / arm))
        except Exception as exc:
            # Preserve existing transcript/state artifacts and run remaining
            # declared cells even if setup, audit, or evaluator fails.
            failed = {"arm": arm, "cell_error": {"type": type(exc).__name__, "message": str(exc)},
                      "execution_error": "cell_incomplete_see_retained_artifacts",
                      "evaluation_returncode": None, "audit": None, "native_evaluation": None,
                      "native_calls": None, "native_writes": None, "full_task_success": False}
            (out / arm).mkdir(parents=True, exist_ok=True)
            write(out / arm / "FAILED_RESULT.json", failed)
            rows.append(failed)
            print(json.dumps(failed), flush=True)
    unchanged = manifest() == (freeze["sources"], freeze["vendor_sources"])
    direct_path = out / "direct_native_dispatch/ACTOR_RESULT.json"
    ecrc_path = out / "qualification_ecrc/ACTOR_RESULT.json"
    direct = read(direct_path) if direct_path.exists() else {}
    ecrc = read(ecrc_path) if ecrc_path.exists() else {}
    same_candidates = direct.get("candidates") == ecrc.get("candidates") and len(direct.get("candidates", [])) == 2
    summary = {"stage": "exposed_module_development", "rows": rows, "sources_unchanged": unchanged,
               "same_direct_ecrc_candidates": same_candidates, "model_calls": 0, "model_api_cost_usd": 0,
               "paper_changed": False, "isolation": isolation, "full_benchmark_run": False}
    write(out / "SUMMARY.json", summary)
    if not unchanged or not same_candidates or any(r["execution_error"] or r["evaluation_returncode"] for r in rows):
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
