"""Create explicit synthetic fixtures; does not invoke actors, tools or evaluators."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from boundary_common import (ROOT, PREVIOUS, DATA, inherited, apply_patch, digest,
                             read, sha, write, within)

NOW = datetime.fromisoformat("2024-05-15T15:00:00")


def replacement(database, operations, keys, value):
    parent = database
    for key in keys[:-1]:
        parent = parent[key]
    old = deepcopy(parent[keys[-1]])
    if old != value:
        operations.append({"path": keys, "before": old, "after": deepcopy(value)})
        parent[keys[-1]] = deepcopy(value)


def build(base, spec, identity):
    """No policy qualification is called; every change follows the published grid."""
    data, operations = deepcopy(base), []
    rid = identity["selected_reservation_id"]
    prefix = ["reservations", rid]
    booking = data["reservations"][rid]
    if len(booking["flights"]) != 1:
        raise ValueError("This fixed template must retain its one original leg")
    flight = booking["flights"][0]["flight_number"]
    for name, value in (("created_at", (NOW - timedelta(seconds=spec["age_seconds"])).isoformat()),
                        ("cabin", spec["cabin"]), ("insurance", spec["insurance"]),
                        ("status", spec["reservation_status"])):
        replacement(data, operations, prefix + [name], value)
    legs = deepcopy(booking["flights"])
    legs[0]["date"] = "2024-05-15" if spec["flight_status"] == "flying" else "2024-05-20"
    replacement(data, operations, prefix + ["flights"], legs)
    day = legs[0]["date"]
    if spec["flight_status"] == "available":
        if data["flights"][flight]["dates"][day]["status"] != "available":
            raise ValueError("Fixed native available-date control no longer available")
    elif spec["flight_status"] == "cancelled":
        replacement(data, operations, ["flights", flight, "dates", day], {"status": "cancelled"})
    elif spec["flight_status"] == "flying":
        replacement(data, operations, ["flights", flight, "dates", day],
                    {"status": "flying", "actual_departure_time_est": "2024-05-15T13:00:00",
                     "estimated_arrival_time_est": "2024-05-15T16:00:00"})
        replacement(data, operations, ["flights", flight, "scheduled_departure_time_est"], "13:00:00")
        replacement(data, operations, ["flights", flight, "scheduled_arrival_time_est"], "16:00:00")
    else:
        raise ValueError("Unrecognized pre-fixed flight-status manipulation")
    if spec["reservation_status"] == "cancelled":
        history = deepcopy(booking["payment_history"])
        if sum(entry["amount"] for entry in history) <= 0:
            raise ValueError("Template must start with positive paid history")
        refunded = history + [{"payment_id": p["payment_id"], "amount": -p["amount"]} for p in history]
        replacement(data, operations, prefix + ["payment_history"], refunded)
    patch = {"operations": operations}
    if apply_patch(base, patch) != data:
        raise RuntimeError("Fixture cannot be independently reproduced by its patch")
    return data, patch


def create():
    if (ROOT / "FIXTURE_INDEX.json").exists() or (ROOT / "BASE_DB.json.gz").exists():
        raise FileExistsError("Keep generated fixtures; do not silently overwrite an existing preparation")
    isolation = inherited.setup()
    from tau2.domains.airline.data_model import FlightDB
    specifications = read(ROOT / "CASE_SPECS.json")
    specs = specifications["cases"]
    identity = read(PREVIOUS / "COHORT_SELECTION.json")["selected_accounts"][0]
    if (identity["user_id"], identity["selected_reservation_id"]) != ("lei_santos_6163", "9Z5X1D"):
        raise ValueError("The declared, previously exposed template identity changed")
    base = FlightDB.model_validate(read(DATA / "db.json")).model_dump(mode="json")
    if base["reservations"][identity["selected_reservation_id"]]["user_id"] != identity["user_id"]:
        raise ValueError("Template ownership mismatch")
    write(ROOT / "BASE_DB.json.gz", base)
    cases, fixtures = [], []
    for spec in specs:
        before, patch = build(base, spec, identity)
        if FlightDB.model_validate(before).model_dump(mode="json") != before:
            raise ValueError("Fixture does not round-trip through the unchanged native schema")
        case_id = spec["case_id"]
        before_path = f"fixtures/{case_id}/BEFORE_DB.json.gz"
        patch_path = f"fixtures/{case_id}/DB_PATCH.json"
        write(ROOT / before_path, before)
        write(ROOT / patch_path, patch)
        fixtures.append({"case_id": case_id, "before_path": before_path,
                         "before_file_sha256": sha(ROOT / before_path), "before_canonical_sha256": digest(before),
                         "patch_path": patch_path, "patch_file_sha256": sha(ROOT / patch_path)})
        reason = spec["reason"]
        suffix = {"other": " I booked it by mistake.", "weather": " Severe weather prevents me from travelling.",
                  "unspecified": ""}[reason]
        rid = identity["selected_reservation_id"]
        cases.append({"case_id": case_id, "task_id": None, "kind": "explicitly_modified_synthetic_boundary",
                      "native_full_goal_in_scope": False, "reason_template": reason,
                      "paired_account_id": identity["user_id"], "paired_reservation_id": rid,
                      "request": {"user_id": identity["user_id"],
                                  "user_statement": f"Cancel reservation {rid}." + suffix,
                                  "cancellation": {"selector": {"kind": "ids", "ids": [rid]}, "reason": reason}}})
    index = {"schema_version": "explicit_synthetic_fixture_index_v1", "template_identity": identity,
             "template_selection": "First account and selected reservation of the pre-existing outcome-blind B hash cohort; previously exposed, not held out",
             "source_native_db": {"path": str((DATA / "db.json").resolve()), "file_sha256": sha(DATA / "db.json")},
             "base_db": {"path": "BASE_DB.json.gz", "file_sha256": sha(ROOT / "BASE_DB.json.gz"),
                         "canonical_sha256": digest(base)}, "fixtures": fixtures}
    write(ROOT / "FIXTURE_INDEX.json", index)
    write(ROOT / "REQUESTS.json", {"study": "controlled synthetic boundary fixtures, not official tasks", "cases": cases})
    report = verify()
    report.update(isolation=isolation, comparison_executed=False, native_tools_executed=0,
                  actors_executed=0, evaluator_executed=False, stage="development_schema_fixture_check_only")
    write(ROOT / "development/SCHEMA_CHECK.json", report)
    print(report)


def verify():
    from tau2.domains.airline.data_model import FlightDB
    index = read(ROOT / "FIXTURE_INDEX.json")
    base_path = within(ROOT, index["base_db"]["path"])
    base = read(base_path)
    if sha(base_path) != index["base_db"]["file_sha256"] or digest(base) != index["base_db"]["canonical_sha256"]:
        raise ValueError("Base fixture binding failed")
    if base != FlightDB.model_validate(read(DATA / "db.json")).model_dump(mode="json"):
        raise ValueError("Base is not the complete unmodified typed native DB")
    cases = read(ROOT / "REQUESTS.json")["cases"]
    specs = read(ROOT / "CASE_SPECS.json")["cases"]
    if not (len(cases) == len(specs) == len(index["fixtures"]) == 16):
        raise ValueError("Fixed 16-case population incomplete")
    ids = [c["case_id"] for c in cases]
    if len(set(ids)) != len(ids) or ids != [s["case_id"] for s in specs] or ids != [f["case_id"] for f in index["fixtures"]]:
        raise ValueError("Fixture / specification / request order differs")
    for spec, case, entry in zip(specs, cases, index["fixtures"]):
        before_path, patch_path = within(ROOT, entry["before_path"]), within(ROOT, entry["patch_path"])
        before, patch = read(before_path), read(patch_path)
        if sha(before_path) != entry["before_file_sha256"] or sha(patch_path) != entry["patch_file_sha256"]:
            raise ValueError("Fixture file binding failed")
        if digest(before) != entry["before_canonical_sha256"] or apply_patch(base, patch) != before:
            raise ValueError("Fixture independent patch reconstruction failed")
        if FlightDB.model_validate(before).model_dump(mode="json") != before:
            raise ValueError("Fixture native schema round-trip failed")
        rebuilt, rebuilt_patch = build(base, spec, index["template_identity"])
        if rebuilt != before or rebuilt_patch != patch:
            raise ValueError("Fixture differs from its declared field specification")
        if case["task_id"] is not None or case["request"]["cancellation"]["reason"] != spec["reason"]:
            raise ValueError("Request does not preserve fixed specification")
    return {"passed": True, "fixtures": len(cases), "full_schema_round_trips": len(cases),
            "explicit_patch_reconstructions": len(cases), "native_clock": NOW.isoformat()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["create", "verify"])
    args = parser.parse_args()
    if args.mode == "create":
        create()
    else:
        inherited.setup()
        print(verify())
