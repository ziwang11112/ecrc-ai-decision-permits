"""Public-rule cancellation/compensation workflow; no task labels or model."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json

NOW = datetime.fromisoformat("2024-05-15T15:00:00")
KNOWN = {"available", "on time", "delayed", "cancelled", "flying", "landed"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def select(reservations, selector):
    kind = selector["kind"]
    if kind == "ids":
        wanted = set(selector["ids"])
        found = [r for r in reservations if r["reservation_id"] in wanted]
        if len(found) != len(wanted):
            raise ValueError("Requested reservation not found in supplied user's account")
    elif kind == "latest":
        latest = max(r["created_at"] for r in reservations)
        found = [r for r in reservations if r["created_at"] == latest]
        if len(found) != 1:
            raise ValueError("Ambiguous latest reservation")
    elif kind == "all_upcoming":
        found = [r for r in reservations if r.get("status") != "cancelled" and
                 any(f["date"] >= NOW.date().isoformat() for f in r["flights"])]
    elif kind == "all":
        found = list(reservations)
    elif kind == "flight":
        fields = ("flight_number", "origin", "destination", "date")
        wanted = {key: selector[key] for key in fields if key in selector}
        if not wanted:
            raise ValueError("Empty flight selector")
        found = [r for r in reservations if any(all(f.get(k) == v for k, v in wanted.items()) for f in r["flights"])]
        if len(found) != 1:
            raise ValueError("Flight selector does not identify one reservation")
    else:
        raise ValueError("Unsupported selector")
    if "passenger_count" in selector:
        found = [r for r in found if len(r["passengers"]) == selector["passenger_count"]]
    return found


def cancel_basis(reservation, statuses, reason):
    if reason not in {"health", "weather", "change_of_plan", "airline_cancelled", "other"}:
        return None, "missing_reason"
    if reservation.get("status") == "cancelled":
        return None, "already_cancelled"
    if not statuses or len(statuses) != len(reservation["flights"]) or any(s not in KNOWN for s in statuses):
        return None, "unknown_flight_status"
    if any(s in {"flying", "landed"} for s in statuses):
        return None, "portion_already_flown_transfer_required"
    age = NOW - datetime.fromisoformat(reservation["created_at"])
    if timedelta(0) <= age <= timedelta(hours=24):
        return "within_24_hours", None
    if "cancelled" in statuses:
        return "airline_cancelled", None
    if reservation["cabin"] == "business":
        return "business_cabin", None
    if reservation["insurance"] == "yes" and reason in {"health", "weather"}:
        return "insured_covered_reason", None
    return None, "no_cancellation_basis"


def compensation_basis(user, reservation, statuses, request, cancelled_here):
    if not request.get("requested"):
        return None, 0, "not_requested"
    if not statuses or len(statuses) != len(reservation["flights"]) or any(s not in KNOWN for s in statuses):
        return None, 0, "unknown_flight_status"
    eligible = user["membership"] in {"silver", "gold"} or reservation["insurance"] == "yes" or reservation["cabin"] == "business"
    if not eligible:
        return None, 0, "no_membership_insurance_or_business_basis"
    relevant_statuses = statuses
    selector = request["selector"]
    if selector["kind"] == "flight":
        fields = {key: selector[key] for key in ("flight_number", "origin", "destination", "date") if key in selector}
        relevant_statuses = [status for flight, status in zip(reservation["flights"], statuses)
                             if all(flight.get(key) == value for key, value in fields.items())]
    if request["complaint"] == "cancelled" and "cancelled" in relevant_statuses:
        return "verified_airline_cancellation", 100 * len(reservation["passengers"]), None
    if request["complaint"] == "delayed" and "delayed" in relevant_statuses:
        if reservation["reservation_id"] in cancelled_here:
            return "verified_delay_after_cancellation", 50 * len(reservation["passengers"]), None
        return None, 0, "delay_requires_completed_change_or_cancellation"
    return None, 0, "complaint_not_supported_by_flight_status"


def run(request, caller, confirm, *, authorize=None):
    """Same ordinary decisions in both arms; optional gate mediates writes only.

    The gate may reject a proposal but cannot rewrite ordinary business rules.
    All evidence bodies come from the shared public workflow, not a task oracle.
    """
    request = deepcopy(request)
    report = {"model_calls": 0, "decisions": [], "actions": [], "proposals": [], "unresolved": [], "status": "running"}
    user = caller("get_user_details", user_id=request["user_id"])
    if user["user_id"] != request["user_id"]:
        raise ValueError("User identity mismatch")
    reservations = []
    for rid in dict.fromkeys(user["reservations"]):
        reservation = caller("get_reservation_details", reservation_id=rid)
        if reservation["reservation_id"] != rid or reservation["user_id"] != user["user_id"]:
            raise ValueError("Reservation identity mismatch")
        reservations.append(reservation)
    statuses = {}
    cancelled_here = set()

    def get_statuses(reservation):
        rid = reservation["reservation_id"]
        if rid not in statuses:
            statuses[rid] = [caller("get_flight_status", flight_number=f["flight_number"], date=f["date"]) for f in reservation["flights"]]
        return statuses[rid]

    def execute(reservation, name, arguments, basis):
        action = {"name": name, "arguments": deepcopy(arguments)}
        display = {**action, "reservation_id": reservation["reservation_id"],
                   "scope": "whole_reservation" if name == "cancel_reservation" else "certificate",
                   "flights": deepcopy(reservation["flights"]), "passengers": deepcopy(reservation["passengers"]),
                   "policy_basis": basis}
        if name == "send_certificate":
            display["amount"] = arguments["amount"]
        proposal = {"user_id": user["user_id"], "actions": [display]}
        if confirm(proposal) != "yes":
            report["unresolved"].append({"reservation_id": reservation["reservation_id"], "reason": "confirmation_declined"})
            return False
        # Ordinary workflow logs its public inputs and decision. ECRC-specific
        # evidence envelopes and claim names are constructed by the outer adapter.
        context = {"request": deepcopy(request), "confirmation": deepcopy(proposal),
                   "user": deepcopy(user), "reservation": deepcopy(reservation),
                   "flight_statuses": get_statuses(reservation),
                   "eligibility": {"action": action, "basis": basis, "allowed": True}}
        record = {"action": action, "context": context, "business_basis": basis}
        report["proposals"].append(deepcopy(record))
        if authorize is not None:
            permission = authorize(**deepcopy(record))
            record["permission"] = permission
            report["proposals"][-1] = deepcopy(record)
            if not permission["allowed"]:
                report["unresolved"].append({"reservation_id": reservation["reservation_id"], "reason": "permission_denied"})
                return False
        before_methods = deepcopy(user["payment_methods"])
        caller(name, **arguments)
        if name == "cancel_reservation":
            observed = caller("get_reservation_details", reservation_id=reservation["reservation_id"])
            verified = observed.get("status") == "cancelled"
            if verified:
                cancelled_here.add(reservation["reservation_id"])
        else:
            observed = caller("get_user_details", user_id=user["user_id"])
            additions = set(observed["payment_methods"]) - set(before_methods)
            verified = len(additions) == 1 and all(observed["payment_methods"][key]["source"] == "certificate" and
                       observed["payment_methods"][key]["amount"] == arguments["amount"] for key in additions)
            user["payment_methods"] = deepcopy(observed["payment_methods"])
        report["actions"].append({**action, "reservation_id": reservation["reservation_id"], "verified": verified})
        if not verified:
            raise RuntimeError("Native write was not verified by readback")
        return True

    if request.get("cancellation"):
        part = request["cancellation"]
        for reservation in select(reservations, part["selector"]):
            basis, denial = cancel_basis(reservation, get_statuses(reservation), part["reason"])
            report["decisions"].append({"operation": "cancel_reservation", "reservation_id": reservation["reservation_id"], "allowed": bool(basis), "basis": basis, "denial": denial})
            if basis:
                execute(reservation, "cancel_reservation", {"reservation_id": reservation["reservation_id"]}, basis)
            elif denial in {"portion_already_flown_transfer_required", "missing_reason", "unknown_flight_status"}:
                report["unresolved"].append({"reservation_id": reservation["reservation_id"], "reason": denial})
    if request.get("compensation"):
        part = request["compensation"]
        for reservation in select(reservations, part["selector"]):
            basis, amount, denial = compensation_basis(user, reservation, get_statuses(reservation), part, cancelled_here)
            report["decisions"].append({"operation": "send_certificate", "reservation_id": reservation["reservation_id"], "allowed": bool(basis), "basis": basis, "denial": denial, "amount": amount})
            if basis:
                execute(reservation, "send_certificate", {"user_id": user["user_id"], "amount": amount}, basis)
    report["status"] = "partial_or_unresolved" if report["unresolved"] else "structured_request_processed"
    # This finite completion label requires actual readback; it is not an LLM explanation.
    report["reported_verified_actions"] = sum(action["verified"] for action in report["actions"])
    return report
