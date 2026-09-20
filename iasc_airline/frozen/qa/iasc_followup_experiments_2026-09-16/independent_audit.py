"""Read-only, standard-library audit of the two frozen airline follow-ups.

No runner, actor, ECRC core, native environment, model, or service is imported.
The old independent reconstruction and SQL checks are imported by verified hash.
This wrapper generalizes study provenance and initial-state references only.
Run after SUMMARY.json exists; never use this program to screen future records.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
PILOTS = WORKSPACE / "research_pilots"
OLD = PILOTS / "ecrc_native_record_coverage_2026-09-15"
VENDOR = PILOTS / "ecrc_airline_pilot_2026-09-15/vendor/tau2-bench"
COVERAGE_AUDIT = OLD / "review/postrun_01/audit_outputs.py"
COVERAGE_HASH = "b5a233871e45161393cf784d1fcb8db7ad2ee10adda15a5b6fc5420d19592f2b"
PRIMITIVE_AUDIT = PILOTS / "ecrc_component_ablation_dev_2026-09-15/review/postrun_01/audit_outputs.py"
PRIMITIVE_HASH = "b75549d5c406afd521f8174ff4e00ef4f73e7cf50f7694feeb73e414cae7a6b4"
ARMS = ("direct_native_dispatch", "qualification_ecrc", "existing_rules_only",
        "without_claim_evidence_requirement")


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    require(path == root or root in path.parents, "artifact path escapes the declared study: " + str(path))
    return path


def load_module(path, expected, name):
    require(sha(path) == expected, "independent auditor source drift: " + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def normalized_native_source():
    native = read(VENDOR / "data/tau2/domains/airline/db.json")
    for user in native["users"].values():
        user["address"].setdefault("address2", None)
    for reservation in native["reservations"].values():
        reservation.setdefault("status", None)
    return native


def source_integrity(freeze, study):
    sources, vendor = freeze["sources"], freeze["vendor_sources"]
    changed = [p for p, h in sources.items() if not Path(p).is_file() or sha(p) != h]
    changed_vendor = [p for p, h in vendor.items()
                      if not (VENDOR / p).is_file() or sha(VENDOR / p) != h]
    prior = read(PILOTS / "ecrc_component_ablation_dev_2026-09-15/review/prerun_01/FREEZE.json")
    missing_prior = [p for p, h in prior["sources"].items() if sources.get(p) != h]
    required = [Path(__file__), COVERAGE_AUDIT, PRIMITIVE_AUDIT, study / "PROTOCOL.md",
                study / "REQUESTS.json", *study.glob("*.py")]
    if (study / "COHORT_SELECTION.json").exists():
        required.append(study / "COHORT_SELECTION.json")
    missing = [str(p.resolve()) for p in required if sources.get(str(p.resolve())) != sha(p)]
    require(vendor == prior["vendor_sources"] and len(vendor) == 1570, "pinned vendor tree changed")
    require(sha(COVERAGE_AUDIT) == COVERAGE_HASH and sha(PRIMITIVE_AUDIT) == PRIMITIVE_HASH,
            "independent reconstruction sources changed")
    return {"audit_pass": not any((changed, changed_vendor, missing_prior, missing)),
            "source_files_checked": len(sources), "vendor_files_checked": len(vendor),
            "changed_sources": changed, "changed_vendor": changed_vendor,
            "missing_prior_sources": missing_prior, "missing_required_sources": missing}


def extension_cohort(freeze, study, before):
    """Reconstruct the next ID-only cohort, never filter on eligibility/results."""
    cohort, requests = freeze["cohort"], freeze["requests"]
    prior_path = OLD / "COHORT_SELECTION.json"
    prior = read(prior_path)
    require(cohort["cohort_id"] == "native_extension_ranks_101_200", "extension cohort identity changed")
    require(cohort["seed"] == prior["seed"] == "ecrc-native-record-coverage-v1", "original seed changed")
    require(cohort["rank_range"] == [101, 200] and cohort["expected_selected_accounts"] == 100
            and cohort["declared_cases"] == 300, "extension's frozen resource scope changed")
    require(cohort["previous_cohort_sha256"] == sha(prior_path), "prior cohort source hash changed")
    prior_freeze = read(OLD / "review/prerun_01/FREEZE.json")
    require(prior_freeze["cohort"] == prior
            and prior_freeze["sources"].get(str(prior_path.resolve())) == sha(prior_path),
            "original cohort no longer matches its original pre-run freeze")
    require(freeze["sources"].get(str(prior_path.resolve())) == sha(prior_path), "prior cohort not freeze-bound")
    require(read(study / "COHORT_SELECTION.json") == cohort and read(study / "REQUESTS.json") == requests,
            "current extension input differs from frozen input")
    pool = prior["all_available_accounts_ranked"]
    require(cohort["all_available_accounts_ranked"] == pool, "original complete ID ranking changed")
    chosen = pool[100:200]
    require(cohort["selected_accounts"] == chosen and len(chosen) == 100, "extension is not exactly ranks 101..200")
    old_users = {r["user_id"] for r in prior["selected_accounts"]}
    users, reservations = {r["user_id"] for r in chosen}, {r["selected_reservation_id"] for r in chosen}
    require(len(users) == len(reservations) == 100 and not users & old_users, "cohort overlaps the first 100 accounts")
    require(not users & set(prior["excluded_accounts_union"]), "extension contains a previously excluded account")
    templates = prior["templates"]
    require(requests["templates"] == templates, "the three original reason templates changed")
    expected = []
    for row in chosen:
        uid, rid, rank = row["user_id"], row["selected_reservation_id"], row["account_rank"]
        require(rid in before["users"][uid]["reservations"]
                and before["reservations"][rid]["user_id"] == uid, "invalid selected ownership link")
        for template in templates:
            reason = template["reason"]
            expected.append({"case_id": f"record_{rank:03d}_{reason}", "task_id": None,
                "kind": "controlled_native_record_followup_request", "native_full_goal_in_scope": False,
                "account_rank": rank, "paired_account_id": uid, "paired_reservation_id": rid,
                "reason_template": reason, "request": {"user_id": uid,
                    "user_statement": template["statement"].format(reservation_id=rid),
                    "cancellation": {"selector": {"kind": "ids", "ids": [rid]}, "reason": reason}}})
    require(requests["cases"] == expected, "extension requests differ from exact ID-ranked construction")
    require(requests["selected_accounts"] == requests["unique_selected_reservations"] == 100,
            "extension denominator metadata differs")
    require(before == normalized_native_source(), "extension initial DB differs from the pinned native source")
    return {"audit_pass": True, "cohort_id": cohort["cohort_id"], "rank_range": [101, 200],
            "selected_accounts": len(users), "selected_reservations": len(reservations),
            "request_contexts": len(expected), "overlap_first_cohort_accounts": 0,
            "new_to_first_cohort_runs_only": True, "never_previously_read_claim": False}


def apply_patch_operations(base, operations):
    """Only declared replacement operations; missing paths are never tolerated."""
    state = deepcopy(base)
    seen = set()
    for operation in operations:
        require(set(operation) == {"path", "before", "after"}, "unsupported fixture patch operation")
        path = operation["path"]
        require(isinstance(path, list) and path, "fixture patch needs a nonempty key path")
        marker = canonical(path)
        require(marker not in seen, "fixture patch replaces the same path twice")
        seen.add(marker)
        node = state
        for key in path[:-1]:
            node = node[key]
        key = path[-1]
        require(node[key] == operation["before"], "fixture patch preimage mismatch")
        node[key] = deepcopy(operation["after"])
    return state


def fixture_initial_states(freeze, batch):
    """Audit explicit fixtures from their frozen original DB and patch index."""
    index = freeze["fixtures"]
    cases = freeze["requests"]["cases"]
    require(len(index) == len(cases) and Counter(e["case_id"] for e in index)
            == Counter(c["case_id"] for c in cases), "fixture index differs from complete case grid")
    base_info = freeze["base_db"]
    base_path = inside(batch / base_info["path"], batch)
    require(sha(base_path) == base_info["file_sha256"], "base DB file hash differs")
    base = read(base_path)
    require(digest(base) == base_info["canonical_sha256"] and base == normalized_native_source(),
            "fixture base is not the original native DB")
    states, evidence = {}, []
    for entry in index:
        before_path, patch_path = (inside(batch / entry[k], batch) for k in ("before_path", "patch_path"))
        require(sha(before_path) == entry["before_file_sha256"]
                and sha(patch_path) == entry["patch_file_sha256"], "fixture artifact hash differs")
        patch = read(patch_path)
        reconstructed = apply_patch_operations(base, patch["operations"])
        before = read(before_path)
        require(before == reconstructed and digest(before) == entry["before_canonical_sha256"],
                "case BEFORE contains unexplained changes beyond its frozen patch")
        states[entry["case_id"]] = (before, before_path, sha(before_path), digest(before))
        evidence.append({"case_id": entry["case_id"], "operations": len(patch["operations"]),
                         "before_sha256": sha(before_path), "patch_sha256": sha(patch_path)})
    return states, {"audit_pass": True, "constructed_fixture_count": len(states),
                    "base_file_sha256": sha(base_path), "patches": evidence,
                    "native_observational_cohort": False}


def bind_initial_reference(folder, expected_path, before, before_sha, before_digest):
    reference = read(folder / "BEFORE_DB_REFERENCE.json")
    target = Path(reference["path"])
    if not target.is_absolute():
        target = folder / target
    require(target.resolve() == expected_path.resolve(), "cell initial reference points to a different fixture")
    require(reference["file_sha256"] == before_sha and reference["canonical_sha256"] == before_digest,
            "cell initial-state hash differs")
    require(reference["fresh_native_initial_state_verified"] is True, "fresh environment was not verified")
    require(not (folder / "BEFORE_DB.json").exists(), "undeclared cell-local initial state")
    return before


def saved_replay_responses(folder, calls):
    """Optional stronger second-pass transcript; absent old artifacts are explicit."""
    path = folder / "NATIVE_REPLAY_RESPONSES.json"
    if not path.exists():
        return {"separate_second_pass_responses_saved": False,
                "scope": "Independently reconstructs recorded responses/full DB; binds runner replay hashes. No new replay executed."}
    responses = read(path)
    require(len(responses) == len(calls), "second-pass response count differs")
    for expected, actual in zip(calls, responses):
        require(actual == expected["response"], "saved second-pass response differs from the actor transcript")
    return {"separate_second_pass_responses_saved": True, "response_count": len(responses), "all_equal": True}


def native_effects(before, after, ids, actual):
    """Report native writes and payment-list mutations separately from eligibility."""
    writes = Counter(actual)
    rows = []
    for rid in ids:
        old, new = before["reservations"][rid], after["reservations"][rid]
        old_payments, new_payments = old["payment_history"], new["payment_history"]
        old_net = sum(p["amount"] for p in old_payments)
        new_net = sum(p["amount"] for p in new_payments)
        was_cancelled = old.get("status") == "cancelled"
        rows.append({"reservation_id": rid, "status_before": old.get("status"),
            "status_after": new.get("status"), "cancel_write_count": writes[rid],
            "status_transitioned_to_cancelled": not was_cancelled and new.get("status") == "cancelled",
            "repeated_cancel_write_count": max(0, writes[rid] - (0 if was_cancelled else 1)),
            "payment_history_entries_before": len(old_payments), "payment_history_entries_after": len(new_payments),
            "payment_history_entries_added": len(new_payments) - len(old_payments),
            "payment_history_net_before": old_net, "payment_history_net_after": new_net,
            "payment_history_net_delta": new_net - old_net})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["extension", "boundary"], required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), "review already exists; choose a new versioned path")
    batch = args.batch.resolve()
    study = batch.parent.parent
    require(batch.parent.name == "runs" and study.parent == PILOTS, "unexpected study/batch path")
    require((batch / "SUMMARY.json").is_file(), "wait for the complete retained SUMMARY before auditing")
    coverage = load_module(COVERAGE_AUDIT, COVERAGE_HASH, "frozen_coverage_audit")
    primitives = load_module(PRIMITIVE_AUDIT, PRIMITIVE_HASH, "frozen_native_audit_primitives")
    freeze, summary = read(batch / "FREEZE.json"), read(batch / "SUMMARY.json")
    require(tuple(freeze["arms"]) == ARMS, "frozen four-arm definitions changed")
    cases = freeze["requests"]["cases"]
    require(len({c["case_id"] for c in cases}) == len(cases), "duplicate case IDs")
    coverage.REASONS = tuple(dict.fromkeys(c["request"]["cancellation"]["reason"] for c in cases))
    failures, rows, pairs, permissions, replay_checks = [], [], [], [], []
    integrity = source_integrity(freeze, study)
    require(integrity["audit_pass"], "frozen source/vendor integrity failed: " + canonical(integrity))
    if args.kind == "extension":
        before_path = batch / "BEFORE_DB.json"
        before = read(before_path)
        scope = extension_cohort(freeze, study, before)
        states = {c["case_id"]: (before, before_path, sha(before_path), digest(before)) for c in cases}
    else:
        states, scope = fixture_initial_states(freeze, batch)
    frozen_cases = Counter((c["case_id"], arm) for c in cases for arm in ARMS)
    stored_cases = Counter((r["case_id"], r["arm"]) for r in summary["rows"])
    if stored_cases != frozen_cases:
        failures.append({"scope": "grid", "error": "SUMMARY does not contain exactly every frozen cell"})
    lookup = {(r["case_id"], r["arm"]): r for r in summary["rows"]}
    expected_folders = {case + "__" + arm for case, arm in frozen_cases}
    unexpected = [p.name for p in batch.iterdir() if p.is_dir() and "__" in p.name and p.name not in expected_folders]
    if unexpected:
        failures.append({"scope": "grid", "undeclared_folders": unexpected})
    require(summary["sources_unchanged"] is True and summary["model_calls"] == summary["model_api_cost_usd"] == 0,
            "runner reports source drift or model work")
    require(summary["full_benchmark_run"] is False, "component study assigned full benchmark scope")
    for number, case in enumerate(cases, 1):
        before, before_path, before_sha, before_digest = states[case["case_id"]]
        coverage.shared_before = lambda folder, _batch, _sha, _before, _digest: bind_initial_reference(
            folder, before_path, before, before_sha, before_digest)
        data = {}
        for arm in ARMS:
            folder = batch / (case["case_id"] + "__" + arm)
            try:
                cell = coverage.audit_cell(primitives, batch, case, arm, before, before_sha, before_digest)
                require(lookup[(case["case_id"], arm)] == read(folder / "RESULT.json"), "SUMMARY/cell result mismatch")
                replay = saved_replay_responses(folder, read(folder / "TOOL_CALLS.json"))
                replay_checks.append({"case_id": case["case_id"], "arm": arm, **replay})
                data[arm] = cell
                cell["row"]["native_effects"] = native_effects(before, cell["after"], cell["row"]["selected_ids"],
                                                              cell["row"]["actual_cancelled_ids"])
                rows.append(cell["row"])
                if cell["gate"]:
                    permissions.extend({"case_id": case["case_id"], "arm": arm, **entry}
                                       for entry in cell["gate"]["permissions"])
            except Exception as exc:
                failed = coverage.failure_row(primitives, case, arm, before, exc, folder)
                failed["native_effects"] = None
                rows.append(failed)
                failures.append({"case_id": case["case_id"], "arm": arm,
                                 "error_type": type(exc).__name__, "error": str(exc)})
        if len(data) == len(ARMS):
            try:
                pairs.append({"case_id": case["case_id"], **coverage.compare_paired_inputs(data)})
            except Exception as exc:
                failures.append({"case_id": case["case_id"], "scope": "paired_inputs", "error": str(exc)})
        if number % 25 == 0:
            print(json.dumps({"audited_requests": number, "planned_requests": len(cases), "findings": len(failures)}), flush=True)
    for before, path, expected_sha, expected_digest in states.values():
        if sha(path) != expected_sha or digest(before) != expected_digest:
            failures.append({"scope": "initial_state_integrity", "path": str(path)})
    final_integrity = source_integrity(freeze, study)
    if final_integrity != integrity or not final_integrity["audit_pass"]:
        failures.append({"scope": "final_source_integrity", "details": final_integrity})
    passed = not failures and len(rows) == len(frozen_cases) and len(pairs) == len(cases)
    population = []
    for case in cases:
        part = coverage.describe_candidate_population(primitives, [case], states[case["case_id"]][0])
        population.extend(part["candidate_contexts"])
    result = {"recorded_at": datetime.now(timezone.utc).isoformat(), "audit_script_sha256": sha(Path(__file__)),
              "audit_script_in_prerun_freeze": freeze["sources"].get(str(Path(__file__).resolve())) == sha(Path(__file__)),
              "kind": args.kind, "batch": str(batch), "scope_audit": scope, "source_integrity": integrity,
              "technical_integrity_pass": passed, "failures": failures, "rows": rows,
              "aggregate": coverage.aggregate_rows(rows, cases),
              "reason_aggregate": coverage.aggregate_rows(rows, cases, by_reason=True),
              "pairs": pairs, "permissions": permissions, "replay_artifact_checks": replay_checks,
              "candidate_population": {"candidate_contexts": population, "positive_bases_may_overlap": True},
              "planned_cells": len(frozen_cases), "planned_request_contexts": len(cases),
              "model_calls": 0, "model_api_cost_usd": 0, "full_task_success_established": False,
              "native_episode_executed_by_auditor": False,
              "limitations": ["Technical integrity does not require an arm to win or the two complete workflows to tie.",
                              "Failed or missing cells retain unknown effect totals, never synthetic zeroes.",
                              "Repeated reason contexts share records; boundary fixtures are constructed tests.",
                              "No full-task, unseen-data, population reliability, CPU/money, or atomic native-receipt claim.",
                              "The auditor independently reconstructs original tool responses and full DB effects; it does not launch a new replay."]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"technical_integrity_pass": passed, "cells": len(rows), "pairs": len(pairs),
                      "failure_count": len(failures), "first_failures": failures[:10]}), flush=True)
    if not passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
