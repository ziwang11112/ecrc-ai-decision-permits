"""Fixed user-request proposals with optional qualification+permission dispatch.

The direct arm is a NEW native-tool execution comparator, not an official tau
agent and not a modified version of the existing ordinary_business workflow.
It keeps ownership checks, native fact queries and explicit confirmation; it
has no cancellation entitlement rule. Candidate generation never reads gold
actions, full database snapshots, or evaluator outputs.
"""
from copy import deepcopy
import hashlib
import json

AT = 1715799600.0


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def run(request, caller, confirm, *, gate=None):
    request = deepcopy(request)
    clause = request["cancellation"]
    if clause["selector"]["kind"] != "ids" or set(request) != {"user_id", "user_statement", "cancellation"}:
        raise ValueError("Only the frozen explicit-ID cancellation module is supported")
    user = caller("get_user_details", user_id=request["user_id"])
    if user["user_id"] != request["user_id"]:
        raise ValueError("Account identity mismatch")
    reservations = {}
    for rid in dict.fromkeys(user["reservations"]):
        r = caller("get_reservation_details", reservation_id=rid)
        if r["reservation_id"] != rid or r["user_id"] != user["user_id"]:
            raise ValueError("Reservation ownership mismatch")
        reservations[rid] = r
    requested = clause["selector"]["ids"]
    if len(set(requested)) != len(requested) or any(rid not in reservations for rid in requested):
        raise ValueError("Unknown, duplicate or unowned requested reservation")
    # Prepare the same factual candidate list before either arm writes.
    candidates = []
    for rid in requested:
        r = reservations[rid]
        statuses = [caller("get_flight_status", flight_number=f["flight_number"], date=f["date"]) for f in r["flights"]]
        action = {"name": "cancel_reservation", "arguments": {"reservation_id": rid}}
        candidates.append({"action": action, "reservation": deepcopy(r), "flight_statuses": statuses})
    report = {"status": "structured_module_processed", "candidates": deepcopy(candidates),
              "actions": [], "permissions": [], "unresolved": [], "model_calls": 0}
    for candidate in candidates:
        action, r = candidate["action"], candidate["reservation"]
        display = {**deepcopy(action), "reservation_id": r["reservation_id"], "scope": "whole_reservation",
                   "flights": deepcopy(r["flights"]), "passengers": deepcopy(r["passengers"])}
        proposal = {"user_id": user["user_id"], "actions": [display]}
        if confirm(proposal) != "yes":
            report["unresolved"].append({"reservation_id": r["reservation_id"], "reason": "confirmation_declined"})
            continue
        if gate is not None:
            # This is the trusted domain qualification adapter, not core ECRC
            # semantic understanding. A negative result STILL enters the gate.
            from ordinary_business import cancel_basis
            basis, denial = cancel_basis(r, candidate["flight_statuses"], clause["reason"])
            context = {"request": deepcopy(request), "confirmation": proposal,
                       "user": deepcopy(user), "reservation": deepcopy(r),
                       "flight_statuses": deepcopy(candidate["flight_statuses"]),
                       "eligibility": {"allowed": bool(basis), "basis": basis, "denial": denial}}
            permission = gate.authorize_candidate(
                decision_id="scope-" + digest({"request": request, "action": action})[:24],
                action=action, context=context, at=AT)
            report["permissions"].append(permission)
            authorization = permission["authorization"]
            if not authorization["allowed"]:
                continue
            gate.assert_action_binding(authorization, action)
        caller(action["name"], **action["arguments"])
        observed = caller("get_reservation_details", reservation_id=r["reservation_id"])
        verified = observed.get("status") == "cancelled"
        report["actions"].append({**deepcopy(action), "reservation_id": r["reservation_id"], "verified": verified})
        if not verified:
            raise RuntimeError("Native cancellation readback failed")
    report["reported_verified_actions"] = sum(a["verified"] for a in report["actions"])
    return report
