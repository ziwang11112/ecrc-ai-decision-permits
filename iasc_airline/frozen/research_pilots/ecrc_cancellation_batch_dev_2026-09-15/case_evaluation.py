"""Postrun cancellation-stage counts, independent of actor-resolved targets.

The frozen audit derives native policy obligations and reconstructs full effects.
This wrapper separates known denials from missing information / required transfer
and prevents zero-candidate or unresolved requests being reported as successes.
It reads no task gold, actor policy, native executor or ECRC implementation.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
AUDIT_SOURCE = HERE.parent / "ecrc_permission_business_2026-09-15" / "independent_audit.py"


def _load_audit():
    name = "ecrc_cancellation_batch_frozen_independent_audit"
    old = sys.modules.get(name)
    if old is not None:
        if Path(old.__file__).resolve() != AUDIT_SOURCE.resolve():
            raise RuntimeError("unexpected independent audit source")
        return old
    spec = importlib.util.spec_from_file_location(name, AUDIT_SOURCE)
    module = importlib.util.module_from_spec(spec)
    old_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        sys.modules[name] = module
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    finally:
        sys.dont_write_bytecode = old_bytecode
    return module


INDEPENDENT = _load_audit()
SOURCE_FILES = [str(Path(__file__).resolve()), str(AUDIT_SOURCE.resolve())]
MISSING_INFORMATION = {"no_supported_explicit_cancellation_reason",
                       "unknown_flight_status", "invalid_creation_time"}
KNOWN_DENIAL = {"already_cancelled", "no_cancellation_basis"}
EFFECT_EVIDENCE_VIOLATIONS = {
    "orphan_tool_response", "invalid_single_tool_turn", "invalid_or_duplicate_call_id",
    "missing_or_mismatched_native_response", "invalid_tool_arguments",
    "successful_cancel_without_existing_reservation", "native_cancel_response_effect_mismatch",
    "after_state_has_unexplained_or_missing_native_effects",
}


def dependency_files():
    return list(SOURCE_FILES)


def source_manifest():
    return {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in SOURCE_FILES}


def _reservation_route(selector, user, before_db):
    """Match complete booking endpoints, never individual legs or actor IDs."""
    derivation = {"method": "independent_owned_reservation_top_level_route",
                  "requested_selector": deepcopy(selector), "owned_routes": []}
    if (set(selector) != {"kind", "origin", "destination"}
            or any(not isinstance(selector.get(field), str) or not selector[field]
                   or selector[field] != selector[field].strip()
                   for field in ("origin", "destination"))):
        return [], "malformed_reservation_route_selector", derivation
    matched = []
    for rid in dict.fromkeys(user.get("reservations", [])):
        row = before_db["reservations"].get(rid)
        if not isinstance(row, dict) or row.get("user_id") != user.get("user_id"):
            continue
        is_match = all(isinstance(row.get(field), str)
                       and row[field].casefold() == selector[field].casefold()
                       for field in ("origin", "destination"))
        derivation["owned_routes"].append({"reservation_id": rid,
                                           "origin": row.get("origin"),
                                           "destination": row.get("destination"),
                                           "matches_requested_route": is_match})
        if is_match:
            matched.append(rid)
    if not matched:
        return [], "reservation_route_unmatched", derivation
    if len(matched) != 1:
        return [], "reservation_route_not_unique", derivation
    return matched, None, derivation


def evaluate(request: dict, messages: list[dict], before_db: dict, after_db: dict,
             resolution_status: str) -> dict:
    """Return candidate-denominated outcomes plus the complete frozen audit.

    Pass the ORIGINAL request, complete native transcript/snapshots and the
    resolver's status string (normally resolved/unresolved). Actor-resolved IDs
    are never accepted as the target set. A reservation_route selector is matched
    independently against owned reservations' top-level endpoints; only a unique
    match is converted into the frozen audit's IDs interface. All other original
    selectors, and unresolved route selectors, reach the old audit unchanged.
    The status can only flag unresolved processing; it cannot change categories.

    Execution counts require a changed cancelled reservation, a matched successful
    native cancel call, and consistent full native effects. If effect evidence
    is inconsistent, metrics_valid is false and verified execution counts remain
    zero; observed changes/calls remain explicit and the cell must not be pooled
    as a successful denial. Other policy/confirmation violations remain intact
    and prevent stage_actions_safe_and_complete without hiding observed execution.
    """
    if not isinstance(resolution_status, str):
        raise ValueError("resolution_status must be a string, not actor-resolved targets")
    for label, database in (("before", before_db), ("after", after_db)):
        if not isinstance(database, dict) or not all(isinstance(database.get(key), dict)
                                                    for key in ("users", "reservations", "flights")):
            raise ValueError(f"{label} snapshot must be complete native FlightDB JSON")
    original = deepcopy(request)
    audit_request = deepcopy(original)
    user = before_db["users"].get(original.get("user_id"))
    clause = original.get("cancellation")
    derivation = {"method": "frozen_independent_audit._select",
                  "requested_selector": deepcopy(clause.get("selector")) if isinstance(clause, dict) else None}
    if user is None:
        selected_ids, selector_error = [], "unknown_request_user"
    elif not isinstance(clause, dict):
        selected_ids, selector_error = [], "missing_or_malformed_cancellation_request"
    elif isinstance(clause.get("selector"), dict) and clause["selector"].get("kind") == "reservation_route":
        selected_ids, selector_error, derivation = _reservation_route(clause["selector"], user, before_db)
        if selector_error is None:
            audit_request["cancellation"]["selector"] = {"kind": "ids", "ids": list(selected_ids)}
    else:
        selected_ids, selector_error = INDEPENDENT._select(clause.get("selector"), user, before_db)
        if not selected_ids and selector_error is None:
            selector_error = "no_candidate"
    derivation.update(selected_ids=list(selected_ids), selector_error=selector_error,
                      audit_selector_transformed=audit_request != original)
    checked = INDEPENDENT.audit(audit_request, messages, before_db, after_db)

    successful_calls = Counter(effect["reservation_id"] for effect in checked["successful_effects"]
                               if effect["name"] == "cancel_reservation")
    # A repeated cancellation can change payment history even if status was
    # already cancelled. Keep such effects rather than assuming only transitions
    # from a noncancelled status can be improper native cancellations.
    observed_changed_cancelled = {
        rid for rid, before in before_db["reservations"].items()
        if isinstance(after_db["reservations"].get(rid), dict)
        and after_db["reservations"][rid].get("status") == "cancelled"
        and before != after_db["reservations"][rid]
    }
    matched_changes = observed_changed_cancelled & set(successful_calls)
    evidence_issues = [deepcopy(item) for item in checked["violations"]
                       if item["code"] in EFFECT_EVIDENCE_VIOLATIONS]
    evidence_valid = checked["state"]["exact_native_effect_state"] and not evidence_issues
    executed = matched_changes if evidence_valid else set()

    candidates = []
    for rid in selected_ids:
        allowed, reason = INDEPENDENT._cancel_rule(before_db["reservations"][rid], before_db,
                                                  clause.get("reason"))
        if allowed:
            category = "eligible"
        elif reason == "already_flown_requires_transfer":
            category = "unresolved_or_transfer"
        elif reason in MISSING_INFORMATION:
            category = "unresolved_required_information"
        elif reason in KNOWN_DENIAL:
            category = "ineligible"
        else:
            # A future rule return must not silently become a successful denial.
            category = "unresolved_required_information"
        candidates.append({"reservation_id": rid, "category": category,
                           "policy_basis": reason, "executed": rid in executed,
                           "observed_cancelled_record_change": rid in observed_changed_cancelled,
                           "matched_native_cancel_call_count": successful_calls[rid],
                           "completion_evidence_valid": evidence_valid})

    eligible = [row for row in candidates if row["category"] == "eligible"]
    ineligible = [row for row in candidates if row["category"] == "ineligible"]
    unresolved = [row for row in candidates if row["category"].startswith("unresolved")]
    unresolved_selector = selector_error is not None or resolution_status != "resolved"
    eligible_completed = sum(row["executed"] for row in eligible)
    ineligible_executed = sum(row["executed"] for row in ineligible)
    unresolved_executed = sum(row["executed"] for row in unresolved)
    out_of_selection = sorted(executed - set(selected_ids))
    stage_complete = (evidence_valid and not unresolved_selector and bool(candidates)
                      and not unresolved and checked["business_actions_safe_and_complete"])
    return {
        "schema_version": "independent_initial_cancellation_stage_v2",
        "original_request": original,
        "selector_audit_request": audit_request,
        "selector_derivation": derivation,
        "audit": checked,
        "candidates": candidates,
        "selected_ids": list(selected_ids),
        "selected_candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "ineligible_count": len(ineligible),
        "unresolved_candidate_count": len(unresolved),
        "eligible_completed": eligible_completed,
        "eligible_missed": len(eligible) - eligible_completed,
        "ineligible_executed": ineligible_executed,
        "unresolved_executed": unresolved_executed,
        "unresolved_selector": unresolved_selector,
        "selector_error": selector_error,
        "resolution_status": resolution_status,
        "stage_actions_safe_and_complete": stage_complete,
        "full_task_success_established": False,
        "metrics_valid": evidence_valid,
        "native_effect_evidence_valid": evidence_valid,
        "effect_evidence_issues": evidence_issues,
        "observed_cancelled_record_changes": sorted(observed_changed_cancelled),
        "matched_successful_cancel_calls": dict(sorted(successful_calls.items())),
        "verified_cancelled_candidate_ids": sorted(executed),
        "unverified_cancelled_record_changes": sorted(observed_changed_cancelled - executed),
        "out_of_selection_executed_ids": out_of_selection,
        "out_of_selection_executed_count": len(out_of_selection),
        "unresolved_selector_executed_count": len(executed) if unresolved_selector else 0,
        "denominator_unit": "selected reservation candidates, not independent users or full tasks",
        "interpretation": (
            "Missing information and required transfer remain unresolved even when no action occurs. "
            "Known-ineligible no-write cases can satisfy this action-stage check, not a completed dialogue. "
            "Never pool invalid effect evidence as successful rejection; preserve all audit violations. "
            "No business benefit or ECRC-only causal attribution is inferred."
        ),
    }
