"""Independent final execution of exact registered source bytes.

Trusted orchestration supplies a registry job with the official fixed suite.
This is a fresh execution of that same suite, not a held-out test split or an
oracle resistant to deliberately harness-aware malicious Python. The result
does not feed back to the agent and consumes no study verification allowance.
Its actual execution and resource use are recorded separately.
"""
from pathlib import Path
import hashlib

from workload import job_runner


def evaluate(job: dict, out_dir: Path) -> dict:
    """Run a final registry job in a new sandbox and record its separate cost.

    ``job`` must come from trusted orchestration/registry, never a model-supplied
    verdict. The caller supplies the official fixed ``test`` and entry point.
    The copied runner validates its own hash and binds source/test hashes.
    Existing output directories are rejected, including empty directories.
    """
    frozen_job = dict(job)
    for field in ("solution", "test"):
        value = frozen_job[field]
        if not isinstance(value, str):
            raise TypeError(field + " must be source text")
        actual = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if actual != frozen_job[field + "_sha256"]:
            raise ValueError(field + " hash mismatch before independent execution")
    if frozen_job["runner_sha256"] != job_runner.runner_sha256():
        raise ValueError("runner bundle hash mismatch before independent execution")
    destination = Path(out_dir).resolve()
    if destination.exists():
        raise FileExistsError("independent final execution requires a new output directory")

    # No service/cache call: every accepted invocation reaches the real runner.
    result = job_runner.run_job(frozen_job, destination)
    record = {
        **result,
        "accepted": result["status"] == "pass",
        "evaluation_role": "independent_final_execution",
        "suite_policy": "same_official_fixed_suite",
        "held_out_suite": False,
        "feedback_to_agent": False,
        "cached_tool_result_used": False,
        "study_quota_units": 0,
        "model_api_calls": 0,
        "candidate_source_on_host_executed": False,
        "independent_cost": {
            "actual_starts": result["actual_starts"],
            "actual_start_known": result["actual_start_known"],
            "cpu_seconds": result.get("cpu_seconds"),
            "suite_wall_seconds": result.get("wall_seconds"),
            "launcher_wall_seconds": result.get("launcher_wall_seconds"),
        },
        "acceptance_record": str(destination / "acceptance.json"),
    }
    job_runner.save_json(destination / "acceptance.json", record)
    return record
