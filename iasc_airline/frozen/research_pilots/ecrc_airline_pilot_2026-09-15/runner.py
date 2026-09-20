"""One ordinary no-model development episode with separate native evaluation."""
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
import zipfile

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor/tau2-bench"


def write(path, value):
    """Save a UTF-8 JSON record; only within an already fresh run directory."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_sources():
    files = list(ROOT.glob("*.py")) + [ROOT / "REQUESTS.json", ROOT / "RUN_PLAN.json"]
    return {p.name: sha(p) for p in sorted(files)}


def verify_vendor():
    """Match every downloaded source/data file to the retained pinned ZIP."""
    records = {}
    with zipfile.ZipFile(ROOT / "vendor_snapshot.zip") as archive:
        prefix = archive.namelist()[0].split("/")[0] + "/"
        for item in archive.infolist():
            if item.is_dir():
                continue
            relative = item.filename.removeprefix(prefix)
            path = (VENDOR / relative).resolve()
            if not path.is_relative_to(VENDOR.resolve()):
                raise ValueError("Archive path escapes source root")
            expected = hashlib.sha256(archive.read(item)).hexdigest()
            if sha(path) != expected:
                raise ValueError(f"Vendor source/data differs: {relative}")
            records[relative] = expected
    return records


def prepare(out):
    """Freeze source, task selection and installed runtime before either episode."""
    out.mkdir(parents=True, exist_ok=False)
    vendor_hashes = verify_vendor()
    pinned_checks = {
        "src/tau2/domains/airline/tools.py": "3987f21c286314cb48764f97052934ff4fd60e27a0b2e4a43423911adf8eaa26",
        "data/tau2/domains/airline/tasks.json": "ccd8ba737b4cc371415af70151187788f728d6108d0916e73bb4317b40542052",
        "data/tau2/domains/airline/split_tasks.json": "b22ced4d9a9850ac9aea31c53bdcb6d6009058140bd9acc7db37c1d36222ba8b",
    }
    for name, expected in pinned_checks.items():
        if vendor_hashes[name] != expected:
            raise ValueError("Archive differs from independently reviewed source: " + name)
    plan = json.loads((ROOT / "RUN_PLAN.json").read_text(encoding="utf-8"))
    native_tasks = json.loads((VENDOR / "data/tau2/domains/airline/tasks.json").read_text(encoding="utf-8"))
    initial_checks = {}
    for episode in plan["episodes"]:
        task = next(t for t in native_tasks if t["id"] == episode["task_id"])
        if task.get("initial_state") is not None:
            raise ValueError("This pilot requires unmodified default initial state")
        initial_checks[episode["task_id"]] = {"initial_state_is_null": True}
    local = local_sources()
    freeze = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "plan": plan, "local_sha256": local,
        "vendor_archive_sha256": sha(ROOT / "vendor_snapshot.zip"),
        "vendor_file_count": len(vendor_hashes),
        "native_sources_modified": False,
        "independently_reviewed_source_hashes_matched": pinned_checks,
        "private_initial_state_qualification": initial_checks,
        "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "python": sys.version,
    }
    write(out / "PRERUN.json", freeze)
    write(out / "VENDOR_HASHES.json", vendor_hashes)
    for name in local:
        destination = out / "sources" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    print(json.dumps({"prepared": True, "source_files": len(local), "vendor_files": len(vendor_hashes)}))


def run_episode(episode, out, freeze_path):
    """Run public rules once, retain all native calls, then evaluate separately."""
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if local_sources() != freeze["local_sha256"]:
        raise RuntimeError("Local source changed after freeze")
    vendor_hashes = verify_vendor()
    if vendor_hashes != json.loads((freeze_path.parent / "VENDOR_HASHES.json").read_text(encoding="utf-8")):
        raise RuntimeError("Vendor source changed after freeze")
    planned = [item for item in freeze["plan"]["episodes"] if item["episode"] == episode]
    if len(planned) != 1:
        raise ValueError("Unknown episode")
    spec = planned[0]
    entries = json.loads((ROOT / "REQUESTS.json").read_text(encoding="utf-8"))["episodes"]
    record = next(item for item in entries if item["task_id"] == spec["task_id"])
    out.mkdir(parents=True, exist_ok=False)
    write(out / "FROZEN_RUN.json", {"episode": spec, "freeze": freeze})
    write(out / "STRUCTURED_REQUEST.json", record)

    from bootstrap import install
    isolation = install()
    from loguru import logger
    logger.remove()
    from tau2.domains.airline.environment import get_environment
    from tau2.data_model.message import AssistantMessage, UserMessage, ToolCall
    from tau2.environment.toolkit import get_tool_types
    from ordinary import run

    env = get_environment()
    before = env.tools.db.model_dump(mode="json")
    write(out / "BEFORE_DB.json", before)
    actions = []
    messages = [UserMessage(role="user", content=json.dumps(record["request"], ensure_ascii=False)).model_dump(mode="json")]
    confirmations = []
    types = get_tool_types(env.tools)

    def call(name, **arguments):
        if len(actions) >= freeze["plan"]["maximum_tool_calls"]:
            raise RuntimeError("Declared development tool-call cap exceeded")
        tool_call = ToolCall(id=f"call-{len(actions)+1}", name=name, arguments=deepcopy(arguments), requestor="assistant")
        messages.append(AssistantMessage(role="assistant", tool_calls=[tool_call]).model_dump(mode="json"))
        response = env.get_response(tool_call)
        payload = response.model_dump(mode="json")
        messages.append(payload)
        actions.append({**tool_call.model_dump(mode="json"), "response": payload,
                        "tool_type": types.get(name).value if name in types else "unknown"})
        write(out / "MESSAGES.json", messages)
        write(out / "TOOL_CALLS.json", actions)
        if response.error:
            raise RuntimeError(response.content)
        try:
            return json.loads(response.content)
        except (TypeError, json.JSONDecodeError):
            return response.content

    def confirm(proposal):
        # The user delegated the eligible cancellations; this script acknowledges
        # the displayed actions, never private labels or reference IDs.
        if proposal["user_id"] != record["request"]["user_id"]:
            raise ValueError("Confirmation belongs to a different user")
        messages.append(AssistantMessage(role="assistant", content=json.dumps(proposal, ensure_ascii=False)).model_dump(mode="json"))
        messages.append(UserMessage(role="user", content="yes").model_dump(mode="json"))
        confirmations.append({"proposal": deepcopy(proposal), "response": "yes"})
        return "yes"

    started = time.perf_counter()
    actor = run(deepcopy(record["request"]), call, confirm)
    actor_seconds = time.perf_counter() - started
    messages.append(AssistantMessage(role="assistant", content=json.dumps({"status": actor["status"], "actions": actor["actions"], "unresolved": actor["unresolved"]}, ensure_ascii=False)).model_dump(mode="json"))
    after = env.tools.db.model_dump(mode="json")
    write(out / "AFTER_DB.json", after)
    write(out / "ACTOR_RESULT.json", actor)
    write(out / "MESSAGES.json", messages)
    write(out / "TOOL_CALLS.json", actions)
    write(out / "CONFIRMATIONS.json", confirmations)
    write(out / "EVALUATION_INPUT.json", {
        "task_id": spec["task_id"], "actions": actions, "messages": messages,
        "termination_reason": "agent_stop", "actor_final_db_hash": env.get_db_hash(),
    })
    # Private task/reference loading is confined to this separate evaluator.
    evaluation = subprocess.run([
        sys.executable, "-B", str(ROOT / "native_evaluation.py"),
        "--input", str(out / "EVALUATION_INPUT.json"),
        "--output", str(out / "NATIVE_EVALUATION.json"),
    ], capture_output=True, text=True, encoding="utf-8", timeout=120)
    (out / "evaluation.stdout.txt").write_text(evaluation.stdout, encoding="utf-8")
    (out / "evaluation.stderr.txt").write_text(evaluation.stderr, encoding="utf-8")
    from policy_audit import audit
    policy = audit(record["request"], messages, before, after)
    write(out / "POLICY_AUDIT.json", policy)
    unchanged = local_sources() == freeze["local_sha256"] and verify_vendor() == vendor_hashes
    result = {
        "episode": episode, "task_id": spec["task_id"],
        "stage": "ordinary_development_episode_completed",
        "actor_status": actor["status"], "actor_seconds": actor_seconds,
        "tool_calls": len(actions),
        "write_tool_calls": sum(item["tool_type"] == "write" for item in actions),
        "native_tool_errors": sum(item["response"]["error"] for item in actions),
        "confirmed_cancellation_readbacks": sum(item["status"] == "cancelled_verified" for item in actor["actions"]),
        "unresolved_count": len(actor["unresolved"]),
        "native_evaluation_process_returncode": evaluation.returncode,
        "native_evaluation": json.loads((out / "NATIVE_EVALUATION.json").read_text(encoding="utf-8")) if evaluation.returncode == 0 else None,
        "policy_audit": policy, "sources_unchanged": unchanged,
        "model_calls": 0, "model_api_cost_usd": 0, "ecrc_used": False,
        "official_dialogue_rollout": False,
        "scripted_structured_user": True,
        "isolation": isolation,
    }
    write(out / "RESULT.json", result)
    print(json.dumps({key:result[key] for key in ("episode", "actor_status", "tool_calls", "write_tool_calls", "confirmed_cancellation_readbacks", "unresolved_count", "native_evaluation_process_returncode", "model_calls", "sources_unchanged")}, indent=2))
    if evaluation.returncode or not unchanged:
        raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["prepare", "run"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--episode")
    parser.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.out.resolve())
    else:
        if not args.episode or not args.freeze:
            parser.error("run requires --episode and --freeze")
        run_episode(args.episode, args.out.resolve(), args.freeze.resolve())
