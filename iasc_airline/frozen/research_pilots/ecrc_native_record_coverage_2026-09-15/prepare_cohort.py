"""Freeze an outcome-blind native-record cohort and three scripted requests.

This is controlled coverage over native records, not official benchmark tasks.
Only account/reservation identifiers and ownership links participate in sampling.
The initial generation discovers prior runtime logs. Verification uses that exact
archived file list, so later experiments cannot silently change this cohort.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
PILOTS = ROOT.parent
NATIVE = PILOTS / "ecrc_airline_pilot_2026-09-15"
DATA = NATIVE / "vendor/tau2-bench/data/tau2/domains/airline"
SEED = "ecrc-native-record-coverage-v1"
MAX_ACCOUNTS = 100
SOURCE_COMMIT = "2174a603f6d014ef94473ffa95957f6ce27100db"
USER_ID_RE = re.compile(r"\b[a-z]+(?:_[a-z]+)+_[0-9]+\b")
TEMPLATES = [
    {"reason": "health", "statement": "Cancel reservation {reservation_id} because I am sick."},
    {"reason": "other", "statement": "Cancel reservation {reservation_id}. I booked it by mistake."},
    {"reason": "unspecified", "statement": "Cancel reservation {reservation_id}."},
]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rank_hash(*identifiers):
    """Hash a canonical JSON array containing the seed and the identifiers."""
    payload = json.dumps([SEED, *identifiers], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def strings(value, location="user_scenario"):
    if isinstance(value, str):
        yield location, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from strings(child, location + "." + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from strings(child, f"{location}[{index}]")


def official_accounts():
    """Read public scenario fields; never inspect task evaluator or gold fields."""
    projected = [
        {"task_id": str(task["id"]), "user_scenario": task["user_scenario"]}
        for task in read(DATA / "tasks.json")
    ]
    split = read(DATA / "split_tasks.json")
    population_ids = set(split["train"]) | set(split["test"])
    if len(projected) != 50 or {t["task_id"] for t in projected} != population_ids:
        raise RuntimeError("Unexpected official task population; do not silently alter selection")
    evidence = []
    for task in sorted(projected, key=lambda row: int(row["task_id"])):
        matches = [
            {"source_field": location, "user_id": match.group(0)}
            for location, value in strings(task["user_scenario"])
            for match in USER_ID_RE.finditer(value)
        ]
        users = sorted({match["user_id"] for match in matches})
        if len(users) != 1:
            raise RuntimeError("Unexpected public user-ID extraction for task " + task["task_id"])
        evidence.append({"task_id": task["task_id"], "user_ids": users, "matches": matches})
    return sorted({user for row in evidence for user in row["user_ids"]}), evidence


def discover_runtime_files():
    """Find actual saved runtime transcripts, excluding vendors and this cohort."""
    found = []
    for project in sorted(PILOTS.glob("ecrc_*")):
        if not project.is_dir() or project.resolve() == ROOT.resolve():
            continue
        for filename in ("TOOL_CALLS.json", "MESSAGES.json"):
            for path in project.rglob(filename):
                parts = path.relative_to(project).parts
                if "runs" in parts and "vendor" not in parts:
                    found.append(path.resolve())
    return sorted(set(found))


def exposure_from_files(files):
    """Inspect only actual get_user_details call arguments, not tool responses."""
    evidence = []
    for path in files:
        rows = read(path)
        if not isinstance(rows, list):
            raise RuntimeError("Runtime transcript is not a list: " + str(path))
        calls = []
        if path.name == "TOOL_CALLS.json":
            calls = [(f"[{index}]", row) for index, row in enumerate(rows)]
        elif path.name == "MESSAGES.json":
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise RuntimeError("Malformed runtime message: " + str(path))
                for call_index, call in enumerate(row.get("tool_calls") or []):
                    calls.append((f"[{index}].tool_calls[{call_index}]", call))
        else:
            raise RuntimeError("Unexpected exposure file name: " + str(path))
        matched = []
        for location, call in calls:
            if not isinstance(call, dict):
                raise RuntimeError("Malformed runtime tool call: " + str(path))
            # Saved airline ToolCall records use name/arguments. JSON function
            # wrappers are handled as a schema variant, without reading output.
            function = call.get("function") if isinstance(call.get("function"), dict) else call
            if function.get("name", function.get("tool")) != "get_user_details":
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            user = arguments.get("user_id") if isinstance(arguments, dict) else None
            if not isinstance(user, str) or not user:
                raise RuntimeError("get_user_details lacks a user_id: " + str(path))
            matched.append({"location": location, "user_id": user})
        evidence.append({"path": str(path), "user_ids": sorted({m["user_id"] for m in matched}),
                         "get_user_details_calls": matched})
    users = sorted({user for item in evidence for user in item["user_ids"]})
    return users, evidence


def structural_projection():
    """Discard all native values except IDs and declared ownership association."""
    database = read(DATA / "db.json")
    # No status, time, cabin, insurance, balance, DOB, or policy field is read.
    users = {
        key: {"user_id": value.get("user_id"), "reservations": value.get("reservations")}
        for key, value in database["users"].items()
    }
    reservations = {
        key: {"reservation_id": value.get("reservation_id"), "user_id": value.get("user_id")}
        for key, value in database["reservations"].items()
    }
    del database
    if len(users) != 500 or len(reservations) != 2000:
        raise RuntimeError("Unexpected pinned native record population")
    return users, reservations


def build(runtime_files, source_files):
    official, official_evidence = official_accounts()
    exposed, exposure_evidence = exposure_from_files(runtime_files)
    excluded = set(official) | set(exposed)
    users, reservations = structural_projection()
    pool = []
    structural_issues = []
    structurally_valid_excluded = []
    all_structurally_usable_users = []
    for key, user in sorted(users.items()):
        uid = user["user_id"]
        associated = user["reservations"]
        if not isinstance(uid, str) or uid != key or not isinstance(associated, list):
            structural_issues.append({"record_key": key, "reason": "invalid_user_identity_or_reservation_list"})
            continue
        valid = []
        for rid in associated:
            if not isinstance(rid, str):
                structural_issues.append({"user_id": uid, "reason": "non_string_associated_reservation_id"})
                continue
            reservation = reservations.get(rid)
            if (not reservation or reservation["reservation_id"] != rid
                    or reservation["user_id"] != uid):
                structural_issues.append({"user_id": uid, "reservation_id": rid,
                                          "reason": "missing_or_mismatched_ownership_link"})
                continue
            valid.append(rid)
        valid = sorted(set(valid))
        if not valid:
            structural_issues.append({"user_id": uid, "reason": "no_structurally_owned_reservation"})
            continue
        all_structurally_usable_users.append(uid)
        if uid in excluded:
            structurally_valid_excluded.append(uid)
            continue
        ranked_reservations = sorted(
            [{"reservation_id": rid, "selection_hash": rank_hash(uid, rid)} for rid in valid],
            key=lambda row: (row["selection_hash"], row["reservation_id"]),
        )
        pool.append({"user_id": uid, "account_selection_hash": rank_hash(uid),
                     "owned_reservation_choices": ranked_reservations,
                     "selected_reservation_id": ranked_reservations[0]["reservation_id"],
                     "reservation_selection_hash": ranked_reservations[0]["selection_hash"]})
    pool.sort(key=lambda row: (row["account_selection_hash"], row["user_id"]))
    for position, row in enumerate(pool, 1):
        row["account_rank"] = position
    selected = pool[:MAX_ACCOUNTS]
    selection = {
        "schema_version": "controlled_native_record_coverage_v1",
        "source_commit": SOURCE_COMMIT,
        "source_files": source_files,
        "selection_script": str(Path(__file__).resolve()),
        "selection_script_sha256": digest(__file__),
        "seed": SEED,
        "account_limit": MAX_ACCOUNTS,
        "sample_size_basis": "Fixed resource scope of at most 100 different usable accounts, not a prospective statistical power calculation.",
        "selection_rule": {
            "allowed_db_fields": ["users record key", "users.user_id", "users.reservations",
                                  "reservations record key", "reservations.reservation_id", "reservations.user_id"],
            "exclusions": "All user IDs explicitly present in all 50 official public user_scenario fields, plus all get_user_details user_id arguments in saved prior research_pilots/ecrc_*/.../runs/.../{TOOL_CALLS,MESSAGES}.json transcripts, excluding vendor paths and the current coverage project.",
            "structural_eligibility": "User record key equals user_id and at least one user-list reservation exists with matching reservation_id and ownership user_id. Keep every structurally valid association; discard only invalid associations. Do not inspect business eligibility or outcomes.",
            "account_hash": "SHA256(UTF8(JSON([seed,user_id], ensure_ascii=False, separators=(',',':'))))",
            "reservation_hash": "SHA256(UTF8(JSON([seed,user_id,reservation_id], ensure_ascii=False, separators=(',',':'))))",
            "tie_break": "Ascending hash, then ascending identifier string.",
            "sampling": "First min(100, available) accounts by account hash; one structurally owned reservation per account by reservation hash. No replacement or positive-case oversampling.",
            "request_generation": "Generate each health, other, and unspecified template once for the same selected reservation. Retain every template and all outcomes.",
        },
        "counts": {"native_users": len(users), "native_reservations": len(reservations),
                   "official_tasks": len(official_evidence), "official_user_ids": len(official),
                   "runtime_files": len(runtime_files), "runtime_queried_user_ids": len(exposed),
                   "union_excluded_user_ids": len(excluded),
                   "structurally_usable_accounts": len(all_structurally_usable_users),
                   "structurally_usable_excluded_accounts": len(structurally_valid_excluded),
                   "available_accounts": len(pool), "selected_accounts": len(selected),
                   "scripted_requests": len(selected) * len(TEMPLATES)},
        "fewer_than_100_available": len(pool) < MAX_ACCOUNTS,
        "official_excluded_accounts": official,
        "official_exclusion_evidence": official_evidence,
        "runtime_excluded_accounts": exposed,
        "runtime_exposure_files": [str(path) for path in runtime_files],
        "runtime_exposure_evidence": exposure_evidence,
        "excluded_accounts_union": sorted(excluded),
        "excluded_ids_absent_from_native_users": sorted(excluded - set(users)),
        "structural_issues": structural_issues,
        "all_available_accounts_ranked": pool,
        "selected_accounts": selected,
        "templates": TEMPLATES,
        "interpretation": [
            "Native DB records plus author-written request templates: a controlled coverage experiment, not new official benchmark tasks, independent holdout, or real user requests.",
            "One native reservation per selected account; three reason variants share the account and reservation and are paired conditions, not 300 independent account samples.",
            "No model, eligibility function, gold actions, evaluator fields, or business outcomes are used in cohort selection.",
            "The account exclusion audit records known prior public/task/runtime exposure, not a guarantee that records have never been seen by any author.",
            "Every candidate is retained. Missing, expired, invalid, already-completed, unsupported, and adverse cases must remain in reporting after execution.",
        ],
    }
    cases = []
    for row in selected:
        uid, rid = row["user_id"], row["selected_reservation_id"]
        for template in TEMPLATES:
            reason = template["reason"]
            cases.append({"case_id": f"record_{row['account_rank']:03d}_{reason}", "task_id": None,
                          "kind": "controlled_native_record_request",
                          "native_full_goal_in_scope": False,
                          "account_rank": row["account_rank"], "paired_account_id": uid,
                          "paired_reservation_id": rid, "reason_template": reason,
                          "request": {"user_id": uid,
                                      "user_statement": template["statement"].format(reservation_id=rid),
                                      "cancellation": {"selector": {"kind": "ids", "ids": [rid]}, "reason": reason}}})
    requests = {
        "schema_version": "controlled_native_record_requests_v1",
        "source_commit": SOURCE_COMMIT,
        "source_split": "controlled_native_record_coverage_not_official_tasks",
        "source_population_size": len(users),
        "scope": "Initial cancellation module over selected native records and three scripted reason templates; no official task_id or full conversational goal.",
        "selection_basis": "Outcome-blind hash sample of structurally linked records after documented account exclusions; see COHORT_SELECTION.json.",
        "selected_accounts": len(selected), "unique_selected_reservations": len({r['selected_reservation_id'] for r in selected}),
        "sample_size_basis": selection["sample_size_basis"],
        "templates": TEMPLATES, "cases": cases,
        "limitations": selection["interpretation"],
    }
    assert len({row["user_id"] for row in selected}) == len(selected)
    assert len({row["case_id"] for row in cases}) == len(cases)
    assert not ({row["user_id"] for row in selected} & excluded)
    assert all(set(case["request"]) == {"user_id", "user_statement", "cancellation"} for case in cases)
    return selection, requests


def ensure_sources(source_files):
    for path, expected in source_files.items():
        if digest(path) != expected:
            raise RuntimeError("Selection source changed: " + path)


def generate():
    outputs = [ROOT / "COHORT_SELECTION.json", ROOT / "REQUESTS.json"]
    if any(path.exists() for path in outputs):
        raise RuntimeError("Frozen cohort outputs already exist; use --verify, never replace the sample")
    runtime_files = discover_runtime_files()
    paths = [DATA / "db.json", DATA / "tasks.json", DATA / "split_tasks.json", Path(__file__).resolve(), *runtime_files]
    source_files = {str(path.resolve()): digest(path) for path in sorted(set(paths))}
    selection, requests = build(runtime_files, source_files)
    ensure_sources(source_files)
    for path, value in zip(outputs, [selection, requests]):
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps({"generated": True, **selection["counts"], "fewer_than_100_available": selection["fewer_than_100_available"]}), flush=True)


def verify():
    archived_selection = read(ROOT / "COHORT_SELECTION.json")
    archived_requests = read(ROOT / "REQUESTS.json")
    sources = archived_selection["source_files"]
    ensure_sources(sources)
    # New runtime files are intentionally not discovered here: the original
    # source-file snapshot defines exposure before this experiment started.
    files = [Path(path) for path in archived_selection["runtime_exposure_files"]]
    selection, requests = build(files, sources)
    ensure_sources(sources)
    if selection != archived_selection or requests != archived_requests:
        raise RuntimeError("Frozen cohort replay disagrees")
    print(json.dumps({"verified": True, **selection["counts"], "request_sha256": digest(ROOT / "REQUESTS.json"),
                      "selection_sha256": digest(ROOT / "COHORT_SELECTION.json")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Rebuild from the archived pre-run source snapshot without writing")
    arguments = parser.parse_args()
    verify() if arguments.verify else generate()
