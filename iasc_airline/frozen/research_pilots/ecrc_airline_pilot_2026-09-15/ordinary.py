"""Small, no-model airline runbook over public native tool responses.

The structured request is a declared development adaptation of the user scenario.
This actor has no task-id, task-file, reference-action or database access. It is
not a natural-language agent or a reimplementation of ECRC.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Callable


POLICY_NOW = "2024-05-15T15:00:00"
SUPPORTED_MODES = {"cancel_upcoming", "resolve_itinerary_conflicts"}
REASONS = {"change_of_plan", "airline_cancelled", "health", "weather", "other"}
FLOWN = {"flying", "landed"}
KNOWN_STATUSES = {"available", "on time", "delayed", "cancelled", *FLOWN}


def cancellation_eligibility(reservation: dict, statuses: list[str], reason: str) -> dict:
    """Apply the pinned public cancellation policy, including its flown override."""
    if reason not in REASONS:
        return {"allowed": False, "reason": "missing_or_unsupported_reason"}
    if reservation.get("status") == "cancelled":
        return {"allowed": False, "reason": "already_cancelled"}
    if len(statuses) != len(reservation.get("flights", [])) or not statuses:
        return {"allowed": False, "reason": "incomplete_flight_status"}
    if any(status not in KNOWN_STATUSES for status in statuses):
        return {"allowed": False, "reason": "unknown_flight_status"}
    if any(status in FLOWN for status in statuses):
        return {"allowed": False, "reason": "portion_already_flown_transfer_required"}
    age = datetime.fromisoformat(POLICY_NOW) - datetime.fromisoformat(reservation["created_at"])
    if timedelta(0) <= age <= timedelta(hours=24):
        return {"allowed": True, "reason": "booked_within_24_hours"}
    if "cancelled" in statuses:
        return {"allowed": True, "reason": "airline_cancelled_flight"}
    if reservation["cabin"] == "business":
        return {"allowed": True, "reason": "business_cabin"}
    if reservation["insurance"] == "yes" and reason in {"health", "weather"}:
        return {"allowed": True, "reason": "insured_covered_reason"}
    return {"allowed": False, "reason": "no_policy_cancellation_basis"}


def _time_on_date(date: str, time: str) -> datetime:
    """Native schedules encode overnight arrivals as HH:MM:SS+1."""
    clock, _, day_offset = time.partition("+")
    return datetime.fromisoformat(date + "T" + clock) + timedelta(days=int(day_offset or "0"))


def _passenger_matches(passenger: dict, user: dict) -> bool:
    return all(
        str(passenger.get(key, "")).casefold() == str(user["name"].get(key, "")).casefold()
        for key in ("first_name", "last_name")
    ) and passenger.get("dob") == user.get("dob")


def run(request: dict, caller: Callable, confirm: Callable) -> dict:
    """Run one bounded request. ``caller(name, **kwargs)`` returns JSON values.

    ``confirm(proposal)`` is an explicit scripted-user turn and must return the
    string ``yes`` to authorize the displayed complete cancellation proposal.
    It must not consult hidden evaluation actions. Native mutations are made at
    most once each; a tool error stops this ordinary invocation without retries.
    """
    request = deepcopy(request)
    if request.get("mode") not in SUPPORTED_MODES:
        raise ValueError("Unsupported structured intent")
    if not isinstance(request.get("user_id"), str) or not request["user_id"]:
        raise ValueError("The user must supply a user_id")
    if request.get("reason") not in REASONS:
        raise ValueError("An explicit structured cancellation reason is required")
    report = {
        "actor": "ordinary_no_model_rules", "model_calls": 0,
        "request": request, "status": "running", "decisions": [],
        "actions": [], "unresolved": [], "trace": [], "messages": [],
    }

    def event(kind: str, **fields) -> None:
        report["trace"].append({"sequence": len(report["trace"]), "kind": kind, **deepcopy(fields)})

    def call(name: str, **arguments):
        event("tool_call", name=name, arguments=arguments)
        try:
            value = deepcopy(caller(name, **arguments))
        except Exception as exc:
            event("tool_error", name=name, error_type=type(exc).__name__, error=str(exc))
            raise
        event("tool_result", name=name, result=value)
        return value

    try:
        user = call("get_user_details", user_id=request["user_id"])
        if user["user_id"] != request["user_id"]:
            raise ValueError("Returned user does not match the supplied user id")
        reservations = []
        for reservation_id in dict.fromkeys(user["reservations"]):
            reservation = call("get_reservation_details", reservation_id=reservation_id)
            if reservation["reservation_id"] != reservation_id or reservation["user_id"] != user["user_id"]:
                raise ValueError("Reservation identity or ownership mismatch")
            reservations.append(reservation)

        statuses = {}
        for reservation in reservations:
            statuses[reservation["reservation_id"]] = [
                call("get_flight_status", flight_number=flight["flight_number"], date=flight["date"])
                for flight in reservation["flights"]
            ]

        today = POLICY_NOW[:10]
        upcoming = {
            reservation["reservation_id"] for reservation in reservations
            if any(flight["date"] >= today for flight in reservation["flights"])
            and reservation.get("status") != "cancelled"
        }
        if request["mode"] == "cancel_upcoming":
            selected = upcoming
            selection_reasons = {rid: "user_requested_all_upcoming" for rid in selected}
        else:
            selected, selection_reasons = _select_conflicts(request, user, reservations, statuses, call, report)

        proposal_actions = []
        for reservation in reservations:
            rid = reservation["reservation_id"]
            rule = cancellation_eligibility(reservation, statuses[rid], request["reason"])
            in_scope = rid in selected
            allowed = in_scope and rule["allowed"]
            report["decisions"].append({
                "reservation_id": rid, "in_scope": in_scope,
                "selection_reason": selection_reasons.get(rid, "preserve_not_selected"),
                "policy": rule, "decision": "propose_cancel" if allowed else "preserve",
            })
            if allowed:
                proposal_actions.append({
                    "name": "cancel_reservation", "arguments": {"reservation_id": rid},
                    "scope": "whole_reservation", "flights": deepcopy(reservation["flights"]),
                    "passengers": deepcopy(reservation["passengers"]),
                    "policy_basis": rule["reason"],
                    "selection_basis": selection_reasons[rid],
                    "refund_destination": "original_payment_methods",
                    "refund_timing": "5 to 7 business days",
                })
            elif in_scope and rule["reason"] == "portion_already_flown_transfer_required":
                report["unresolved"].append({"reservation_id": rid, "reason": rule["reason"]})

        if not proposal_actions:
            report["status"] = "needs_clarification" if report["unresolved"] else "completed_no_write"
            return report

        proposal = {
            "user_id": user["user_id"], "actions": proposal_actions,
            "preserved_reservations": [item["reservation_id"] for item in report["decisions"] if item["decision"] == "preserve"],
            "unresolved": deepcopy(report["unresolved"]),
            "question": "Confirm these entire-reservation cancellations: yes or no?",
        }
        event("assistant_proposal", proposal=proposal)
        response = confirm(deepcopy(proposal))
        event("scripted_user_confirmation", response=response)
        report["confirmation"] = {"proposal": proposal, "response": response}
        if not isinstance(response, str) or response.strip().casefold() != "yes":
            report["status"] = "confirmation_declined"
            return report

        for action in proposal_actions:
            rid = action["arguments"]["reservation_id"]
            outcome = {"reservation_id": rid, "status": "attempt_started"}
            report["actions"].append(outcome)
            call("cancel_reservation", reservation_id=rid)
            observed = call("get_reservation_details", reservation_id=rid)
            if observed.get("status") != "cancelled":
                outcome["status"] = "cancellation_not_verified"
                report["status"] = "verification_failed"
                return report
            outcome["status"] = "cancelled_verified"
            event("assistant_result", reservation_id=rid, message="Reservation cancellation verified by readback.")
        report["status"] = "partial_completed_needs_clarification" if report["unresolved"] else "completed"
    except Exception as exc:
        report["status"] = "tool_or_data_error"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    return report


def _select_conflicts(request, user, reservations, statuses, call, report):
    """An explicit scheduling heuristic, not an airline policy or gold answer.

    Protect uniquely matched user anchors. A whole reservation whose future
    itinerary interval overlaps a protected one is a cancellation candidate.
    Layovers are included in that interval. This is a declared runbook choice;
    the customer sees every candidate before the scripted confirmation.
    """
    anchors = request.get("anchors", [])
    if not anchors:
        report["unresolved"].append({"reason": "missing_itinerary_anchors"})
        return set(), {}
    airports = {item["iata"]: item["city"].casefold() for item in call("list_all_airports")}
    eligible = []
    intervals = {}
    schedules = {}
    for reservation in reservations:
        rid = reservation["reservation_id"]
        matches = [_passenger_matches(passenger, user) for passenger in reservation["passengers"]]
        if not any(matches) or reservation.get("status") == "cancelled":
            continue
        if request.get("preserve_other_passengers", True) and not all(matches):
            report["unresolved"].append({"reservation_id": rid, "reason": "mixed_passengers_need_scope_confirmation"})
            continue
        timed_flights = []
        incomplete = False
        for flight, status in zip(reservation["flights"], statuses[rid]):
            if status in FLOWN or flight["date"] < POLICY_NOW[:10]:
                continue
            if status != "available":
                incomplete = True
                continue
            key = (flight["origin"], flight["destination"], flight["date"])
            if key not in schedules:
                schedules[key] = call("search_direct_flight", origin=key[0], destination=key[1], date=key[2])
            found = [item for item in schedules[key] if item["flight_number"] == flight["flight_number"]]
            if len(found) != 1:
                incomplete = True
                continue
            data = found[0]
            timed_flights.append({
                **flight, "departure": _time_on_date(flight["date"], data["scheduled_departure_time_est"]),
                "arrival": _time_on_date(flight["date"], data["scheduled_arrival_time_est"]),
            })
        if incomplete:
            report["unresolved"].append({"reservation_id": rid, "reason": "native_public_schedule_unavailable"})
            continue
        if not timed_flights:
            continue
        eligible.append((reservation, timed_flights))
        intervals[rid] = (min(f["departure"] for f in timed_flights), max(f["arrival"] for f in timed_flights))

    city_airports = request.get("public_context", {}).get("city_airports", {})

    def location_matches(iata, anchor, name):
        value = anchor.get(name)
        aliases = next((codes for city, codes in city_airports.items() if value is not None and city.casefold() == value.casefold()), [])
        return value is None or value.casefold() in {iata.casefold(), airports.get(iata, "")} or iata in aliases

    protected = set()
    for anchor in anchors:
        matching = set()
        for reservation, flights in eligible:
            for flight in flights:
                direction = anchor.get("event")
                if direction not in {"arrival", "departure"}:
                    raise ValueError("Anchor event must be arrival or departure")
                if flight[direction].date().isoformat() != anchor["date"]:
                    continue
                if location_matches(flight["origin"], anchor, "origin") and location_matches(flight["destination"], anchor, "destination"):
                    matching.add(reservation["reservation_id"])
        if len(matching) == 1:
            protected.update(matching)
        else:
            report["unresolved"].append({"anchor": deepcopy(anchor), "reason": "anchor_not_uniquely_matched", "matching_reservations": sorted(matching)})

    selected = set()
    reasons = {}
    for rid, (start, end) in intervals.items():
        if rid in protected:
            continue
        conflicting = [other for other in protected if start < intervals[other][1] and intervals[other][0] < end]
        if conflicting:
            selected.add(rid)
            reasons[rid] = "whole_itinerary_interval_overlaps_confirmed_anchor"
    if protected:
        last_anchor_end = max(intervals[rid][1] for rid in protected)
        for rid, (start, end) in intervals.items():
            if rid not in protected and rid not in selected and start < last_anchor_end:
                report["unresolved"].append({
                    "reservation_id": rid,
                    "reason": "unanchored_itinerary_needs_preference_or_complete_route_assumption",
                    "detail": "No temporal overlap proves a unique cancellation; missing transfers and earlier travel intent are not specified.",
                })
    report["itinerary_analysis"] = {
        "algorithm": "unique_native_city_or_airport_anchor_then_whole_itinerary_interval_overlap",
        "protected_reservations": sorted(protected),
        "candidate_cancellations": sorted(selected),
        "intervals": {rid: [start.isoformat(), end.isoformat()] for rid, (start, end) in intervals.items()},
        "public_city_airports": deepcopy(city_airports),
        "limitation": "Does not infer missing travel legs or a unique globally preferred itinerary; supplied metropolitan aliases only match existing trips.",
    }
    return selected, reasons
