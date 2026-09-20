"""Cancellation scope adapter using the unchanged earlier ECRC permission core.

The trusted adapter checks native-record bindings and recomputes the existing
public cancellation predicate.  Only a positive result emits the typed
``cancellation_eligible`` record.  A negative candidate still reaches original
ingest/issue: the original claim rule produces abstention without dispatch.

This is not semantic reasoning by ECRC.  Native reads and the caller's recorded
confirmation are trusted; the core checks their supplied metadata and closes
the final permission.  Native airline writes have no atomic ECRC receipt, so
successful authorization remains held and no completion is manufactured.
"""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "ecrc_permission_business_2026-09-15"


def _load_source(name, path):
    old = sys.modules.get(name)
    if old is not None:
        if Path(old.__file__).resolve() != path.resolve():
            raise RuntimeError("unexpected source for " + name)
        return old
    spec = importlib.util.spec_from_file_location(name, path)
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


PREVIOUS_ADAPTER = _load_source("ecrc_scope_previous_adapter", PREVIOUS / "ecrc_adapter.py")
PREVIOUS_BUSINESS = _load_source("ecrc_scope_previous_business", PREVIOUS / "ordinary_business.py")
G, S8 = PREVIOUS_ADAPTER.G, PREVIOUS_ADAPTER.S8
CAPACITY = 100
EVIDENCE_MAX_AGE_SECONDS = PREVIOUS_ADAPTER.EVIDENCE_MAX_AGE_SECONDS
MODEL_ID = PREVIOUS_ADAPTER.MODEL_ID
EVIDENCE_SOURCES = {
    "user_request": "scripted_user",
    "account_record": "native_airline",
    "reservation_record": "native_airline",
    "cancellation_eligible": "public_policy_checker",
}
SOURCE_FILES = list(dict.fromkeys([
    str(Path(__file__).resolve()),
    str(PREVIOUS / "ecrc_adapter.py"),
    str(PREVIOUS / "ordinary_business.py"),
    *PREVIOUS_ADAPTER.core_files(),
]))


def core_files():
    """All executed adapter, predicate, and original-core dependencies."""
    return list(SOURCE_FILES)


def source_manifest():
    return {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in SOURCE_FILES}


def _bound_context(action, context):
    """Validate one native candidate; return an independent predicate result.

    The parent runner calls this only after its shared confirm() returns yes.
    A display is not itself proof of a user response; the runner retains that
    response in its transcript.  This adapter verifies what was displayed.
    """
    if type(action) is not dict or set(action) != {"name", "arguments"}:
        raise ValueError("action requires exactly name and arguments")
    if action["name"] != "cancel_reservation":
        raise ValueError("scope gate supports only cancel_reservation")
    args = action["arguments"]
    if type(args) is not dict or set(args) != {"reservation_id"}:
        raise ValueError("cancellation requires exactly reservation_id")
    rid = args["reservation_id"]
    if not isinstance(rid, str) or not rid or rid != rid.strip():
        raise ValueError("reservation_id must be canonical nonempty text")
    required = {"request", "confirmation", "user", "reservation", "flight_statuses", "eligibility"}
    if type(context) is not dict or not required.issubset(context):
        raise ValueError("missing candidate context")
    request, user, reservation = context["request"], context["user"], context["reservation"]
    if any(type(value) is not dict for value in (request, user, reservation)):
        raise ValueError("request and native records must be objects")
    uid = request.get("user_id")
    if (not isinstance(uid, str) or not uid or uid != user.get("user_id")
            or uid != reservation.get("user_id") or rid != reservation.get("reservation_id")
            or rid not in user.get("reservations", [])):
        raise ValueError("action, request, account and reservation binding mismatch")
    cancellation = request.get("cancellation")
    if type(cancellation) is not dict:
        raise ValueError("a cancellation request is required")
    selector = cancellation.get("selector")
    if (type(selector) is not dict or selector.get("kind") != "ids"
            or type(selector.get("ids")) is not list or rid not in selector["ids"]):
        raise ValueError("candidate not in the explicitly requested reservation IDs")
    if not isinstance(cancellation.get("reason"), str):
        raise ValueError("a recorded cancellation reason is required")

    confirmation = context["confirmation"]
    if (type(confirmation) is not dict or confirmation.get("user_id") != uid
            or type(confirmation.get("actions")) is not list):
        raise ValueError("missing bound confirmation display")
    matching = [row for row in confirmation["actions"]
                if type(row) is dict and row.get("name") == action["name"]
                and row.get("arguments") == args]
    if len(matching) != 1:
        raise ValueError("confirmation must display the candidate exactly once")
    display = matching[0]
    if (display.get("reservation_id") != rid or display.get("scope") != "whole_reservation"
            or display.get("flights") != reservation.get("flights")
            or display.get("passengers") != reservation.get("passengers")):
        raise ValueError("confirmation scope does not match the native reservation")

    statuses = context["flight_statuses"]
    if type(statuses) is not list:
        raise ValueError("flight_statuses must be an ordered native response list")
    basis, denial = PREVIOUS_BUSINESS.cancel_basis(reservation, statuses, cancellation["reason"])
    checked = {"allowed": bool(basis), "basis": basis, "denial": denial}
    supplied = context["eligibility"]
    if (type(supplied) is not dict or set(supplied) != set(checked)
            or type(supplied.get("allowed")) is not bool or supplied != checked):
        raise ValueError("eligibility does not match the public cancellation predicate")
    return checked


class ScopeGate(PREVIOUS_ADAPTER.PermissionGate):
    """Actual original issuance/arm with a cancellation-only evidence policy."""

    def __init__(self, db_path):
        self.db_path = str(db_path)
        self.model_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        policy = G.PolicyManifest(
            policy_id="airline-action-scope-dev-cancel", revision=1,
            issuer_id="local-business-scope-experiment",
            effective_from="2000-01-01T00:00:00Z", expires_at="2100-01-01T00:00:00Z",
            approved_models=(G.ModelBinding(MODEL_ID, self.model_hash),),
            evidence_rules=tuple(G.EvidenceRule(kind, (source,), ("1",),
                                               EVIDENCE_MAX_AGE_SECONDS, True)
                                 for kind, source in EVIDENCE_SOURCES.items()),
            score_threshold=0.6, uncertainty_threshold=0.9, review_band_width=0.03,
            alert_capacity=CAPACITY, review_capacity=0, capacity_scope="session",
            claim_rules=(G.ClaimRule("cancel_booking", ("alert",),
                                    required_evidence_types=tuple(EVIDENCE_SOURCES)),),
            blocked_claim_ids=("issue_compensation",),
            allowed_routes=("alert", "abstain", "no_action"),
        ).to_dict()
        self.policies = {"cancel_reservation": policy}
        self.core = S8.Adapter(self.db_path)
        self.core.ledger.register_policy(G.PolicyManifest.from_dict(policy))

    def authorize_candidate(self, decision_id, action, context, at):
        """Send positive AND negative candidates to unchanged ingest/issue.

        ``at`` is a shared logical observation/proposal timestamp supplied by
        the runner; it is not evidence of real wall-clock latency or freshness.
        There are no artificial source/schema/time perturbations here.
        """
        action, context = deepcopy(action), deepcopy(context)
        checked = _bound_context(action, context)
        bodies = {
            "user_request": {"request": context["request"], "confirmation": context["confirmation"]},
            "account_record": context["user"],
            "reservation_record": {
                "reservation": context["reservation"],
                "flight_statuses": context["flight_statuses"],
                "eligibility_check": checked,
            },
        }
        if checked["allowed"]:
            bodies["cancellation_eligible"] = {
                "action": action, "user_id": context["user"]["user_id"],
                "reservation_id": context["reservation"]["reservation_id"],
                "reason": context["request"]["cancellation"]["reason"], **checked,
            }
        records = [{"id": decision_id + ":" + kind, "type": kind,
                    "source": EVIDENCE_SOURCES[kind], "observed_at": at, "available_at": at,
                    "body_hash": G.canonical_hash(body)} for kind, body in bodies.items()]
        inputs = {"decision_id": decision_id, "action": action, "evidence": records,
                  "at": at, "requested_claim": "cancel_booking"}
        # No negative-business early return: original claim evaluation decides.
        authorization = super().authorize(**inputs)
        return {"input": inputs, "bodies": bodies, "authorization": authorization}
