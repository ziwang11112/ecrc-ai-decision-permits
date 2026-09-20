"""Boundary-only replay-artifact adapter for the preserved follow-up auditor v1.

Native ToolMessage timestamps are created at each actual invocation. Compare
second-pass response semantics while retaining both truthful transport times.
All v1 selection, full DB reconstruction, SQL and failure-retention rules remain.
"""
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
V1 = HERE / "independent_audit.py"
V1_SHA256 = "ca339fb7373820bfd19241950495708dfd117f2802fc575ecb3752074fa0f93d"


def load_v1():
    actual = hashlib.sha256(V1.read_bytes()).hexdigest()
    if actual != V1_SHA256:
        raise ValueError("The extension's frozen auditor v1 has changed")
    spec = importlib.util.spec_from_file_location("preserved_followup_auditor_v1", V1)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


AUDIT = load_v1()


def semantic_response(value):
    AUDIT.require(isinstance(value, dict), "native replay response is not an object")
    AUDIT.require(set(value) == {"id", "role", "content", "requestor", "error", "turn_idx", "timestamp"},
                  "unexpected native ToolMessage schema")
    AUDIT.require(value["role"] == "tool", "replay response is not a tool message")
    timestamp = value["timestamp"]
    AUDIT.require(isinstance(timestamp, str), "actual native replay timestamp was omitted")
    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    result = {k: v for k, v in value.items() if k != "timestamp"}
    try:
        result["content"] = json.loads(value["content"])
    except (TypeError, json.JSONDecodeError):
        pass
    return result


def saved_replay_responses(folder, calls):
    path = folder / "NATIVE_REPLAY_RESPONSES.json"
    AUDIT.require(path.is_file(), "boundary second-pass response evidence is missing")
    responses = AUDIT.read(path)
    AUDIT.require(isinstance(responses, list) and len(responses) == len(calls),
                  "second-pass response count differs")
    native = AUDIT.read(folder / "NATIVE_REPLAY.json")
    response_hash = AUDIT.digest(responses)
    AUDIT.require(native["replay_responses_canonical_sha256"] == response_hash
                  and native["replay_responses_count"] == len(responses),
                  "native replay result does not bind its actual second-pass response array")
    for index, (call, actual) in enumerate(zip(calls, responses)):
        AUDIT.require(semantic_response(actual) == semantic_response(call["response"]),
                      "saved replay response semantics differ at call " + str(index))
    return {"separate_second_pass_responses_saved": True, "response_count": len(responses),
            "canonical_sha256": response_hash, "file_sha256": AUDIT.sha(path),
            "all_response_semantics_equal": True, "independent_actual_timestamps_retained": True,
            "auditor_executed_native_replay": False}


BASE_SOURCE_INTEGRITY = AUDIT.source_integrity


def source_integrity(freeze, study):
    result = BASE_SOURCE_INTEGRITY(freeze, study)
    AUDIT.require(freeze["sources"].get(str(V1.resolve())) == V1_SHA256,
                  "boundary freeze does not bind the original v1 auditor")
    return result


# The wrapper's byte hash, rather than a postrun inferred adapter version, is
# reported and required in the boundary pre-run freeze. The original v1 file
# remains byte-for-byte unchanged and separately bound above.
AUDIT.__file__ = str(Path(__file__).resolve())
AUDIT.source_integrity = source_integrity
AUDIT.saved_replay_responses = saved_replay_responses


if __name__ == "__main__":
    AUDIT.main()
