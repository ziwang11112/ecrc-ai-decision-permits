"""Independent read-only audit of controlled native-record cancellation coverage.

This is not an official benchmark score, a fresh task split, or a population
estimate. Each native account/record is reused under three declared reasons.
The auditor never imports actors, the permission core, a native environment or
the runner, and it never executes native episodes. It reuses the unchanged
independent reconstruction and SQLite checks from the preceding v3 audit.
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
import re
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PILOTS = ROOT.parent
WORKSPACE = PILOTS.parent
VENDOR = PILOTS / "ecrc_airline_pilot_2026-09-15/vendor/tau2-bench"
PRIOR_AUDIT = PILOTS / "ecrc_component_ablation_dev_2026-09-15/review/postrun_01/audit_outputs.py"
PRIOR_AUDIT_SHA256 = "b75549d5c406afd521f8174ff4e00ef4f73e7cf50f7694feeb73e414cae7a6b4"
ARMS = ("direct_native_dispatch", "qualification_ecrc", "existing_rules_only",
        "without_claim_evidence_requirement")
GATED = (ARMS[1], ARMS[3])
REASONS = ("health", "other", "unspecified")
SEED = "ecrc-native-record-coverage-v1"
TEMPLATES = [
    {"reason": "health", "statement": "Cancel reservation {reservation_id} because I am sick."},
    {"reason": "other", "statement": "Cancel reservation {reservation_id}. I booked it by mistake."},
    {"reason": "unspecified", "statement": "Cancel reservation {reservation_id}."},
]
COUNT_KEYS = ("selected_candidate_count", "eligible_count", "ineligible_count",
              "unresolved_candidate_count", "eligible_completed", "eligible_missed",
              "ineligible_executed", "unresolved_executed")


def require(condition, message):
    if not condition:
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
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def load_independent_primitives():
    require(sha(PRIOR_AUDIT) == PRIOR_AUDIT_SHA256, "preceding independent v3 auditor changed")
    spec = importlib.util.spec_from_file_location("coverage_frozen_independent_v3_audit", PRIOR_AUDIT)
    module = importlib.util.module_from_spec(spec)
    # Executing definitions only: its main() is protected by __name__. Disable
    # bytecode writes so even importing this read-only helper changes no source.
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def shared_before(folder, batch, expected_sha, before, before_digest):
    reference = read(folder / "BEFORE_DB_REFERENCE.json")
    target = Path(reference["path"])
    if not target.is_absolute():
        target = folder / target
    require(target.resolve() == (batch / "BEFORE_DB.json").resolve(),
            "cell initial-state reference is not the common frozen initial DB")
    require(reference["file_sha256"] == expected_sha and reference["canonical_sha256"] == before_digest,
            "cell initial-state reference hash differs")
    require(reference["fresh_native_initial_state_verified"] is True, "native fresh initial state was not verified")
    require(not (folder / "BEFORE_DB.json").exists(), "unexpected independent initial DB alongside reference")
    return before


def independent_counts(ids, categories, actual):
    counts = {
        "selected_candidate_count": len(ids),
        "eligible_count": sum(c == "eligible" for c in categories.values()),
        "ineligible_count": sum(c == "ineligible" for c in categories.values()),
        "unresolved_candidate_count": sum(c.startswith("unresolved") for c in categories.values()),
        "eligible_completed": sum(categories[rid] == "eligible" for rid in actual),
        "ineligible_executed": sum(categories[rid] == "ineligible" for rid in actual),
        "unresolved_executed": sum(categories[rid].startswith("unresolved") for rid in actual),
    }
    counts["eligible_missed"] = counts["eligible_count"] - counts["eligible_completed"]
    return counts


def audit_cell(primitives, batch, case, arm, before, before_sha, before_digest):
    folder = batch / (case["case_id"] + "__" + arm)
    before = shared_before(folder, batch, before_sha, before, before_digest)
    after = read(folder / "AFTER_DB.json.gz")
    require(read(folder / "CASE.json") == case, "cell original case differs from freeze")
    require(case.get("task_id") is None, "controlled record request was labelled an official task")
    result = read(folder / "RESULT.json")
    require(result["case_id"] == case["case_id"] and result["arm"] == arm, "result cell identity differs")
    require(not result.get("execution_error") and not result.get("cell_error"), "native cell execution failed")
    require(result.get("evaluation_returncode", 0) == 0, "native replay failed")
    actor, resolution = read(folder / "ACTOR_RESULT.json"), read(folder / "RESOLUTION.json")
    evaluation = read(folder / "CASE_EVALUATION.json")
    native = result["native_evaluation"]
    require(isinstance(native, dict), "missing generic native replay")
    require(read(folder / "NATIVE_REPLAY.json") == native, "native replay artifact differs from result")
    require(not any(key in native for key in ("adapter_composed_native_reward", "reward", "task_id")),
            "controlled replay contains an official-task/reward claim")
    calls, messages, confirmations = (read(folder / (name + ".json"))
                                      for name in ("TOOL_CALLS", "MESSAGES", "CONFIRMATIONS"))
    ids, unresolved_selector = primitives.selected(case["request"], before)
    reason = case["request"]["cancellation"]["reason"]
    categories = {rid: primitives.category(before["reservations"][rid], reason, before) for rid in ids}
    require(resolution["original_request"] == case["request"], "resolver lost the original selector")
    require((resolution["status"] != "resolved") == unresolved_selector,
            "shared resolver differs from independent original selection")
    require(set(resolution["selected_ids"]) == set(ids), "actor-resolved IDs differ from original selector")
    actual = primitives.reconstruct(case["request"], before, after, calls, messages, confirmations)
    require(set(actual) <= set(ids) and len(actual) == len(set(actual)), "unselected or repeated cancellation")
    require(evaluation["original_request"] == case["request"] and evaluation["metrics_valid"],
            "stored evaluator original input or effect integrity failed")
    require(evaluation["selected_ids"] == ids, "stored evaluator selected a different original object")
    require(len(evaluation["candidates"]) == len(ids)
            and categories == {row["reservation_id"]: row["category"] for row in evaluation["candidates"]},
            "candidate categories differ from independent initial facts")
    counts = independent_counts(ids, categories, actual)
    require(all(evaluation[key] == value for key, value in counts.items()),
            "stored counts differ from independently reconstructed effects")
    require(evaluation["unresolved_selector"] == unresolved_selector, "unresolved selector was relabelled")
    require(evaluation["audit"]["state"]["exact_native_effect_state"], "earlier audit rejects full native effect state")
    require(all(attempt["explicit_confirmation"] for attempt in evaluation["audit"]["attempts"]),
            "earlier audit found a missing explicit confirmation")
    require(native["all_recorded_tool_responses_reproduced"] is True
            and native["actor_final_db_match_verified"] is True, "generic native replay did not reproduce effects")
    # Native DB.get_hash() uses json.dumps(sort_keys=True, default=str), including
    # its default whitespace/ASCII escaping. Reproduce this hash without import.
    native_after_hash = hashlib.sha256(json.dumps(after, sort_keys=True, default=str).encode()).hexdigest()
    require(native["actor_final_db_hash"] == native["replay_final_db_hash"] == native_after_hash
            and native["initial_db_match_verified"] is True
            and native["recorded_tool_call_count"] == len(calls), "native replay hashes/count do not bind to artifacts")
    require(native["native_full_task_evaluation_applicable"] is False
            and native["official_task_score"] is None and native["model_calls"] == 0,
            "generic replay was assigned a task score or model work")
    require(result["native_calls"] == len(calls) and result["native_writes"] == len(actual)
            and result["native_errors"] == 0, "runner counts differ from actual transcript")
    require(result["case_evaluation"] == evaluation, "result embeds a different independent evaluation")
    require(result["model_calls"] == 0 and result["model_api_cost_usd"] == 0
            and result["full_task_success_established"] is False
            and result["native_receipt_registered"] is False, "study boundary/result provenance changed")
    gate = primitives.audit_gate(folder, arm, actor, ids, categories, before, resolution) if arm in GATED else None
    if gate:
        require(Counter(actual) == Counter(gate["allowed_ids"]), "native writes differ from stored allowed/armed actions")
    else:
        require(not actor.get("permissions") and not (folder / "permission.sqlite").exists(),
                "non-ECRC arm acquired a hidden permission layer")
    expected_stage_complete = bool(ids) and not any((unresolved_selector,
        counts["unresolved_candidate_count"], counts["eligible_missed"],
        counts["ineligible_executed"], counts["unresolved_executed"]))
    require(evaluation["stage_actions_safe_and_complete"] is expected_stage_complete,
            "stage completion does not retain unresolved, missed or unsafe work")
    row = {"case_id": case["case_id"], "user_id": case["request"]["user_id"],
           "reason": reason, "arm": arm, "audit_pass": True,
           "native_calls": len(calls), "writes": len(actual), "selected_ids": ids,
           "actual_cancelled_ids": actual, "categories": categories,
           "unresolved_selector": unresolved_selector,
           "unresolved_or_transfer_count": sum(c == "unresolved_or_transfer" for c in categories.values()),
           "unresolved_required_information_count": sum(c == "unresolved_required_information" for c in categories.values()),
           "stage_actions_safe_and_complete": evaluation["stage_actions_safe_and_complete"],
           "audit_violations": evaluation["audit"]["violations"], **counts}
    return {"after": after, "actor": actor, "resolution": resolution, "gate": gate, "row": row}


def compare_paired_inputs(data):
    full, no_claim = data[ARMS[1]]["gate"], data[ARMS[3]]["gate"]
    expected = deepcopy(full["policy"])
    claim = next(rule for rule in expected["claim_rules"] if rule["claim_id"] == "cancel_booking")
    require(claim["required_evidence_types"].count("cancellation_eligible") == 1,
            "full policy lost its positive eligibility dependency")
    claim["required_evidence_types"].remove("cancellation_eligible")
    require(no_claim["policy"] == expected, "claim ablation changed an additional policy field")
    require(no_claim["input_by_rid"] == full["input_by_rid"], "domain evidence/proposal inputs differ between gates")
    for rid, raw in no_claim["raw_by_rid"].items():
        restored = deepcopy(raw)
        restored["policy"] = full["policy"]
        require(restored == full["raw_by_rid"][rid], "claim ablation changed an additional request field")
    require(full["configuration"]["class"] == "ScopeGate" and full["configuration"]["core_class"] == "Adapter",
            "full arm replaced the frozen runtime classes")
    require(no_claim["configuration"]["class"] == "WithoutClaimEvidenceRequirementGate"
            and no_claim["configuration"]["core_class"] == "Adapter", "claim arm changed runtime classes")
    direct = data[ARMS[0]]
    require(all(cell["resolution"] == direct["resolution"] for cell in data.values()), "resolution differs across arms")
    require(all(data[arm]["actor"].get("candidates") == direct["actor"].get("candidates") for arm in GATED),
            "shared direct/gated candidate proposals differ")
    return {"only_declared_claim_dependency_changed": True, "same_resolution": True,
            "domain_evidence_and_proposals_identical": True,
            "rules_full_after_db_equal": data[ARMS[2]]["after"] == data[ARMS[1]]["after"],
            "claim_off_direct_after_db_equal": data[ARMS[3]]["after"] == direct["after"]}


def public_strings(value, location="user_scenario"):
    if isinstance(value, str):
        yield location, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from public_strings(child, location + "." + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from public_strings(child, f"{location}[{index}]")


def audit_public_exclusions():
    # Project immediately onto public fields; no evaluation_criteria/gold field
    # is queried or returned. Task IDs are only population accounting here.
    tasks = [{"task_id": str(row["id"]), "user_scenario": row["user_scenario"]}
             for row in read(VENDOR / "data/tau2/domains/airline/tasks.json")]
    split = read(VENDOR / "data/tau2/domains/airline/split_tasks.json")
    expected = {str(i) for key in ("train", "test") for i in split[key]}
    require(len(tasks) == 50 and {row["task_id"] for row in tasks} == expected,
            "official public scenario population differs from pinned 50")
    pattern = re.compile(r"\b[a-z]+(?:_[a-z]+)+_[0-9]+\b")
    evidence = []
    for task in sorted(tasks, key=lambda item: int(item["task_id"])):
        matches = [{"source_field": location, "user_id": match.group(0)}
                   for location, content in public_strings(task["user_scenario"])
                   for match in pattern.finditer(content)]
        users = sorted({match["user_id"] for match in matches})
        require(len(users) == 1, "public scenario account is absent or ambiguous: " + task["task_id"])
        evidence.append({"task_id": task["task_id"], "user_ids": users, "matches": matches})
    return sorted({uid for row in evidence for uid in row["user_ids"]}), evidence


def audit_runtime_exclusions(cohort, frozen_at):
    paths = [Path(value).resolve() for value in cohort["runtime_exposure_files"]]
    require(len(paths) == len(set(paths)) and paths == sorted(paths), "duplicate/unordered prior runtime source list")
    evidence = []
    for path in paths:
        relative = path.relative_to(PILOTS)
        require(relative.parts[0].startswith("ecrc_") and relative.parts[0] != ROOT.name
                and "runs" in relative.parts and "vendor" not in relative.parts
                and path.name in {"MESSAGES.json", "TOOL_CALLS.json"}, "unexpected historical exposure source")
        require(cohort["source_files"].get(str(path)) == sha(path), "historical exposure file not hash-bound")
        rows = read(path)
        require(isinstance(rows, list), "historical transcript is not a list")
        if path.name == "TOOL_CALLS.json":
            calls = [(f"[{index}]", call) for index, call in enumerate(rows)]
        else:
            calls = [(f"[{index}].tool_calls[{offset}]", call)
                     for index, message in enumerate(rows)
                     for offset, call in enumerate(message.get("tool_calls") or [])]
        matched = []
        for location, call in calls:
            function = call.get("function") if isinstance(call.get("function"), dict) else call
            if function.get("name", function.get("tool")) != "get_user_details":
                continue
            arguments = function.get("arguments")
            arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
            uid = arguments.get("user_id") if isinstance(arguments, dict) else None
            require(isinstance(uid, str) and uid, "historical native account query lacks user_id")
            matched.append({"location": location, "user_id": uid})
        evidence.append({"path": str(path), "user_ids": sorted({row["user_id"] for row in matched}),
                         "get_user_details_calls": matched})
    # Do not extend the cohort with later exposure. Existing earlier logs absent
    # from the archived list are an integrity finding, not a new sampling input.
    cutoff = datetime.fromisoformat(frozen_at).timestamp()
    omitted = []
    for project in PILOTS.glob("ecrc_*"):
        if not project.is_dir() or project.resolve() == ROOT.resolve():
            continue
        for name in ("TOOL_CALLS.json", "MESSAGES.json"):
            for path in project.rglob(name):
                parts = path.relative_to(project).parts
                if "runs" in parts and "vendor" not in parts and path.stat().st_mtime <= cutoff:
                    if path.resolve() not in paths:
                        omitted.append(str(path.resolve()))
    require(not omitted, "pre-freeze runtime transcripts missing from exposure manifest: " + repr(omitted))
    return sorted({uid for row in evidence for uid in row["user_ids"]}), evidence


def selection_hash(*identifiers):
    payload = json.dumps([SEED, *identifiers], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit_cohort(freeze, before):
    cohort, requests = freeze["cohort"], freeze["requests"]
    require(read(ROOT / "COHORT_SELECTION.json") == cohort and read(ROOT / "REQUESTS.json") == requests,
            "current cohort/requests differs from pre-run freeze")
    require(cohort["seed"] == SEED and cohort["account_limit"] == 100, "sampling seed/resource scope changed")
    require(cohort["templates"] == requests["templates"] == TEMPLATES, "reason templates changed")
    official, official_evidence = audit_public_exclusions()
    exposed, exposure_evidence = audit_runtime_exclusions(cohort, freeze["recorded_at"])
    excluded = set(official) | set(exposed)
    require(cohort["official_excluded_accounts"] == official
            and cohort["official_exclusion_evidence"] == official_evidence, "public account exclusions differ")
    require(cohort["runtime_excluded_accounts"] == exposed
            and cohort["runtime_exposure_evidence"] == exposure_evidence, "runtime account exclusions differ")
    require(cohort["excluded_accounts_union"] == sorted(excluded), "combined exclusion set differs")
    native = read(VENDOR / "data/tau2/domains/airline/db.json")
    # The cohort reconstruction below consumes ID/association fields only. The
    # full state equality is a separate postrun authenticity check, not sampling.
    users = {key: {"user_id": value.get("user_id"), "reservations": value.get("reservations")}
             for key, value in native["users"].items()}
    reservations = {key: {"reservation_id": value.get("reservation_id"), "user_id": value.get("user_id")}
                    for key, value in native["reservations"].items()}
    require(len(users) == 500 and len(reservations) == 2000, "native sampling population changed")
    pool, issues, usable, usable_excluded = [], [], [], []
    for key, user in sorted(users.items()):
        uid, associated = user["user_id"], user["reservations"]
        if not isinstance(uid, str) or uid != key or not isinstance(associated, list):
            issues.append({"record_key": key, "reason": "invalid_user_identity_or_reservation_list"})
            continue
        valid = []
        for rid in associated:
            if not isinstance(rid, str):
                issues.append({"user_id": uid, "reason": "non_string_associated_reservation_id"})
                continue
            record = reservations.get(rid)
            if not record or record["reservation_id"] != rid or record["user_id"] != uid:
                issues.append({"user_id": uid, "reservation_id": rid, "reason": "missing_or_mismatched_ownership_link"})
            else:
                valid.append(rid)
        valid = sorted(set(valid))
        if not valid:
            issues.append({"user_id": uid, "reason": "no_structurally_owned_reservation"})
            continue
        usable.append(uid)
        if uid in excluded:
            usable_excluded.append(uid)
            continue
        choices = sorted([{"reservation_id": rid, "selection_hash": selection_hash(uid, rid)} for rid in valid],
                         key=lambda item: (item["selection_hash"], item["reservation_id"]))
        pool.append({"user_id": uid, "account_selection_hash": selection_hash(uid), "owned_reservation_choices": choices,
                     "selected_reservation_id": choices[0]["reservation_id"],
                     "reservation_selection_hash": choices[0]["selection_hash"]})
    pool.sort(key=lambda item: (item["account_selection_hash"], item["user_id"]))
    for rank, item in enumerate(pool, 1):
        item["account_rank"] = rank
    chosen = pool[:100]
    require(cohort["all_available_accounts_ranked"] == pool and cohort["selected_accounts"] == chosen,
            "cohort differs from independent outcome-blind ID hash ordering")
    require(cohort["structural_issues"] == issues, "structural exclusions were changed or hidden")
    require(cohort["excluded_ids_absent_from_native_users"] == sorted(excluded - set(users)),
            "absent excluded accounts differ")
    expected_counts = {"native_users": len(users), "native_reservations": len(reservations),
        "official_tasks": len(official_evidence), "official_user_ids": len(official),
        "runtime_files": len(exposure_evidence), "runtime_queried_user_ids": len(exposed),
        "union_excluded_user_ids": len(excluded), "structurally_usable_accounts": len(usable),
        "structurally_usable_excluded_accounts": len(usable_excluded), "available_accounts": len(pool),
        "selected_accounts": len(chosen), "scripted_requests": len(chosen) * len(REASONS)}
    require(cohort["counts"] == expected_counts and cohort["fewer_than_100_available"] == (len(pool) < 100),
            "cohort source/selected population counts differ")
    require(len(chosen) == 100 and len({row["selected_reservation_id"] for row in chosen}) == 100,
            "declared 100-account/100-record resource scope not present")
    require(not {row["user_id"] for row in chosen} & excluded, "selected account was previously exposed by declared criterion")
    expected_cases = []
    for item in chosen:
        uid, rid, rank = item["user_id"], item["selected_reservation_id"], item["account_rank"]
        for template in TEMPLATES:
            reason = template["reason"]
            expected_cases.append({"case_id": f"record_{rank:03d}_{reason}", "task_id": None,
                "kind": "controlled_native_record_request", "native_full_goal_in_scope": False,
                "account_rank": rank, "paired_account_id": uid, "paired_reservation_id": rid,
                "reason_template": reason, "request": {"user_id": uid,
                    "user_statement": template["statement"].format(reservation_id=rid),
                    "cancellation": {"selector": {"kind": "ids", "ids": [rid]}, "reason": reason}}})
    require(requests["cases"] == expected_cases and len(expected_cases) == 300,
            "requests differ from exact three-reason/one-record deterministic construction")
    require(requests["selected_accounts"] == requests["unique_selected_reservations"] == 100,
            "request account/reservation denominators changed")
    # These are the two nullable defaults in the pinned airline DB models, not
    # outcome-dependent modifications. Numeric int/float JSON values compare by
    # value; hash checks separately bind the actual serialized native artifacts.
    for row in native["users"].values():
        row["address"].setdefault("address2", None)
    for row in native["reservations"].values():
        row.setdefault("status", None)
    require(before == native, "shared native BEFORE_DB differs from pinned original DB plus declared model defaults")
    return {"audit_pass": True, **expected_counts, "three_reasons_per_record": True,
            "exact_deterministic_cohort_and_requests": True, "public_and_runtime_exclusions_reconstructed": True,
            "before_matches_pinned_native_source": True, "selected_account_ids": [row["user_id"] for row in chosen],
            "selected_reservation_ids": [row["selected_reservation_id"] for row in chosen]}


def source_integrity(freeze):
    sources, vendor = freeze["sources"], freeze["vendor_sources"]
    changed = [path for path, expected in sources.items() if not Path(path).is_file() or sha(path) != expected]
    changed_vendor = [path for path, expected in vendor.items()
                      if not (VENDOR / path).is_file() or sha(VENDOR / path) != expected]
    prior = read(PILOTS / "ecrc_component_ablation_dev_2026-09-15/review/prerun_01/FREEZE.json")
    missing_prior = [path for path, expected in prior["sources"].items() if sources.get(path) != expected]
    require(vendor == prior["vendor_sources"] and len(vendor) == 1570,
            "vendor manifest differs from the original pinned 1570-file tree")
    required = [ROOT / name for name in ("run_coverage.py", "prepare_cohort.py", "PROTOCOL.md",
                                         "REQUESTS.json", "COHORT_SELECTION.json")]
    required.append(PRIOR_AUDIT)
    missing_current = [str(path.resolve()) for path in required if str(path.resolve()) not in sources]
    missing_selection = [path for path, expected in freeze["cohort"]["source_files"].items()
                         if sources.get(path) != expected]
    require(freeze["cohort"]["selection_script_sha256"] == sha(freeze["cohort"]["selection_script"]),
            "cohort selection script hash differs")
    return {"source_files_checked": len(sources), "vendor_files_checked": len(vendor),
            "changed_sources": changed, "changed_vendor_sources": changed_vendor,
            "missing_or_altered_prior_source_freeze": missing_prior,
            "missing_current_frozen_sources": missing_current, "missing_selection_sources": missing_selection,
            "audit_pass": not any((changed, changed_vendor, missing_prior, missing_current, missing_selection))}


def failure_row(primitives, case, arm, before, exc, folder):
    """Retain a row for every planned cell; unknown effects are never zeroes."""
    ids, unresolved = primitives.selected(case["request"], before)
    reason = case["request"]["cancellation"]["reason"]
    categories = {rid: primitives.category(before["reservations"][rid], reason, before) for rid in ids}
    counts = independent_counts(ids, categories, [])
    for key in ("eligible_completed", "eligible_missed", "ineligible_executed", "unresolved_executed"):
        counts[key] = None
    retained = {}
    for name in ("FAILED_RESULT", "RESULT", "CASE_EVALUATION"):
        path = folder / (name + ".json")
        if path.exists():
            try:
                value = read(path)
                if name == "CASE_EVALUATION":
                    retained["stored_audit_violations"] = value.get("audit", {}).get("violations")
                    retained["stored_effect_evidence_issues"] = value.get("effect_evidence_issues")
                else:
                    retained[name.lower()] = {key: value.get(key) for key in
                        ("cell_error", "execution_error", "native_errors", "evaluation_returncode")}
            except Exception as read_error:
                retained[name.lower() + "_read_error"] = str(read_error)
    return {"case_id": case["case_id"], "user_id": case["request"]["user_id"], "reason": reason,
            "arm": arm, "audit_pass": False, "error_type": type(exc).__name__, "error": str(exc),
            "native_calls": None, "writes": None, "selected_ids": ids, "actual_cancelled_ids": None,
            "categories": categories, "unresolved_selector": unresolved,
            "unresolved_or_transfer_count": sum(c == "unresolved_or_transfer" for c in categories.values()),
            "unresolved_required_information_count": sum(c == "unresolved_required_information" for c in categories.values()),
            "stage_actions_safe_and_complete": None, "retained_failure_evidence": retained, **counts}


def aggregate_rows(rows, cases, by_reason=False):
    output = []
    reason_groups = REASONS if by_reason else (None,)
    fields = (*COUNT_KEYS, "native_calls", "writes", "unresolved_selector", "unresolved_or_transfer_count",
              "unresolved_required_information_count", "stage_actions_safe_and_complete")
    for arm in ARMS:
        for reason in reason_groups:
            group = [row for row in rows if row["arm"] == arm and (reason is None or row["reason"] == reason)]
            planned = [case for case in cases if reason is None or case["request"]["cancellation"]["reason"] == reason]
            output.append({"arm": arm, "reason": reason, "planned_request_cells": len(planned),
                "retained_request_cells": len(group), "verified_cells": sum(row["audit_pass"] for row in group),
                "unverified_cells": sum(not row["audit_pass"] for row in group),
                "unique_accounts": len({case["request"]["user_id"] for case in planned}),
                "unique_records": len({rid for case in planned for rid in case["request"]["cancellation"]["selector"]["ids"]}),
                "eligible_unique_accounts": len({row["user_id"] for row in group if row["eligible_count"]}),
                "eligible_unique_reservations": len({rid for row in group for rid, category in row["categories"].items()
                                                     if category == "eligible"}),
                # A known subtotal is accompanied by its missing-value count.
                # Only the zero-missing-value case establishes a complete total.
                **{key: sum(row[key] for row in group if row.get(key) is not None) for key in fields},
                "unknown_cell_values_by_metric": {key: sum(row.get(key) is None for row in group) for key in fields},
                "effect_totals_complete": all(row["audit_pass"] for row in group) and len(group) == len(planned)})
    return output


def describe_candidate_population(primitives, cases, before):
    """Descriptive pre-action strata; never outcome-based cohort selection."""
    entries = []
    for case in cases:
        reason = case["request"]["cancellation"]["reason"]
        ids, unresolved = primitives.selected(case["request"], before)
        for rid in ids:
            reservation = before["reservations"][rid]
            category = primitives.category(reservation, reason, before)
            bases = []
            if category == "eligible":
                age = (primitives.NOW - datetime.fromisoformat(reservation["created_at"])).total_seconds()
                if 0 <= age <= 86400:
                    bases.append("within_24_hours")
                if "cancelled" in primitives.statuses(reservation, before):
                    bases.append("airline_cancelled")
                if reservation.get("cabin") == "business":
                    bases.append("business_cabin")
                if reservation.get("insurance") == "yes" and reason in {"health", "weather"}:
                    bases.append("insured_" + reason)
            entries.append({"case_id": case["case_id"], "user_id": case["request"]["user_id"],
                            "reservation_id": rid, "reason": reason, "category": category,
                            "unresolved_selector": unresolved, "positive_eligibility_bases": bases})
    category_groups, basis_groups = [], []
    for reason in (None, *REASONS):
        selected = [entry for entry in entries if reason is None or entry["reason"] == reason]
        for category in sorted({entry["category"] for entry in entries}):
            group = [entry for entry in selected if entry["category"] == category]
            category_groups.append({"reason": reason, "category": category, "request_contexts": len(group),
                "unique_accounts": len({entry["user_id"] for entry in group}),
                "unique_reservations": len({entry["reservation_id"] for entry in group})})
        for basis in sorted({basis for entry in entries for basis in entry["positive_eligibility_bases"]}):
            group = [entry for entry in selected if basis in entry["positive_eligibility_bases"]]
            basis_groups.append({"reason": reason, "positive_eligibility_basis": basis, "request_contexts": len(group),
                "unique_accounts": len({entry["user_id"] for entry in group}),
                "unique_reservations": len({entry["reservation_id"] for entry in group})})
    return {"candidate_contexts": entries, "category_reason_aggregate": category_groups,
            "positive_eligibility_basis_reason_aggregate": basis_groups,
            "basis_groups_may_overlap": True,
            "interpretation": "Counts describe the frozen records, not observed customer frequencies; positive basis strata overlap and must not be summed."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, default=ROOT / "runs/batch_01")
    parser.add_argument("--out", type=Path, default=HERE / "REVIEW.json")
    args = parser.parse_args()
    require(not args.out.exists(), "review already exists; preserve/version it before choosing a new output path")
    batch = args.batch.resolve()
    primitives = load_independent_primitives()
    freeze, summary = read(batch / "FREEZE.json"), read(batch / "SUMMARY.json")
    before_file = batch / "BEFORE_DB.json"
    before_sha, before = sha(before_file), read(before_file)
    before_digest = digest(before)
    cases = freeze["requests"]["cases"]
    failures, rows, pairs, permissions = [], [], [], []
    integrity, cohort_review = None, None
    try:
        require(tuple(freeze["arms"]) == ARMS, "declared four-arm grid changed")
        integrity = source_integrity(freeze)
        require(integrity["audit_pass"], "frozen source/vendor integrity failed")
        cohort_review = audit_cohort(freeze, before)
        require(summary["stage"] == "controlled_native_record_coverage" and summary["full_benchmark_run"] is False,
                "summary study identity changed")
        require(summary["sources_unchanged"] is True and summary["model_calls"] == summary["model_api_cost_usd"] == 0,
                "runner reports source drift or model work")
    except Exception as exc:
        failures.append({"scope": "freeze_cohort_and_source_integrity", "error_type": type(exc).__name__, "error": str(exc)})
    expected_grid = [(case["case_id"], arm) for case in cases for arm in ARMS]
    recorded_keys = [(row["case_id"], row["arm"]) for row in summary["rows"]]
    if Counter(recorded_keys) != Counter(expected_grid) or len(expected_grid) != 1200:
        failures.append({"scope": "complete_grid", "error": "summary does not retain the exact planned 1200 cells"})
    summary_lookup = {(row["case_id"], row["arm"]): row for row in summary["rows"]}
    expected_folders = {case_id + "__" + arm for case_id, arm in expected_grid}
    unexpected_folders = [path.name for path in batch.iterdir() if path.is_dir() and "__" in path.name and path.name not in expected_folders]
    if unexpected_folders:
        failures.append({"scope": "complete_grid", "error": "undeclared cell folders", "folders": unexpected_folders})
    for index, case in enumerate(cases):
        data = {}
        for arm in ARMS:
            folder = batch / (case["case_id"] + "__" + arm)
            try:
                cell = audit_cell(primitives, batch, case, arm, before, before_sha, before_digest)
                require(summary_lookup[(case["case_id"], arm)] == read(folder / "RESULT.json"),
                        "summary row differs from the actual cell result")
                data[arm] = cell
                rows.append(cell["row"])
                if cell["gate"]:
                    permissions.extend({"case_id": case["case_id"], "user_id": case["request"]["user_id"],
                                        "reason": case["request"]["cancellation"]["reason"], "arm": arm, **entry}
                                       for entry in cell["gate"]["permissions"])
            except Exception as exc:
                rows.append(failure_row(primitives, case, arm, before, exc, folder))
                failures.append({"case_id": case["case_id"], "arm": arm, "error_type": type(exc).__name__, "error": str(exc)})
        if len(data) == len(ARMS):
            try:
                comparison = compare_paired_inputs(data)
                pairs.append({"case_id": case["case_id"], "user_id": case["request"]["user_id"],
                              "reason": case["request"]["cancellation"]["reason"], **comparison})
            except Exception as exc:
                failures.append({"case_id": case["case_id"], "scope": "paired_inputs_and_configuration",
                                 "error_type": type(exc).__name__, "error": str(exc)})
        if (index + 1) % 25 == 0:
            print(json.dumps({"audited_requests": index + 1, "planned_requests": len(cases),
                              "retained_cells": len(rows), "audit_findings": len(failures)}), flush=True)
    if sha(before_file) != before_sha:
        failures.append({"scope": "read_only_integrity", "error": "shared original BEFORE_DB changed during audit"})
    try:
        final_integrity = source_integrity(freeze)
        require(final_integrity == integrity and final_integrity["audit_pass"], "sources changed during audit")
    except Exception as exc:
        failures.append({"scope": "final_source_integrity", "error_type": type(exc).__name__, "error": str(exc)})
    aggregate = aggregate_rows(rows, cases)
    by_reason = aggregate_rows(rows, cases, by_reason=True)
    population = describe_candidate_population(primitives, cases, before)
    passed = not failures and len(rows) == 1200 and len(pairs) == 300 and all(row["audit_pass"] for row in rows)
    review = {"recorded_at": datetime.now(timezone.utc).isoformat(), "audit_script_sha256": sha(Path(__file__)),
        "audit_script_timing": "postrun wrapper not included in the pre-run freeze; do not represent it as preregistered",
        "frozen_independent_primitives": {"path": str(PRIOR_AUDIT), "sha256": PRIOR_AUDIT_SHA256},
        "review_type": "independent_read_only_controlled_native_record_coverage_no_new_episodes",
        "batch": str(batch), "before_file_sha256": before_sha, "before_canonical_sha256": before_digest,
        "source_integrity": integrity, "cohort_audit": cohort_review, "failures": failures,
        "source_files_checked": len(freeze["sources"]), "vendor_files_checked": len(freeze["vendor_sources"]),
        "rows": rows, "aggregate": aggregate, "reason_aggregate": by_reason, "pairs": pairs, "permissions": permissions,
        "candidate_population": population,
        "technical_integrity_pass": passed, "planned_cells": 1200, "planned_request_contexts": 300,
        "planned_individual_accounts": 100, "planned_individual_reservations": 100,
        "model_calls": 0, "model_api_cost_usd": 0, "full_task_success_established": False,
        "official_benchmark_score": None,
        "limitations": [
            "Controlled author-written requests over pinned native records, not official benchmark tasks or a new unseen dataset.",
            "Three reason contexts share one account/reservation; cells are paired opportunities, not 1200 independent samples.",
            "Known-invalid and missing-information executions remain measured outcomes, not automatic technical-integrity failures.",
            "Already-flown/transfer-required candidates remain unresolved even if no cancellation occurs.",
            "A technical pass means that recorded selection, effects and permission state are verifiable; it does not mean that an arm performs well.",
            "All planned cells remain in the report. Missing effect evidence produces unknown metric values and visible failures, never successful refusals.",
            "No expected winning arm or completion count is hard-coded; direct eligible completions and conventional-rule ties are retained.",
            "This isolates qualification-to-permission integration; capacity, metadata faults, recovery and atomic native receipts are not tested here.",
            "Known account exclusions do not establish that authors never accessed the global native database.",
            "Generic replay results are verified against recorded responses and reconstructed full DB; this postrun auditor does not run native tools again."
        ]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(review, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"technical_integrity_pass": passed, "aggregate": aggregate,
                      "reason_aggregate": by_reason, "permission_count": len(permissions),
                      "failure_count": len(failures), "first_failures": failures[:20]}, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
