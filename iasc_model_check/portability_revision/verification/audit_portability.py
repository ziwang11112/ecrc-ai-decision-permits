"""Bounded path/verify-only QA; never invokes TLC or enumerates model states."""
from datetime import datetime, timezone
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys

sys.dont_write_bytecode = True
QA = Path(__file__).resolve().parent
ARCHIVE = QA.parents[2] / "research_pilots/iasc_model_check_2026-09-12"
WRAPPER = ARCHIVE / "portable_reproduce.py"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def inventory():
    freeze, review = read(ARCHIVE / "FREEZE.json"), read(ARCHIVE / "FINAL_ENUMERATION_REVIEW.json")
    names = set(freeze["source_hashes"]) | set(review["evidence_sha256"])
    names.update(("FREEZE.json", "FINAL_ENUMERATION_REVIEW.json", "PORTABLE_REPRODUCTION.md"))
    return {name: sha(ARCHIVE / name.replace("\\", "/")) for name in sorted(names)}


def baseline():
    old = QA / "before/portable_reproduce.py"
    assert old.read_bytes() == WRAPPER.read_bytes()
    assert sha(old) == "06f7263aa8c36e400959abd081a92014a1ea9b54dcba68b3c2d96a3af1821f98"
    write(QA / "BEFORE.json", {"utc": datetime.now(timezone.utc).isoformat(), "wrapper_sha256": sha(old), "protected_sha256": inventory()})
    print("Baseline captured; original wrapper bytes preserved.")


def exercise():
    label = "windows" if os.name == "nt" else "wsl_linux"
    destination = QA / label
    destination.mkdir(exist_ok=False)
    spec = importlib.util.spec_from_file_location("portable_wrapper_under_test", WRAPPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = destination / "fixture"
    root = fixture / "archive"
    (root / "nested").mkdir(parents=True)
    target = root / "nested/evidence.txt"
    target.write_text("QA fixture only\n", encoding="utf-8")
    outside = fixture / "outside.txt"
    outside.write_text("outside the fixture archive\n", encoding="utf-8")
    module.HERE = root.resolve()
    cases = []

    def check(case_id, call, expected=None, error_contains=None):
        try:
            actual = call()
            passed = error_contains is None and actual == expected
            detail = str(actual)
        except Exception as exc:
            passed = isinstance(exc, ValueError) and error_contains is not None and error_contains in str(exc)
            detail = type(exc).__name__ + ": " + str(exc)
        cases.append({"case": case_id, "pass": passed, "detail": detail})

    for name in ("nested/evidence.txt", "nested\\evidence.txt", "nested/./evidence.txt", "nested//evidence.txt", "nested\\.\\evidence.txt", "nested/../nested/evidence.txt"):
        check("accept:" + name, lambda name=name: module.relative_file(name), target.resolve())
    for name in (str(target.resolve()), "/tmp/evidence.txt", "\\nested\\evidence.txt", "C:/evidence.txt", "C:\\evidence.txt", "C:evidence.txt", "C:", "\\\\server\\share\\file", "//server/share/file", "\\\\?\\C:\\evidence.txt", "\\\\.\\C:\\evidence.txt"):
        check("reject_absolute_or_drive:" + name, lambda name=name: module.relative_file(name), error_contains="Archive path must be relative")
    for name in ("../outside.txt", "..\\outside.txt", "nested/../../outside.txt", "nested\\..\\..\\outside.txt"):
        check("reject_escape:" + name, lambda name=name: module.relative_file(name), error_contains="Path escapes the archive")
    check("reject_empty", lambda: module.relative_file(""), error_contains="Archive path must be a nonempty string")
    check("reject_nonstring", lambda: module.relative_file(None), error_contains="Archive path must be a nonempty string")
    check("reject_missing", lambda: module.relative_file("nested/missing.txt"), error_contains="Required archive file missing")
    check("reject_directory", lambda: module.relative_file("nested"), error_contains="Required archive file missing")
    symlink = {"status": "NOT_RUN"}
    try:
        (root / "external_link").symlink_to(outside)
        (root / "internal_link").symlink_to(target)
    except OSError as exc:
        symlink = {"status": "UNAVAILABLE", "error": type(exc).__name__ + ": " + str(exc)}
    else:
        symlink = {"status": "TESTED"}
        check("reject_symlink_escape", lambda: module.relative_file("external_link"), error_contains="Path escapes the archive")
        check("accept_internal_symlink", lambda: module.relative_file("internal_link"), target.resolve())
    for name in (root, root / "new-report.json"):
        check("reject_output_inside:" + str(name), lambda name=name: module.outside_new_path(str(name)), error_contains="New output must be outside")
    check("reject_output_overwrite", lambda: module.outside_new_path(str(outside)), error_contains="Refusing to overwrite")
    new_output = fixture / "new-report.json"
    check("accept_new_outside_output", lambda: module.outside_new_path(str(new_output)), new_output.resolve())
    check("output_guard_does_not_write", lambda: new_output.exists(), False)
    write(destination / "PATH_TESTS.json", {"cases": cases, "symlink": symlink})

    command = [sys.executable, "-B", str(WRAPPER), "--report", str(destination / "VERIFICATION.json")]
    environment = {"utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(), "python": sys.version,
                   "python_executable": sys.executable, "os_name": os.name, "wsl_distribution": os.environ.get("WSL_DISTRO_NAME"),
                   "command": command, "cwd": str(destination), "wrapper_sha256": sha(WRAPPER)}
    write(destination / "COMMAND_ENVIRONMENT.json", environment)
    with (destination / "command.txt").open("x", encoding="utf-8") as stream:
        stream.write((subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)) + "\n")
    with (destination / "stdout.txt").open("xb") as out, (destination / "stderr.txt").open("xb") as err:
        child = subprocess.run(command, cwd=destination, stdout=out, stderr=err, timeout=60, check=False)
    report_path = destination / "VERIFICATION.json"
    verification = read(report_path) if report_path.is_file() else {}
    report_before_retry = sha(report_path) if report_path.is_file() else None
    # The actual CLI must refuse an existing report and preserve its bytes.
    with (destination / "overwrite_stdout.txt").open("xb") as out, (destination / "overwrite_stderr.txt").open("xb") as err:
        retry = subprocess.run(command, cwd=destination, stdout=out, stderr=err, timeout=60, check=False)
    overwrite_error = (destination / "overwrite_stderr.txt").read_text(encoding="utf-8")
    overwrite_pass = retry.returncode == 1 and "Refusing to overwrite existing path" in overwrite_error and report_before_retry == sha(report_path)
    before = read(QA / "BEFORE.json")
    preservation = inventory() == before["protected_sha256"]
    passed = (all(row["pass"] for row in cases) and child.returncode == 0 and verification.get("status") == "PASS"
              and verification.get("frozen_sources_verified") == 15 and verification.get("retained_evidence_hashes_verified") == 19
              and overwrite_pass and preservation and (os.name == "nt" or symlink["status"] == "TESTED"))
    summary = {"status": "PASS" if passed else "FAIL", "platform": label, "path_cases": len(cases),
               "path_cases_passed": sum(row["pass"] for row in cases), "symlink": symlink, "verify_returncode": child.returncode,
               "verify_status": verification.get("status"), "overwrite_rejection_passed": overwrite_pass,
               "protected_files_unchanged": preservation, "wrapper_sha256": sha(WRAPPER),
               "scope": "Path fixture checks and default retained-evidence CLI only; no --execute, TLC, model enumeration or S9 execution."}
    write(destination / "SUMMARY.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if passed else 1


def finalize():
    before = read(QA / "BEFORE.json")
    after = inventory()
    freeze, review = read(ARCHIVE / "FREEZE.json"), read(ARCHIVE / "FINAL_ENUMERATION_REVIEW.json")
    evidence = {name: after[name] == expected for name, expected in review["evidence_sha256"].items()}
    frozen = {name: after[name] == expected for name, expected in freeze["source_hashes"].items()}
    summaries = {label: read(QA / label / "SUMMARY.json") for label in ("windows", "wsl_linux")}
    old_text = (QA / "before/portable_reproduce.py").read_text(encoding="utf-8")
    new_text = WRAPPER.read_text(encoding="utf-8")
    with (QA / "portable_reproduce.diff").open("x", encoding="utf-8") as stream:
        stream.writelines(difflib.unified_diff(old_text.splitlines(keepends=True), new_text.splitlines(keepends=True), fromfile="before/portable_reproduce.py", tofile="after/portable_reproduce.py"))
    result = {"status": "PASS" if before["protected_sha256"] == after and all(frozen.values()) and all(evidence.values()) and all(row["status"] == "PASS" for row in summaries.values()) else "FAIL",
              "utc": datetime.now(timezone.utc).isoformat(), "old_wrapper_sha256": before["wrapper_sha256"], "new_wrapper_sha256": sha(WRAPPER),
              "protected_file_count": len(after), "all_protected_files_unchanged": before["protected_sha256"] == after,
              "frozen_source_matches": frozen, "retained_evidence_matches": evidence, "after_protected_sha256": after,
              "platform_summaries": summaries, "scope": "Post-hoc portable wrapper revision only. Original v1 sources, inputs, review, and retained results unchanged; no research run repeated."}
    write(QA / "REVISION_VERIFICATION.json", result)
    print(json.dumps({key: result[key] for key in ("status", "old_wrapper_sha256", "new_wrapper_sha256", "protected_file_count", "all_protected_files_unchanged")}, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    mode = sys.argv[1]
    sys.exit(baseline() if mode == "baseline" else exercise() if mode == "exercise" else finalize() if mode == "finalize" else 2)
