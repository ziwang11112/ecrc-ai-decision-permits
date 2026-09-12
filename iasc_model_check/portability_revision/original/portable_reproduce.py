"""Verify retained S10 evidence (default), or reproduce it in a new directory.

This post-hoc public-archive wrapper is not one of the 15 pre-run frozen files.
It never calls the historical workspace-bound runners or alters retained runs.
Python 3.10+; standard library only. Run --help for the execution interface.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
FREEZE_SHA256 = "f88faba8a248ab51fe18bce8454776e1e57a723ca70494e022a26f71b8437a8d"
REVIEW_SHA256 = "ed9da58d5f279ceaed7a3db6f6c8d9d7b475adc33a7d5c8b089f12139e8cb3bb"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def relative_file(name):
    """Archive paths are relative; never follow retained author-machine paths."""
    path = (HERE / name).resolve()
    require(HERE in path.parents, "Path escapes the archive: " + name)
    require(path.is_file(), "Required archive file missing: " + name)
    return path


def outside_new_path(value):
    path = Path(value).expanduser().resolve()
    require(path != HERE and HERE not in path.parents,
            "New output must be outside the archive root")
    require(not path.exists(), "Refusing to overwrite existing path: " + str(path))
    return path


def tlc_statistics(log):
    matches = re.findall(r"([\d,]+) states generated, ([\d,]+) distinct states found, ([\d,]+) states left on queue", log)
    require(bool(matches), "TLC completion statistics missing")
    counts = dict(zip(("generated_states", "distinct_states", "queue_remaining"),
                      (int(x.replace(",", "")) for x in matches[-1])))
    depths = re.findall(r"The depth of the complete state graph search is (\d+)", log)
    counts["reported_search_depth"] = int(depths[-1]) if depths else None
    return counts


def compare_case(case, tlc, exact, log, exact_directory):
    name = case["id"]
    require(tlc["case"] == exact["case"] == case, name + ": case binding mismatch")
    require(not tlc["timed_out"], name + ": TLC timed out")
    counts = tlc_statistics(log)
    require(all(tlc.get(k) == v for k, v in counts.items()), name + ": TLC JSON/log count mismatch")
    if case["unsafe"]:
        require(tlc["status"] == exact["status"] == "EXPECTED_COUNTEREXAMPLE"
                and tlc["returncode"] == 12
                and "Invariant EffectCountBound is violated." in log
                and "State 1:" in log
                and not exact["complete_reachable_graph"], name + ": expected counterexample not confirmed")
        witness = read(exact_directory / "COUNTEREXAMPLE.json")
        trace = witness["trace"]
        final = trace[-1]["state"]
        rejection = witness["positive_model_first_rejected_step"]
        require(witness["case"] == case and witness["transition_count"] == len(trace) - 1
                and len(final["effects"]) > case["capacity"]
                and final["heldCount"] + final["committedCount"] <= case["capacity"]
                and rejection["action"]["name"] == "UnsafeReleaseUnknown"
                and rejection["positive_enabled_action_targets"] == [], name + ": invalid negative witness endpoint")
        return {"case": name, "status": "BOTH_FOUND_COUNTEREXAMPLE", "exhaustive": False,
                "note": "Partial negative discovered/checked/expanded counts need not match; they are not a complete graph."}
    require(tlc["status"] == exact["status"] == "COMPLETE_PASS"
            and tlc["returncode"] == 0
            and "Model checking completed. No error has been found." in log
            and counts["queue_remaining"] == exact["frontier_states_not_expanded"] == 0
            and exact["complete_reachable_graph"] and exact["exhaustive_positive"], name + ": positive search incomplete")
    require(counts["distinct_states"] == exact["unique_labeled_states_discovered"]
            == exact["states_checked"] == exact["states_expanded"], name + ": positive state counts differ")
    require(counts["generated_states"] == exact["generated_states_including_initial"]
            == 1 + exact["enabled_action_instance_edges_generated"], name + ": transition counts differ")
    require(counts["reported_search_depth"] == 1 + exact["maximum_discovered_shortest_path_depth_edges"], name + ": depth conventions disagree")
    require(len(exact["invariant_violating_checked_states"]) == 9
            and all(v == 0 for v in exact["invariant_violating_checked_states"].values())
            and exact["invariant_state_check_count"] == 9 * exact["states_checked"], name + ": invariant results disagree")
    coverage = {a: int(y) for a, _, y in re.findall(r"^<(\w+) line[^>]*>:\s*(\d+):(\d+)", log, re.M) if a != "Init"}
    expected = {a: v["generated_edges"] for a, v in exact["action_coverage"].items()}
    require(coverage == expected and len(coverage) == 18
            and sum(v > 0 for v in coverage.values()) == 17
            and coverage["UnsafeReleaseUnknown"] == 0
            and sum(coverage.values()) + 1 == counts["generated_states"], name + ": action coverage mismatch")
    return {"case": name, "status": "COMPLETE_COUNTS_AND_COVERAGE_MATCH", "exhaustive": True,
            "distinct_states": counts["distinct_states"], "generated_including_initial": counts["generated_states"],
            "covered_normal_action_families": 17, "unsafe_action_edges": 0}


def verify_retained():
    require(sha(relative_file("FREEZE.json")) == FREEZE_SHA256, "Historical FREEZE hash mismatch")
    freeze = read(HERE / "FREEZE.json")
    require(len(freeze["source_hashes"]) == 15, "Expected 15 pre-run frozen sources")
    for name, digest in freeze["source_hashes"].items():
        require(sha(relative_file(name)) == digest, "Frozen source hash mismatch: " + name)
    require(sha(relative_file("FINAL_ENUMERATION_REVIEW.json")) == REVIEW_SHA256, "Retained final-review hash mismatch")
    review = read(HERE / "FINAL_ENUMERATION_REVIEW.json")
    require(review["status"] == "PASS" and review["freeze_sha256"] == FREEZE_SHA256,
            "Retained final review does not bind the successful historical run")
    for name, digest in review["evidence_sha256"].items():
        require(sha(relative_file(name)) == digest, "Retained evidence hash mismatch: " + name)
    rows = []
    for tool in ("tlc", "exact"):
        start = read(relative_file("runs/v1/" + tool + "/START.json"))
        require(start["freeze_sha256"] == FREEZE_SHA256, tool + " START freeze mismatch")
    for case in freeze["cases"]:
        name = case["id"]
        tdir, edir = HERE / "runs/v1/tlc" / name, HERE / "runs/v1/exact" / name
        tlc, exact = read(tdir / "RESULT.json"), read(edir / "RESULT.json")
        for filename in ("ECRCLifecycle.tla", name + ".cfg"):
            require(sha(tdir / filename) == freeze["source_hashes"][filename], name + ": copied source mismatch")
        for filename, digest in exact["source_sha256"].items():
            require(digest == freeze["source_hashes"][filename], name + ": exact source binding mismatch")
        for filename in ("stdout.txt", "stderr.txt"):
            require(sha(tdir / filename) == tlc[filename.split(".")[0] + "_sha256"], name + ": log hash mismatch")
        rows.append(compare_case(case, tlc, exact, (tdir / "stdout.txt").read_text(encoding="utf-8"), edir))
    baseline = read(HERE / "ARTIFACT_BASELINE.json")
    return {"status": "PASS", "mode": "retained_evidence_verification", "freeze_sha256": FREEZE_SHA256,
            "frozen_sources_verified": 15, "retained_evidence_hashes_verified": len(review["evidence_sha256"]),
            "pre_run_START_bindings_verified": ["tlc", "exact"], "cases": rows,
            "author_workspace_baseline": {"status": "NOT_CHECKED", "target_count": len(baseline),
                "metadata_hash_verified": True,
                "reason": "Targets are outside the public S10 archive. Their historical audit is retained; this verifier does not inspect the author workspace or claim to recheck its preservation."},
            "limitations": "Integrity and finite-model result checks; no signature/authenticity guarantee, unbounded protocol proof, code refinement, liveness, statistical inference or independent third enumeration."}


def run_tlc(case, directory, java, jar):
    directory.mkdir(parents=True, exist_ok=False)
    for filename in ("ECRCLifecycle.tla", case["id"] + ".cfg"):
        shutil.copyfile(HERE / filename, directory / filename)
    # Preserve v1 options, including heap and GC advisory. Do not add -deadlock.
    command = [str(java), "-Xmx2g", "-cp", str(jar), "tlc2.TLC", "-workers", "1", "-fp", "0",
               "-coverage", "1", "-metadir", str(directory / "states"), "-config", case["id"] + ".cfg", "ECRCLifecycle.tla"]
    write_new(directory / "COMMAND.json", {"command": command, "cwd": str(directory), "case": case})
    started = time.perf_counter()
    timed_out = False
    with (directory / "stdout.txt").open("xb") as out, (directory / "stderr.txt").open("xb") as err:
        process = subprocess.Popen(command, cwd=directory, stdout=out, stderr=err,
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        try:
            code = process.wait(timeout=case["timeout_seconds"])
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            code = process.wait(timeout=30)
        except BaseException:
            process.kill()
            process.wait(timeout=30)
            raise
    log = (directory / "stdout.txt").read_text(encoding="utf-8", errors="replace")
    try:
        counts = tlc_statistics(log)
    except ValueError:
        counts = {}  # Incomplete/error status remains explicit; raw logs are retained.
    clean = code == 0 and not timed_out and counts.get("queue_remaining") == 0 and "Model checking completed. No error has been found." in log
    negative = code == 12 and not timed_out and "Invariant EffectCountBound is violated." in log and "State 1:" in log
    status = ("EXPECTED_COUNTEREXAMPLE" if negative else "INCOMPLETE_OR_FAILURE") if case["unsafe"] else ("COMPLETE_PASS" if clean else "INCOMPLETE_OR_FAILURE")
    result = {"case": case, "status": status, "returncode": code, "timed_out": timed_out,
              "elapsed_seconds": time.perf_counter() - started, **counts,
              "exhaustive_positive": clean and not case["unsafe"], "exhaustive_negative": False if case["unsafe"] else None,
              "stdout_sha256": sha(directory / "stdout.txt"), "stderr_sha256": sha(directory / "stderr.txt")}
    write_new(directory / "RESULT.json", result)
    return result, log


def execute(output, java, jar, java_expected, verification):
    manifest = read(HERE / "tools/TOOLCHAIN.json")
    java, jar = Path(java).expanduser().resolve(), Path(jar).expanduser().resolve()
    java_expected = (java_expected or manifest["java"]["java_executable_sha256"]).lower()
    require(re.fullmatch(r"[0-9a-f]{64}", java_expected), "Expected Java SHA256 must have 64 hexadecimal characters")
    require(sha(java) == java_expected, "Java executable hash mismatch; a different platform requires an explicit --java-sha256")
    require(sha(jar) == manifest["tlc"]["jar_sha256"], "tla2tools.jar does not match the frozen toolchain hash")
    output.mkdir(parents=True, exist_ok=False)
    start = {"started_utc": datetime.now(timezone.utc).isoformat(), "kind": "POST_HOC_PORTABLE_REPRODUCTION",
             "historical_run": "v1 (unchanged)", "freeze_sha256": FREEZE_SHA256,
             "wrapper_sha256": sha(Path(__file__)), "python_version": sys.version,
             "java_executable": str(java), "java_executable_sha256": sha(java),
             "java_matches_historical_executable": sha(java) == manifest["java"]["java_executable_sha256"],
             "jar": str(jar), "jar_sha256": sha(jar), "retained_verification": verification}
    write_new(output / "START.json", start)
    try:
        version = subprocess.run([str(java), "-version"], capture_output=True, timeout=30,
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        write_new(output / "JAVA_VERSION.json", {"returncode": version.returncode,
                  "stdout": version.stdout.decode("utf-8", errors="replace"), "stderr": version.stderr.decode("utf-8", errors="replace")})
        require(version.returncode == 0, "java -version failed")
        # Import the hash-verified frozen engine without creating archive __pycache__.
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("s10_frozen_exact_engine", HERE / "exact_check.py")
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        freeze = engine.validate_freeze()
        rows = []
        for case in freeze["cases"]:
            print(json.dumps({"starting": case["id"], "kind": "POST_HOC_PORTABLE_REPRODUCTION"}), flush=True)
            tlc, log = run_tlc(case, output / "tlc" / case["id"], java, jar)
            edir = output / "exact" / case["id"]
            edir.mkdir(parents=True, exist_ok=False)
            with (edir / "stdout.txt").open("x", encoding="utf-8") as out:
                with contextlib.redirect_stdout(out):
                    exact = engine.check_case(case, edir)
            rows.append(compare_case(case, tlc, exact, log, edir))
            if not case["unsafe"]:
                old = read(HERE / "runs/v1/exact" / case["id"] / "RESULT.json")
                require(exact["unique_labeled_states_discovered"] == old["unique_labeled_states_discovered"]
                        and exact["generated_states_including_initial"] == old["generated_states_including_initial"],
                        case["id"] + ": differs from historical positive counts")
        # Confirm that neither imported engine nor reproduction modified the archive.
        verify_retained()
        result = {"status": "PASS", "kind": "POST_HOC_PORTABLE_REPRODUCTION", "cases": rows,
                  "historical_retained_evidence_still_verified": True,
                  "author_workspace_baseline": verification["author_workspace_baseline"],
                  "limitations": verification["limitations"]}
        write_new(output / "SUMMARY.json", result)
        return result
    except BaseException as exc:
        write_new(output / "ERROR.json", {"status": "INCOMPLETE_OR_FAILURE", "type": type(exc).__name__,
                  "message": str(exc), "traceback": traceback.format_exc(), "automatic_retry": False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Run all fixed cases after retained-evidence verification")
    parser.add_argument("--output", help="Required for execution: nonexistent directory outside archive root")
    parser.add_argument("--java", help="Explicit path to a user-supplied Java executable")
    parser.add_argument("--java-sha256", help="Expected local Java executable SHA256; default is the historical executable hash")
    parser.add_argument("--jar", help="Explicit tla2tools.jar path; SHA256 must match frozen TOOLCHAIN.json")
    parser.add_argument("--report", help="Verify-only: save JSON to a nonexistent file outside archive root")
    args = parser.parse_args()
    if args.execute:
        if not all((args.output, args.java, args.jar)) or args.report:
            parser.error("--execute requires --output, --java and --jar; --report is verify-only")
    elif any((args.output, args.java, args.java_sha256, args.jar)):
        parser.error("Execution options require --execute")
    try:
        require(sys.version_info >= (3, 10), "Python 3.10+ is required")
        destination = outside_new_path(args.output or args.report) if args.output or args.report else None
        verification = verify_retained()
        if args.execute:
            result = execute(destination, args.java, args.jar, args.java_sha256, verification)
        else:
            result = verification
            if destination:
                destination.parent.mkdir(parents=True, exist_ok=True)
                write_new(destination, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
