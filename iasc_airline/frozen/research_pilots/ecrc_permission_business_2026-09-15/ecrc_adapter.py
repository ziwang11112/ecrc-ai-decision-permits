"""Business adapter around the unchanged paper S8 ECRC permission core.

This module evaluates evidence *metadata*, not airline policy or evidence truth.
The caller supplies an already selected business action and independently made
policy-eligibility evidence.  The two business operations have separate fixed
policy identities and nonbinding 100-unit limits; no money-budget claim is made.

Issuance and arm are real original-core operations.  No finish/receipt is forged
for the native airline tool: its effects are not the paper's atomic durable sink.
An allowed result only authorizes the bound action.  Before dispatch callers can
use assert_action_binding; this wrapper check is separate from core claim logic.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
CORE_ROOT = HERE.parents[1] / "output" / "AIR-014_IASC_Reproducibility" / "end_to_end"
GOVERNANCE_ROOT = CORE_ROOT / "legacy_snapshot/source_snapshot/agentic_eeg_dm/governance"
SOURCE_FILES = [
    str(CORE_ROOT / "ecrc_e2e.py"),
    str(CORE_ROOT / "legacy_snapshot/ecrc_adapter.py"),
    str(GOVERNANCE_ROOT.parent / "__init__.py"),
    *[str(GOVERNANCE_ROOT / name) for name in (
        "__init__.py", "adjudicator.py", "canonical.py", "enforcement.py",
        "exceptions.py", "ledger.py", "models.py", "verifier.py",
    )],
]


def core_files() -> list[str]:
    """Return all imported authoritative source paths for the parent's freeze."""
    return list(SOURCE_FILES)


def source_manifest() -> dict[str, str]:
    return {path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in SOURCE_FILES}


def _load_core():
    expected = {
        "ecrc_e2e": CORE_ROOT / "ecrc_e2e.py",
        "legacy_snapshot.ecrc_adapter": CORE_ROOT / "legacy_snapshot/ecrc_adapter.py",
        "agentic_eeg_dm": GOVERNANCE_ROOT.parent / "__init__.py",
    }
    for name, path in expected.items():
        old = sys.modules.get(name)
        if old is not None and Path(getattr(old, "__file__", "")).resolve() != path.resolve():
            raise RuntimeError("a different ECRC source is already loaded: " + name)
    old_path = list(sys.path)
    old_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(CORE_ROOT))
        s8 = importlib.import_module("ecrc_e2e")
        governance = importlib.import_module("agentic_eeg_dm.governance")
    finally:
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_bytecode
    for name, path in expected.items():
        if Path(sys.modules[name].__file__).resolve() != path.resolve():
            raise RuntimeError("unexpected ECRC source: " + name)
    return s8, governance


S8, G = _load_core()

CLAIMS = {
    "cancel_reservation": "cancel_booking",
    "send_certificate": "issue_compensation",
}
EVIDENCE_SOURCES = {
    "user_request": "scripted_user",
    "account_record": "native_airline",
    "reservation_record": "native_airline",
    "policy_eligibility": "public_policy_checker",
}
EVIDENCE_MAX_AGE_SECONDS = 300
CAPACITY = 100
MODEL_ID = "structured-business-proposal-not-llm"


def _timestamp(value: float) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("time must be finite UTC Unix seconds")
    try:
        return G.normalize_timestamp(datetime.fromtimestamp(value, timezone.utc).isoformat())
    except (OverflowError, OSError) as exc:
        raise ValueError("time is out of range") from exc


def _action_copy(action: dict) -> dict:
    if type(action) is not dict or set(action) != {"name", "arguments"}:
        raise ValueError("action requires exactly name and arguments")
    if action["name"] not in CLAIMS or type(action["arguments"]) is not dict:
        raise ValueError("unsupported action or arguments")
    if any(not isinstance(key, str) for key in action["arguments"]):
        raise ValueError("argument names must be strings")
    return json.loads(G.canonical_json(action))


def _policy(operation: str, model_hash: str) -> dict:
    return G.PolicyManifest(
        policy_id="airline-permission-dev-" + operation,
        revision=1,
        issuer_id="local-business-permission-experiment",
        effective_from="2000-01-01T00:00:00Z",
        expires_at="2100-01-01T00:00:00Z",
        approved_models=(G.ModelBinding(MODEL_ID, model_hash),),
        evidence_rules=tuple(G.EvidenceRule(kind, (source,), ("1",), EVIDENCE_MAX_AGE_SECONDS, True)
                             for kind, source in EVIDENCE_SOURCES.items()),
        score_threshold=0.6,
        uncertainty_threshold=0.9,
        review_band_width=0.03,
        alert_capacity=CAPACITY,
        review_capacity=0,
        capacity_scope="session",
        claim_rules=(G.ClaimRule(CLAIMS[operation], ("alert",),
                                 required_evidence_types=tuple(EVIDENCE_SOURCES)),),
        blocked_claim_ids=tuple(claim for name, claim in CLAIMS.items() if name != operation),
        allowed_routes=("alert", "abstain", "no_action"),
    ).to_dict()


def _evidence_items(records: list[dict]) -> tuple:
    if type(records) is not list:
        raise ValueError("evidence must be a list")
    required = {"id", "type", "source", "observed_at", "available_at", "body_hash"}
    items = []
    for record in records:
        if type(record) is not dict or set(record) != required:
            raise ValueError("invalid friendly evidence fields")
        items.append(G.EvidenceItem(
            evidence_id=record["id"], evidence_type=record["type"],
            source=record["source"], schema_version="1",
            observed_at=_timestamp(record["observed_at"]),
            available_at=_timestamp(record["available_at"]),
            provenance_hash=record["body_hash"], requested_for_use=True,
        ))
    return tuple(items)


class PermissionGate:
    """Issue and arm the same paper core's permission for a bound business action."""

    def __init__(self, db_path):
        self.db_path = str(db_path)
        self.model_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.policies = {name: _policy(name, self.model_hash) for name in CLAIMS}
        self.core = S8.Adapter(self.db_path)
        for policy in self.policies.values():
            self.core.ledger.register_policy(G.PolicyManifest.from_dict(policy))

    def authorize(self, *, decision_id: str, action: dict, evidence: list[dict],
                  at: float, requested_claim: str) -> dict:
        if not isinstance(decision_id, str) or not decision_id or decision_id != decision_id.strip():
            raise ValueError("decision_id must be nonempty canonical text")
        action = _action_copy(action)
        stamp = _timestamp(at)
        action_hash = G.canonical_hash(action)
        items = _evidence_items(evidence)
        scope_valid = isinstance(requested_claim, str) and requested_claim == CLAIMS[action["name"]]
        if not items:
            return {"permit": None, "allowed": False, "reason": "empty_evidence_envelope",
                    "action_hash": action_hash, "armed": False,
                    "requested_claim": requested_claim, "decision_id": decision_id,
                    "boundary": "wrapper_schema_rejection"}
        # Scope rejection is explicit adapter logic, not new core semantics.
        # A low dispatch-control score asks the original core for a nonaction.
        binding = {"action": action, "requested_claim": requested_claim}
        proposal = G.ProposalEnvelope(
            decision_id=decision_id,
            subject_id="shared-business-subject",
            session_id="airline-business-permission-dev",
            model_id=MODEL_ID, model_version="1", model_hash=self.model_hash,
            score=0.8 if scope_valid else 0.2, uncertainty=0.2,
            proposed_action=action["name"], proposed_at=stamp,
            input_hash=G.canonical_hash(binding),
            validation_scope_id="business-action-metadata-only-v1",
        )
        envelope = G.EvidenceEnvelope(decision_id=decision_id, created_at=stamp, items=items)
        request = {"policy": self.policies[action["name"]], "proposal": proposal.to_dict(),
                   "evidence": envelope.to_dict()}
        self.core.ingest(request, stamp)
        permit = self.core.issue(decision_id, stamp)
        allowed = (scope_valid and permit["route"] == "alert"
                   and requested_claim in permit["permitted_claim_ids"])
        if allowed:
            # Wrapper binding validation precedes immutable original-core arm.
            self._assert_request_binding(decision_id, action, requested_claim)
            self.core.arm(permit, stamp)
        return {"permit": permit, "allowed": allowed,
                "reason": permit["reason_code"] if scope_valid else "requested_claim_not_allowed_for_action",
                "action_hash": action_hash, "armed": allowed,
                "requested_claim": requested_claim, "decision_id": decision_id,
                "boundary": "core_permission_with_wrapper_action_binding"}

    def _assert_request_binding(self, decision_id: str, action: dict, requested_claim: str) -> None:
        row = self.core.get_request(decision_id)
        if row is None:
            raise ValueError("no bound request")
        request = json.loads(row["request_json"])
        proposal = request["proposal"]
        if (proposal["proposed_action"] != action["name"] or
                proposal["input_hash"] != G.canonical_hash({"action": action, "requested_claim": requested_claim})):
            raise ValueError("action or requested claim differs from issued request")

    def assert_action_binding(self, authorization: dict, action: dict) -> None:
        """Verify the supplied action is exactly the issued, armed business action.

        This checks stored data, not just caller-owned booleans or action_hash.
        It does not validate the business argument semantics or deduplicate native
        effects.  In particular, authorization replay must not imply safe replay
        of the airline operation, which has no effect-key contract here.
        """
        action = _action_copy(action)
        decision_id = authorization.get("decision_id")
        claim = authorization.get("requested_claim")
        self._assert_request_binding(decision_id, action, claim)
        stored = self.core.get_permit(decision_id)
        if (not authorization.get("allowed") or authorization.get("armed") is not True or
                stored is None or authorization.get("permit") != stored or
                authorization.get("action_hash") != G.canonical_hash(action) or
                claim != CLAIMS[action["name"]] or stored["route"] != "alert" or
                claim not in stored["permitted_claim_ids"] or
                self.core.get_job(stored["permit_id"]) is None):
            raise ValueError("authorization is not a stored armed action permission")

    def snapshot(self) -> dict:
        return self.core.snapshot()
