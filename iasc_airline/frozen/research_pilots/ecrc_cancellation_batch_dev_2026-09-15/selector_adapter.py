"""Shared public-selector resolution before the three frozen cancellation actors.

This adapter resolves objects, not entitlement.  It queries the native account
and all listed reservations, then calls the unchanged ordinary ``select`` for
its original selector kinds.  The new ``reservation_route`` selector uses the
native reservation's top-level endpoints, which can differ from every single
flight leg in a connecting itinerary; it requires a unique matching booking.
It never calls cancellation eligibility, reads gold targets, or synthesizes a
missing user reason.  The original selector and derivation remain in the output;
only the execution request uses resolved IDs for the frozen actor interface.
Subsequent actor reads are intentionally retained and counted by the runner.
"""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ORDINARY_SOURCE = HERE.parent / "ecrc_permission_business_2026-09-15" / "ordinary_business.py"


def _load_ordinary():
    name = "ecrc_cancel_batch_selector_ordinary"
    old = sys.modules.get(name)
    if old is not None:
        if Path(old.__file__).resolve() != ORDINARY_SOURCE.resolve():
            raise RuntimeError("unexpected ordinary selector source")
        return old
    spec = importlib.util.spec_from_file_location(name, ORDINARY_SOURCE)
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


ORDINARY = _load_ordinary()
SOURCE_FILES = [str(Path(__file__).resolve()), str(ORDINARY_SOURCE)]


def dependency_files():
    return list(SOURCE_FILES)


def source_manifest():
    return {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in SOURCE_FILES}


def _input_problem(request):
    if type(request) is not dict or set(request) != {"user_id", "user_statement", "cancellation"}:
        return "unsupported_request_shape"
    uid = request["user_id"]
    if not isinstance(uid, str) or not uid or uid != uid.strip():
        return "invalid_request_user"
    if not isinstance(request["user_statement"], str):
        return "invalid_user_statement"
    clause = request["cancellation"]
    if type(clause) is not dict or set(clause) != {"selector", "reason"}:
        return "unsupported_cancellation_clause"
    # 'unspecified' remains valid input and is not filled in here.
    if not isinstance(clause["reason"], str):
        return "invalid_reason_representation"
    selector = clause["selector"]
    if type(selector) is not dict:
        return "missing_selector"
    kind = selector.get("kind")
    if kind == "itinerary_conflict":
        return "unsupported_itinerary_conflict_selector"
    fields = {
        "ids": {"kind", "ids", "passenger_count"},
        "flight": {"kind", "flight_number", "origin", "destination", "date", "passenger_count"},
        "all_upcoming": {"kind", "passenger_count"},
        "reservation_route": {"kind", "origin", "destination", "passenger_count"},
    }
    if kind not in fields:
        return "unsupported_selector"
    if not set(selector).issubset(fields[kind]):
        return "unsupported_selector_qualifier"
    count = selector.get("passenger_count")
    if "passenger_count" in selector and (type(count) is not int or count < 1):
        return "invalid_passenger_count"
    if kind == "ids":
        ids = selector.get("ids")
        if type(ids) is not list:
            return "missing_or_malformed_reservation_ids"
        if any(not isinstance(rid, str) or not rid or rid != rid.strip() for rid in ids):
            return "missing_or_malformed_reservation_ids"
        if len(ids) != len(set(ids)):
            return "duplicate_reservation_ids"
    elif kind == "flight":
        identifying = {key: value for key, value in selector.items()
                       if key in {"flight_number", "origin", "destination", "date"}}
        if not identifying:
            return "flight_selector_without_identifying_fields"
        if any(not isinstance(value, str) or not value or value != value.strip()
               for value in identifying.values()):
            return "invalid_flight_selector_field"
    elif kind == "reservation_route":
        if not {"origin", "destination"}.issubset(selector):
            return "reservation_route_requires_both_endpoints"
        if any(not isinstance(selector[key], str) or not selector[key]
               or selector[key] != selector[key].strip() for key in ("origin", "destination")):
            return "invalid_reservation_route_endpoint"
    return None


def resolve(request, caller):
    """Resolve the same public selector for every arm, without action filtering.

    ``caller(name, **arguments)`` must return native decoded read responses and
    record the actual calls in the runner transcript.  On unresolved input this
    returns a retained case with no execution request, never a fabricated ID.
    """
    original = deepcopy(request)
    result = {"status": "unresolved", "original_request": original,
              "resolved_request": None, "selected_ids": [], "reason": None,
              "resolution_records": [], "eligibility_evaluated": False,
              "selector_semantics": "unchanged ordinary_business.select; exact native fields"}
    problem = _input_problem(original)
    if problem:
        result["reason"] = problem
        return result

    def query(name, **arguments):
        record = {"tool": name, "arguments": deepcopy(arguments)}
        result["resolution_records"].append(record)
        try:
            response = caller(name, **arguments)
        except Exception as exc:
            record["error"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        record["response"] = deepcopy(response)
        return response

    try:
        user = query("get_user_details", user_id=original["user_id"])
    except Exception:
        result["reason"] = "native_account_query_failed"
        return result
    if type(user) is not dict or user.get("user_id") != original["user_id"]:
        result["reason"] = "account_identity_mismatch"
        return result
    account_ids = user.get("reservations")
    if (type(account_ids) is not list or any(not isinstance(rid, str) or not rid
                                           or rid != rid.strip() for rid in account_ids)):
        result["reason"] = "invalid_account_reservation_list"
        return result
    reservations = []
    for rid in dict.fromkeys(account_ids):
        try:
            reservation = query("get_reservation_details", reservation_id=rid)
        except Exception:
            result["reason"] = "native_reservation_query_failed"
            return result
        if (type(reservation) is not dict or reservation.get("reservation_id") != rid
                or reservation.get("user_id") != user["user_id"]):
            result["reason"] = "reservation_identity_or_ownership_mismatch"
            return result
        reservations.append(deepcopy(reservation))

    selector = original["cancellation"]["selector"]
    # Unknown explicit IDs are a resolution failure, never silently dropped.
    if selector["kind"] == "ids" and any(rid not in account_ids for rid in selector["ids"]):
        result["reason"] = "unknown_or_unowned_selected_reservation"
        return result
    selector_stage = "ordinary_selector"
    try:
        if selector["kind"] == "reservation_route":
            selector_stage = "reservation_route_selector"
            result["selector_semantics"] = "unique exact native reservation-level origin/destination; passenger_count after route uniqueness"
            matches = [reservation for reservation in reservations
                       if reservation.get("origin") == selector["origin"]
                       and reservation.get("destination") == selector["destination"]]
            result["resolution_records"].append({"stage": selector_stage, "selector": deepcopy(selector),
                                                 "route_match_ids": [row["reservation_id"] for row in matches]})
            if not matches:
                result["reason"] = "no_candidate"
                return result
            if len(matches) != 1:
                result["reason"] = "ambiguous_reservation_route"
                return result
            chosen = matches
            if "passenger_count" in selector:
                chosen = [row for row in chosen if len(row["passengers"]) == selector["passenger_count"]]
        else:
            chosen = ORDINARY.select(reservations, deepcopy(selector))
    except ValueError as exc:
        result["reason"] = ("ambiguous_or_unmatched_flight_selector" if selector["kind"] == "flight"
                            else "selector_resolution_failed")
        result["resolution_records"].append({"stage": selector_stage, "error": str(exc)})
        return result
    except (KeyError, TypeError, IndexError) as exc:
        result["reason"] = "native_record_not_usable_by_selector"
        result["resolution_records"].append({"stage": selector_stage,
                                             "error": {"type": type(exc).__name__, "message": str(exc)}})
        return result
    selected_ids = [reservation["reservation_id"] for reservation in chosen]
    result["resolution_records"].append({"stage": selector_stage, "selector": deepcopy(selector),
                                         "selected_ids": list(selected_ids)})
    if not selected_ids:
        result["reason"] = "no_candidate"
        return result
    resolved = deepcopy(original)
    resolved["cancellation"]["selector"] = {"kind": "ids", "ids": list(selected_ids)}
    result.update(status="resolved", resolved_request=resolved, selected_ids=selected_ids,
                  reason=None)
    return result
