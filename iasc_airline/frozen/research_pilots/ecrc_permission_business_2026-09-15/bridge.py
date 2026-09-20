"""Explicit business-to-ECRC evidence adapter and controlled metadata probes."""
from copy import deepcopy
import hashlib
import json

AT = 1715799600.0
CONDITIONS = ("normal", "missing_eligibility", "stale_reservation", "unknown_source", "future_available")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def envelopes(action, context, condition="normal"):
    if condition not in CONDITIONS:
        raise ValueError("Undeclared condition")
    decision = "decision-" + digest({"request": context["request"], "action": action})[:24]
    bodies = [
        ("user_request", "scripted_user", {"request": context["request"], "confirmation": context["confirmation"]}),
        ("account_record", "native_airline", context["user"]),
        ("reservation_record", "native_airline", {"reservation": context["reservation"], "flight_statuses": context["flight_statuses"]}),
        ("policy_eligibility", "public_policy_checker", context["eligibility"]),
    ]
    records = [{"id": decision + ":" + kind, "type": kind, "source": source,
                "observed_at": AT, "available_at": AT, "body_hash": digest(body)} for kind, source, body in bodies]
    original = deepcopy(records)
    if condition == "missing_eligibility":
        records = [r for r in records if r["type"] != "policy_eligibility"]
    for record in records:
        if record["type"] != "reservation_record":
            continue
        if condition == "stale_reservation":
            record["observed_at"] = AT - 301
        elif condition == "unknown_source":
            record["source"] = "unqualified_cached_source"
        elif condition == "future_available":
            record["available_at"] = AT + 1
    return {
        "decision_id": decision, "action": deepcopy(action), "evidence": records, "at": AT,
        "requested_claim": {"cancel_reservation": "cancel_booking", "send_certificate": "issue_compensation"}[action["name"]],
    }, {"condition": condition, "original_evidence": original, "presented_evidence": records,
        "body_content_modified": False, "native_business_facts_modified": False,
        "meaning": "controlled metadata failure, not a naturally observed benchmark error"}
