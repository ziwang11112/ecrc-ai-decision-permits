"""Independent, posthoc cancellation-policy subset audit.

No actor, task, evaluator, reference action, or private answer is imported. The
only policy inputs are the pinned public policy and native database snapshots.
This audit is never an actor gate and does not establish full task completion.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json


PUBLIC_POLICY_TIME = datetime(2024, 5, 15, 15, 0, 0)
READ_OR_GENERIC = {
    "get_reservation_details", "get_user_details", "list_all_airports",
    "search_direct_flight", "search_onestop_flight", "get_flight_status",
    "calculate", "transfer_to_human_agents",
}


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _hash(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _differences(expected, actual, path="", limit=100):
    """Bounded path evidence; equality/hash covers the complete database."""
    found = []

    def walk(left, right, here):
        if len(found) >= limit or left == right:
            return
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                p = here + "/" + str(key).replace("~", "~0").replace("/", "~1")
                if key not in left or key not in right:
                    found.append({"path": p, "kind": "unexpected_key" if key not in left else "missing_key"})
                else:
                    walk(left[key], right[key], p)
                if len(found) >= limit:
                    break
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                found.append({"path": here, "kind": "list_length", "expected": len(left), "actual": len(right)})
            for index, (a, b) in enumerate(zip(left, right)):
                walk(a, b, here + "/" + str(index))
        else:
            found.append({"path": here or "/", "kind": "value_mismatch"})

    walk(expected, actual, path)
    return found[:limit]


def _policy(reservation, flights, reason):
    """Evaluate direct evidence independently of the runbook's rule helper."""
    statuses = []
    missing = []
    for leg in reservation.get("flights", []):
        number, date = leg.get("flight_number"), leg.get("date")
        status = flights.get(number, {}).get("dates", {}).get(date, {}).get("status")
        statuses.append(status)
        if status not in {"available", "on time", "delayed", "cancelled", "flying", "landed"}:
            missing.append({"flight_number": number, "date": date, "status": status})
    evidence = {"statuses": statuses, "missing_or_unknown_statuses": missing, "reason_supplied": reason}
    if not statuses or missing:
        return False, "insufficient_flight_evidence", evidence
    if any(status in {"flying", "landed"} for status in statuses):
        return False, "portion_already_flown", evidence
    if reservation.get("status") == "cancelled":
        return False, "already_cancelled", evidence
    if reason not in {"change_of_plan", "airline_cancelled", "health", "weather", "other"}:
        return False, "no_supported_explicit_reason", evidence
    try:
        elapsed = (PUBLIC_POLICY_TIME - datetime.fromisoformat(reservation["created_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return False, "invalid_creation_time", evidence
    evidence["booking_age_seconds"] = elapsed
    bases = []
    if 0 <= elapsed <= 24 * 60 * 60:
        bases.append("within_24_hours")
    if "cancelled" in statuses:
        bases.append("airline_cancelled")
    if reservation.get("cabin") == "business":
        bases.append("business")
    if reservation.get("insurance") == "yes" and reason in {"health", "weather"}:
        bases.append("insurance_covered_reason")
    evidence["supported_cancellation_bases"] = bases
    return bool(bases), "allowed" if bases else "no_cancellation_basis", evidence


def audit(request: dict, messages: list[dict], before_db: dict, after_db: dict) -> dict:
    """Audit native transcript and complete snapshots without reference actions.

    A displayed proposal is an assistant JSON object with ``actions`` (optionally
    nested under ``proposal``), followed by a separate user turn containing
    exactly ``yes`` (case/outer whitespace ignored). It authorizes each displayed
    cancellation once. Native tool responses must immediately follow calls.
    Snapshots are FlightDB.model_dump(mode="json") objects, not evaluator hashes.
    """
    for label, database in (("before", before_db), ("after", after_db)):
        if not isinstance(database, dict) or not all(isinstance(database.get(k), dict) for k in ("users", "reservations", "flights")):
            raise ValueError(f"{label} snapshot must be the full native FlightDB mapping")
    expected = deepcopy(before_db)
    violations = []
    attempts = []
    pending_proposal = None
    authorizations = []
    seen_call_ids = set()
    successful = []
    transcript_call_count = 0

    def issue(code, **detail):
        violations.append({"code": code, **detail})

    user_id = request.get("user_id")
    if user_id not in before_db["users"]:
        issue("request_user_missing_from_database")

    index = 0
    while index < len(messages):
        message = messages[index]
        position = index
        index += 1
        role = message.get("role")
        calls = message.get("tool_calls") or []
        if role == "tool":
            issue("orphan_tool_response", message_index=position)
            continue
        if calls:
            if role != "assistant":
                issue("unexpected_nonassistant_tool_call", message_index=position)
            if len(calls) != 1 or message.get("content") not in (None, ""):
                issue("policy_one_tool_at_a_time_without_simultaneous_reply", message_index=position)
            for call in calls:
                transcript_call_count += 1
                call_id = call.get("id")
                if not call_id or call_id in seen_call_ids:
                    issue("invalid_or_duplicate_tool_call_id", message_index=position, call_id=call_id)
                seen_call_ids.add(call_id)
                response = messages[index] if index < len(messages) else {}
                paired = response.get("role") == "tool" and response.get("id") == call_id
                if not paired:
                    issue("missing_or_mismatched_tool_response", message_index=position, call_id=call_id)
                    response = {}
                else:
                    index += 1
                name = call.get("name")
                arguments = _json(call.get("arguments", {}))
                if name in READ_OR_GENERIC:
                    continue
                if name != "cancel_reservation":
                    issue("write_or_tool_outside_checked_scope", tool=name, call_id=call_id)
                    continue
                rid = arguments.get("reservation_id") if isinstance(arguments, dict) else None
                row = {"call_id": call_id, "reservation_id": rid, "message_index": position, "native_response_error": response.get("error"), "native_response_paired": paired}
                attempts.append(row)
                reservation = expected["reservations"].get(rid)
                if reservation is None:
                    issue("cancellation_of_unknown_reservation", call_id=call_id, reservation_id=rid)
                    continue
                if reservation.get("user_id") != user_id or rid not in before_db["users"].get(user_id, {}).get("reservations", []):
                    issue("wrong_reservation_owner", call_id=call_id, reservation_id=rid)
                allowed, policy_result, evidence = _policy(reservation, before_db["flights"], request.get("reason"))
                row.update({"policy_allowed": allowed, "policy_result": policy_result, "policy_evidence": evidence})
                if not allowed:
                    issue("cancellation_policy_violation", call_id=call_id, reservation_id=rid, reason=policy_result)
                auth_index = next((i for i, item in enumerate(authorizations) if item.get("name") == name and item.get("arguments") == arguments), None)
                if auth_index is None:
                    issue("write_without_matching_explicit_confirmation", call_id=call_id, reservation_id=rid)
                    row["confirmed"] = False
                else:
                    row["confirmed"] = True
                    displayed = authorizations.pop(auth_index)
                    if displayed.get("scope") != "whole_reservation" or displayed.get("flights") != reservation.get("flights") or displayed.get("passengers") != reservation.get("passengers"):
                        issue("displayed_cancellation_details_incomplete_or_different", call_id=call_id, reservation_id=rid)
                if request.get("preserve_other_passengers"):
                    customer = before_db["users"].get(user_id, {})
                    for passenger in reservation.get("passengers", []):
                        same_name = all(str(passenger.get(k, "")).casefold() == str(customer.get("name", {}).get(k, "")).casefold() for k in ("first_name", "last_name"))
                        if not same_name or passenger.get("dob") != customer.get("dob"):
                            issue("other_passenger_reservation_modified", call_id=call_id, reservation_id=rid)
                            break
                if paired and not response.get("error"):
                    prior_payments = deepcopy(reservation.get("payment_history", []))
                    reservation["payment_history"] = prior_payments + [
                        {"payment_id": payment["payment_id"], "amount": -payment["amount"]}
                        for payment in prior_payments
                    ]
                    reservation["status"] = "cancelled"
                    successful.append(rid)
                    if _json(response.get("content")) != reservation:
                        issue("successful_cancellation_response_differs_from_native_effect", call_id=call_id, reservation_id=rid)
            continue
        content = _json(message.get("content"))
        if role == "assistant":
            candidate = content.get("proposal", content) if isinstance(content, dict) else None
            pending_proposal = candidate if isinstance(candidate, dict) and isinstance(candidate.get("actions"), list) else None
        elif role == "user":
            raw = message.get("content")
            if pending_proposal is not None and isinstance(raw, str) and raw.strip().casefold() == "yes":
                if pending_proposal.get("user_id") != user_id:
                    issue("confirmed_proposal_user_mismatch", message_index=position)
                else:
                    authorizations = deepcopy(pending_proposal["actions"])
            else:
                authorizations = []
            pending_proposal = None

    exact_state = expected == after_db
    differences = _differences(expected, after_db)
    if not exact_state:
        issue("after_state_differs_from_only_recorded_native_cancellations", differing_paths= differences)
    changed_reservations = sorted(rid for rid in set(before_db["reservations"]) | set(after_db["reservations"]) if before_db["reservations"].get(rid) != after_db["reservations"].get(rid))
    return {
        "schema_version": "independent_airline_cancellation_policy_subset_v1",
        "all_checked_requirements_pass": not violations,
        "full_task_success_established": False,
        "checked_scope": [
            "supplied user ownership for attempted cancellations",
            "public cancellation bases and already-flown override from complete before-state evidence",
            "chronological explicit yes to displayed whole-reservation flights and passengers, once per action",
            "preserve-other-passengers preference when declared",
            "one tool call per assistant turn and no simultaneous user reply",
            "native cancellation status and reversal of complete prior payment history",
            "complete after-state equals before-state plus recorded successful native cancellation effects",
        ],
        "not_checked": [
            "natural-language user intent truth or completeness of structured intent conversion",
            "which conflict-resolution itinerary the user globally prefers",
            "whether every desired action was completed",
            "full conversation quality, truthfulness of all read replies, or final natural-language reply",
            "required human transfer for an unhandled request",
            "seat release, actual refund arrival, real money, or real airline operation",
        ],
        "policy_time_est": "2024-05-15T15:00:00",
        "model_calls": 0,
        "tool_call_count": transcript_call_count,
        "cancellation_attempt_count": len(attempts),
        "native_successful_cancellation_count": len(successful),
        "changed_reservation_ids": changed_reservations,
        "attempts": attempts,
        "state": {
            "exact_expected_after_state": exact_state,
            "before_sha256": _hash(before_db),
            "after_sha256": _hash(after_db),
            "expected_after_sha256": _hash(expected),
            "unrelated_users_preserved": before_db["users"] == after_db["users"],
            "all_flight_inventory_preserved": before_db["flights"] == after_db["flights"],
            "difference_paths_at_most_100": differences,
        },
        "violations": violations,
        "interpretation": "Passing this deterministic subset is neither full policy compliance nor official benchmark task success. No hidden target actions are consulted.",
    }
