"""Posthoc native airline business audit, independent of actor and ECRC code.

This deliberately covers cancellation and compensation only. It never imports
tasks, gold actions, actor rules, or permission code. Expected actions derive
from the supplied request and native database; no-write runs cannot satisfy a
nonempty expected action set. Full dialogue/task success is not inferred.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json


NOW = datetime(2024, 5, 15, 15)
FLIGHT_STATUSES = {"available", "on time", "delayed", "cancelled", "flying", "landed"}
READS = {"get_user_details", "get_reservation_details", "get_flight_status", "list_all_airports", "search_direct_flight", "search_onestop_flight", "calculate", "transfer_to_human_agents"}
WRITES = {"cancel_reservation", "send_certificate"}
REASONS = {"change_of_plan", "airline_cancelled", "health", "weather", "other"}


def _decode(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _select(selector, user, database):
    owned = {rid: database["reservations"][rid] for rid in user.get("reservations", []) if rid in database["reservations"] and database["reservations"][rid].get("user_id") == user.get("user_id")}
    if not isinstance(selector, dict):
        return [], "missing_selector"
    count = selector.get("passenger_count")
    if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 1):
        return [], "invalid_passenger_count"

    def selected_with_count(ids):
        return ([rid for rid in ids if len(owned[rid].get("passengers", [])) == count] if count is not None else ids), None

    kind = selector.get("kind")
    if kind == "ids":
        ids = selector.get("ids")
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
            return [], "malformed_reservation_ids"
        if any(rid not in owned for rid in ids):
            return [], "unknown_or_unowned_selected_reservation"
        return selected_with_count(ids)
    if kind == "latest":
        if not owned:
            return [], "no_owned_reservations"
        try:
            times = {rid: datetime.fromisoformat(r["created_at"]) for rid, r in owned.items()}
            latest = max(times.values())
        except (KeyError, TypeError, ValueError):
            return [], "invalid_creation_time"
        selected = [rid for rid, timestamp in times.items() if timestamp == latest]
        return selected_with_count(selected) if len(selected) == 1 else ([], "latest_creation_time_tie")
    if kind == "all_upcoming":
        return selected_with_count([rid for rid, r in owned.items() if r.get("status") != "cancelled" and any(f.get("date", "") >= NOW.date().isoformat() for f in r.get("flights", []))])
    if kind == "all":
        return selected_with_count(list(owned))
    if kind == "flight":
        fields = [key for key in ("flight_number", "origin", "destination", "date") if selector.get(key)]
        if not fields:
            return [], "flight_selector_without_identifying_fields"
        selected = [rid for rid, r in owned.items() if any(all(str(f.get(key, "")).casefold() == str(selector[key]).casefold() for key in fields) for f in r.get("flights", []))]
        return selected_with_count(selected) if len(selected) == 1 else ([], "flight_selector_not_unique")
    return [], "unsupported_selector"


def _statuses(reservation, database):
    return [database["flights"].get(leg.get("flight_number"), {}).get("dates", {}).get(leg.get("date"), {}).get("status") for leg in reservation.get("flights", [])]


def _cancel_rule(reservation, database, reason):
    statuses = _statuses(reservation, database)
    if reason not in REASONS:
        return False, "no_supported_explicit_cancellation_reason"
    if not statuses or any(status not in FLIGHT_STATUSES for status in statuses):
        return False, "unknown_flight_status"
    if reservation.get("status") == "cancelled":
        return False, "already_cancelled"
    if any(status in {"flying", "landed"} for status in statuses):
        return False, "already_flown_requires_transfer"
    try:
        age = (NOW - datetime.fromisoformat(reservation["created_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return False, "invalid_creation_time"
    if 0 <= age <= 86400:
        return True, "booking_within_24_hours"
    if "cancelled" in statuses:
        return True, "airline_cancelled"
    if reservation.get("cabin") == "business":
        return True, "business"
    if reservation.get("insurance") == "yes" and reason in {"health", "weather"}:
        return True, "insurance_covered_reason"
    return False, "no_cancellation_basis"


def _compensation_rule(request, user, reservation, database, changed):
    if request.get("requested") is not True:
        return False, "compensation_not_explicitly_requested", None
    if not (user.get("membership") in {"silver", "gold"} or reservation.get("insurance") == "yes" or reservation.get("cabin") == "business"):
        return False, "no_compensation_entitlement", None
    relevant = _complaint_legs(request, reservation, database)
    statuses = [status for _, status in relevant]
    complaint = request.get("complaint")
    if complaint == "cancelled" and "cancelled" in statuses:
        return True, "verified_airline_cancelled", 100 * len(reservation.get("passengers", []))
    if complaint == "delayed" and "delayed" in statuses:
        if changed:
            return True, "verified_delay_after_reservation_change", 50 * len(reservation.get("passengers", []))
        return False, "delay_requires_completed_change_or_cancellation", None
    if complaint not in {"cancelled", "delayed", "other"}:
        return False, "unsupported_complaint", None
    return False, "no_verified_compensable_disruption", None


def _complaint_legs(clause, reservation, database):
    selector = clause.get("selector") or {}
    fields = [key for key in ("flight_number", "origin", "destination", "date") if selector.get(key)] if selector.get("kind") == "flight" else []
    return [(leg, status) for leg, status in zip(reservation.get("flights", []), _statuses(reservation, database)) if all(str(leg.get(key, "")).casefold() == str(selector[key]).casefold() for key in fields)]


def _key(action):
    return json.dumps({"name": action["name"], "arguments": action["arguments"], "reservation_id": action["reservation_id"]}, sort_keys=True)


def _obligations(request, before):
    user = before["users"].get(request.get("user_id"))
    actions, rejections, unsupported, selections = [], [], [], {}
    if user is None:
        return actions, rejections, ["unknown_request_user"], selections
    if not any(key in request for key in ("cancellation", "compensation")):
        unsupported.append("no_supported_action_family_requested")
    planned_cancellations = set()
    for family in ("cancellation", "compensation"):
        clause = request.get(family)
        if clause is None:
            continue
        if not isinstance(clause, dict):
            unsupported.append(f"{family}:malformed_request")
            continue
        ids, error = _select(clause.get("selector"), user, before)
        selections[family] = ids
        if error:
            unsupported.append(f"{family}:{error}")
            continue
        for rid in ids:
            reservation = before["reservations"][rid]
            if family == "cancellation":
                allowed, reason = _cancel_rule(reservation, before, clause.get("reason"))
                amount = None
                name, arguments = "cancel_reservation", {"reservation_id": rid}
            else:
                allowed, reason, amount = _compensation_rule(clause, user, reservation, before, rid in planned_cancellations)
                name, arguments = "send_certificate", {"user_id": request["user_id"], "amount": amount}
                if clause.get("allow_change") and rid not in planned_cancellations and clause.get("complaint") == "delayed":
                    unsupported.append(f"compensation:{rid}:requested_modification_outside_audit_scope")
            if allowed:
                actions.append({"name": name, "arguments": arguments, "reservation_id": rid, "policy_basis": reason})
                if family == "cancellation":
                    planned_cancellations.add(rid)
            else:
                rejections.append({"family": family, "reservation_id": rid, "reason": reason})
                if reason in {"unknown_flight_status", "invalid_creation_time", "no_supported_explicit_cancellation_reason", "unsupported_complaint"}:
                    unsupported.append(f"{family}:{rid}:{reason}")
    return actions, rejections, unsupported, selections


def audit(request: dict, messages: list[dict], before_db: dict, after_db: dict) -> dict:
    """Audit supported business outcomes; permit diagnostics are separate.

    Snapshots must be complete native FlightDB JSON. The transcript must contain
    actual chronological native messages. A displayed proposal is assistant
    JSON {user_id, actions:[...]}, optionally nested under ``proposal``, followed
    by a separate user ``yes`` turn. Every displayed action is authorized once.
    """
    for label, database in (("before", before_db), ("after", after_db)):
        if not isinstance(database, dict) or not all(isinstance(database.get(key), dict) for key in ("users", "reservations", "flights")):
            raise ValueError(f"{label} snapshot must be complete native FlightDB JSON")
    expected_actions, expected_rejections, unsupported, selections = _obligations(request, before_db)
    expected_counts = Counter(_key(action) for action in expected_actions)
    observed_counts = Counter()
    predicted = deepcopy(before_db)
    violations, attempts, successful, denied_confirmations = [], [], [], []
    seen_calls, user_reads, reservation_reads, flight_reads = set(), set(), set(), set()
    completed_cancellations = set()
    pending, authorized = None, []

    def issue(code, **details):
        violations.append({"code": code, **details})

    index = 0
    while index < len(messages):
        position = index
        message = messages[index]
        index += 1
        role = message.get("role")
        calls = message.get("tool_calls") or []
        if role == "tool":
            issue("orphan_tool_response", message_index=position)
            continue
        if not calls:
            content = _decode(message.get("content"))
            if role == "assistant":
                candidate = content.get("proposal", content) if isinstance(content, dict) else None
                pending = candidate if isinstance(candidate, dict) and isinstance(candidate.get("actions"), list) and candidate.get("user_id") else None
                if pending is not None:
                    authorized = []
            elif role == "user":
                if pending is not None and isinstance(message.get("content"), str) and message["content"].strip().casefold() == "yes":
                    if pending.get("user_id") != request.get("user_id"):
                        issue("proposal_user_mismatch", message_index=position)
                    else:
                        authorized = deepcopy(pending["actions"])
                else:
                    if pending is not None:
                        denied_confirmations.append(position)
                    authorized = []
                pending = None
            continue
        if role != "assistant" or len(calls) != 1 or message.get("content") not in (None, ""):
            issue("invalid_single_tool_turn", message_index=position)
        for call in calls:
            call_id, name = call.get("id"), call.get("name")
            arguments = _decode(call.get("arguments", {}))
            if not call_id or call_id in seen_calls:
                issue("invalid_or_duplicate_call_id", call_id=call_id)
            seen_calls.add(call_id)
            response = messages[index] if index < len(messages) else {}
            paired = response.get("role") == "tool" and response.get("id") == call_id
            if paired:
                index += 1
            else:
                issue("missing_or_mismatched_native_response", call_id=call_id)
                response = {}
            success = paired and not response.get("error")
            value = _decode(response.get("content"))
            if not isinstance(arguments, dict):
                issue("invalid_tool_arguments", call_id=call_id)
                continue
            if name in READS:
                if success and name == "get_user_details":
                    uid = arguments.get("user_id")
                    if value == predicted["users"].get(uid):
                        user_reads.add(uid)
                    else:
                        issue("read_result_not_supported_by_state", call_id=call_id)
                elif success and name == "get_reservation_details":
                    rid = arguments.get("reservation_id")
                    if value == predicted["reservations"].get(rid):
                        reservation_reads.add(rid)
                    else:
                        issue("read_result_not_supported_by_state", call_id=call_id)
                elif success and name == "get_flight_status":
                    flight, date = arguments.get("flight_number"), arguments.get("date")
                    actual = predicted["flights"].get(flight, {}).get("dates", {}).get(date, {}).get("status")
                    if value == actual and actual in FLIGHT_STATUSES:
                        flight_reads.add((flight, date))
                    else:
                        issue("read_result_not_supported_by_state", call_id=call_id)
                continue
            if name not in WRITES:
                unsupported.append(f"observed_tool_outside_scope:{name}")
                issue("write_or_tool_outside_checked_scope", call_id=call_id, name=name)
                continue
            auth_index = next((i for i, action in enumerate(authorized) if action.get("name") == name and action.get("arguments") == arguments), None)
            displayed = authorized.pop(auth_index) if auth_index is not None else {}
            rid = arguments.get("reservation_id") if name == "cancel_reservation" else displayed.get("reservation_id")
            row = {"call_id": call_id, "name": name, "arguments": deepcopy(arguments), "reservation_id": rid, "explicit_confirmation": auth_index is not None, "native_response_success": success}
            attempts.append(row)
            if auth_index is None:
                issue("write_without_matching_explicit_confirmation", call_id=call_id)
            if name == "send_certificate" and arguments.get("user_id") != request.get("user_id"):
                issue("wrong_certificate_recipient", call_id=call_id)
            reservation = predicted["reservations"].get(rid)
            user = predicted["users"].get(request.get("user_id"))
            family = "cancellation" if name == "cancel_reservation" else "compensation"
            if reservation is None or user is None:
                issue("missing_reservation_or_user_binding", call_id=call_id, reservation_id=rid)
            else:
                if reservation.get("user_id") != request.get("user_id") or rid not in user.get("reservations", []):
                    issue("wrong_reservation_owner", call_id=call_id, reservation_id=rid)
                if rid not in selections.get(family, []):
                    issue("action_outside_request_selection", call_id=call_id, reservation_id=rid)
                scope = "whole_reservation" if name == "cancel_reservation" else "certificate"
                if displayed.get("scope") != scope or displayed.get("flights") != reservation.get("flights") or displayed.get("passengers") != reservation.get("passengers") or displayed.get("reservation_id", rid) != rid:
                    issue("displayed_action_details_incomplete_or_different", call_id=call_id)
                clause = request.get(family) or {}
                if name == "cancel_reservation":
                    permitted, basis = _cancel_rule(reservation, predicted, clause.get("reason"))
                    needed_flights = {(leg["flight_number"], leg["date"]) for leg in reservation.get("flights", [])}
                else:
                    permitted, basis, correct_amount = _compensation_rule(clause, user, reservation, predicted, rid in completed_cancellations)
                    if arguments.get("amount") != correct_amount or isinstance(arguments.get("amount"), bool):
                        issue("wrong_certificate_amount", call_id=call_id, expected_amount=correct_amount)
                    wanted_status = clause.get("complaint")
                    needed_flights = {(leg["flight_number"], leg["date"]) for leg, status in _complaint_legs(clause, reservation, predicted) if status == wanted_status}
                row.update(policy_allowed=permitted, policy_basis=basis)
                if not permitted:
                    issue("business_policy_violation", call_id=call_id, reason=basis)
                statuses_confirmed = needed_flights <= flight_reads if name == "cancel_reservation" else bool(needed_flights & flight_reads)
                if request.get("user_id") not in user_reads or rid not in reservation_reads or not statuses_confirmed:
                    issue("required_business_facts_not_queried_before_action", call_id=call_id)
                if success:
                    observed_counts[_key({"name": name, "arguments": arguments, "reservation_id": rid})] += 1
            if not success:
                continue
            if name == "cancel_reservation":
                if reservation is None:
                    issue("successful_cancel_without_existing_reservation", call_id=call_id)
                    continue
                payments = deepcopy(reservation.get("payment_history", []))
                reservation["payment_history"] = payments + [{"payment_id": payment["payment_id"], "amount": -payment["amount"]} for payment in payments]
                reservation["status"] = "cancelled"
                if value != reservation:
                    issue("native_cancel_response_effect_mismatch", call_id=call_id)
                completed_cancellations.add(rid)
                successful.append({"name": name, "reservation_id": rid})
            else:
                recipient = predicted["users"].get(arguments.get("user_id"))
                if recipient is None:
                    issue("successful_certificate_without_existing_user", call_id=call_id)
                    continue
                available = next((f"certificate_{i}" for i in (3221322, 3221323, 3221324) if f"certificate_{i}" not in recipient.get("payment_methods", {})), None)
                if available is None:
                    issue("successful_certificate_exceeds_native_identifier_slots", call_id=call_id)
                    continue
                recipient["payment_methods"][available] = {"source": "certificate", "id": available, "amount": float(arguments["amount"])}
                expected_text = f"Certificate {available} added to user {arguments['user_id']} with amount {arguments['amount']}."
                if value != expected_text:
                    issue("native_certificate_response_effect_mismatch", call_id=call_id)
                successful.append({"name": name, "reservation_id": rid, "user_id": arguments["user_id"], "certificate_id": available, "amount": arguments["amount"]})

    missing = expected_counts - observed_counts
    extra = observed_counts - expected_counts
    exact_state = predicted == after_db
    if not exact_state:
        issue("after_state_has_unexplained_or_missing_native_effects")
    if extra:
        issue("unexpected_or_duplicate_business_action", actions=[{"action": json.loads(key), "count": count} for key, count in extra.items()])
    coverage = not missing and not extra and not unsupported and len(successful) == sum(observed_counts.values())
    return {
        "schema_version": "native_airline_cancel_compensation_independent_audit_v1",
        "all_checked_requirements_pass": not violations and not unsupported,
        "business_action_set_complete": coverage,
        "business_actions_safe_and_complete": coverage and not violations,
        "full_task_success_established": False,
        "native_policy_time_est": NOW.isoformat(),
        "supported_request_scope": not unsupported,
        "unsupported_or_unresolved_scope": unsupported,
        "expected_actions": expected_actions,
        "expected_policy_rejections": expected_rejections,
        "expected_action_count": sum(expected_counts.values()),
        "successful_native_write_count": len(successful),
        "zero_expected_action_case": not expected_actions,
        "missing_expected_actions": [{"action": json.loads(key), "count": count} for key, count in missing.items()],
        "extra_or_duplicate_actions": [{"action": json.loads(key), "count": count} for key, count in extra.items()],
        "attempts": attempts,
        "successful_effects": successful,
        "violations": violations,
        "declined_confirmation_turns": denied_confirmations,
        "state": {
            "exact_native_effect_state": exact_state,
            "before_sha256": _digest(before_db),
            "after_sha256": _digest(after_db),
            "predicted_after_sha256": _digest(predicted),
            "changed_user_ids": sorted(uid for uid in set(before_db["users"]) | set(after_db["users"]) if before_db["users"].get(uid) != after_db["users"].get(uid)),
            "changed_reservation_ids": sorted(rid for rid in set(before_db["reservations"]) | set(after_db["reservations"]) if before_db["reservations"].get(rid) != after_db["reservations"].get(rid)),
            "flight_inventory_unchanged": before_db["flights"] == after_db["flights"],
        },
        "checked_scope": ["native cancellation/compensation eligibility from observed snapshot facts", "requested selection, recipient, amount and authorized multiplicity", "public prerequisite fact queries", "explicit yes after displayed action details", "complete native effect and unrelated-state preservation", "completion of the derived eligible action set; no-op does not satisfy pending eligible actions"],
        "not_checked": ["original natural-language request conversion or all dialogue quality", "communication of every policy refusal or required human transfer", "modification/upgrade/booking tasks", "world changes between recorded queries and commit", "real funds, seat release or business benefit", "ECRC evidence/route/claim semantics; evaluated separately"],
        "interpretation": "A deterministic native business subset audit, not full task success, official benchmark score, or an ECRC contract audit. Native fixed certificate IDs are a fixture limit, not a business budget.",
    }
