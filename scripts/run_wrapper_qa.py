"""Run the retained ten-case S8 supplemental QA in a fresh package copy.

This preserves all frozen study sources and historical reports. It starts no
HTTP service and adds no formal experimental repetitions. Standard library only.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
E2E = ROOT / "iasc/end_to_end"
WRAPPER = Path("revision_reviews/runtime_review/review_atomic_wrapper_portable.py")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/wrapper_qa")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("Preserve previous QA; choose a fresh output directory: " + str(output))
    if output.is_relative_to(ROOT / "iasc"):
        parser.error("Choose output outside the frozen iasc source mirror")
    freeze = json.loads((E2E / "CODE_FREEZE.json").read_text(encoding="utf-8"))
    for name, digest in freeze["files"].items():
        source = (E2E / name).resolve()
        if not source.is_relative_to(E2E.resolve()):
            raise ValueError("Invalid frozen source path: " + name)
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError("Frozen source mismatch: " + name)
    output.mkdir(parents=True, exist_ok=False)
    for name in ["CODE_FREEZE.json", *freeze["files"]]:
        destination = output / "end_to_end" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(E2E / name, destination)
    wrapper = output / WRAPPER
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "iasc" / WRAPPER, wrapper)
    completed = subprocess.run([sys.executable, "-B", str(wrapper)], cwd=output, check=False)
    if completed.returncode:
        return completed.returncode
    report_path = wrapper.parent / "WRAPPER_QA_PORTABLE_RESULT.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    expected_cases = {(arm, case) for arm in ("ecrc", "ordinary") for case in (
        "after_reservation", "after_release", "before_issue_commit",
        "cleanup_first_competing_arm", "armed_then_expiry_cleanup")}
    observed = {(row["arm"], row["case"]) for row in report["results"] if row["pass"] is True}
    if (report["passed"] is not True or report["qa_cases"] != 10
            or len(report["results"]) != 10 or observed != expected_cases
            or any(report[k] is not False for k in ("formal_denominator", "process_kills", "real_http"))):
        raise ValueError("Wrapper report failed its ten-case acceptance checks")
    for name, digest in report["source_sha256"].items():
        if freeze["files"][name] != digest:
            raise ValueError("Report source binding mismatch: " + name)
    print("Fresh supplemental QA: PASS (10 cases); report: " + str(report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
