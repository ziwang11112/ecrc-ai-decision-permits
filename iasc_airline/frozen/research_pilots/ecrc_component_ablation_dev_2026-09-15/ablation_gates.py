"""Isolated component removals; original ScopeGate and core sources stay frozen.

``without_claim_evidence_requirement`` removes only cancellation_eligible from
the cancellation claim's required types.  Domain checks and positive-attestation
generation remain inherited, so negative evidence is neither removed nor forged.

``without_metadata_qualification`` bypasses source/schema-version and evidence
observation/availability/freshness qualification only.  Known evidence types,
requested_for_use, policy use_allowed, structural parsing, proposal validation,
claims, arm and action binding remain enforced.  The original issue function's
code runs with an isolated globals dictionary, never a shared-module patch.

These are explicit mechanism ablations, not ordinary workflow baselines.  No
native tool executes here, and no airline completion receipt is manufactured.
"""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys
import types


HERE = Path(__file__).resolve().parent
SCOPE_SOURCE = HERE.parent / "ecrc_action_scope_dev_2026-09-15" / "scope_gate.py"


def _load_scope():
    name = "ecrc_component_frozen_scope_gate"
    old = sys.modules.get(name)
    if old is not None:
        if Path(old.__file__).resolve() != SCOPE_SOURCE.resolve():
            raise RuntimeError("unexpected frozen scope adapter source")
        return old
    spec = importlib.util.spec_from_file_location(name, SCOPE_SOURCE)
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


SCOPE = _load_scope()
G, S8 = SCOPE.G, SCOPE.S8
MODES = ("full", "without_claim_evidence_requirement", "without_metadata_qualification")
DESCRIPTORS = {
    "full": "Unmodified frozen ScopeGate, domain checker and original ECRC core.",
    "without_claim_evidence_requirement": "Only cancellation_eligible is removed from cancel_booking.required_evidence_types; domain checks, evidence generation and all other policy fields remain unchanged.",
    "without_metadata_qualification": "Bypass only source, schema-version, observed_at, available_at and max-age evidence qualification; retain configured type vocabulary, requested_for_use, use_allowed and all other core checks.",
}
SOURCE_FILES = list(dict.fromkeys([str(Path(__file__).resolve()), *SCOPE.core_files()]))


def dependency_files():
    return list(SOURCE_FILES)


def core_files():
    return dependency_files()


def source_manifest():
    return {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in SOURCE_FILES}


class WithoutClaimEvidenceRequirementGate(SCOPE.ScopeGate):
    def __init__(self, db_path):
        # This is the frozen ScopeGate constructor's minimal policy setup with
        # one declared policy change, registered only once in this new database.
        # Proposal generation is inherited unchanged, so its original hash stays.
        self.db_path = str(db_path)
        self.model_hash = hashlib.sha256(SCOPE_SOURCE.read_bytes()).hexdigest()
        policy = G.PolicyManifest(
            policy_id="airline-action-scope-dev-cancel", revision=1,
            issuer_id="local-business-scope-experiment",
            effective_from="2000-01-01T00:00:00Z", expires_at="2100-01-01T00:00:00Z",
            approved_models=(G.ModelBinding(SCOPE.MODEL_ID, self.model_hash),),
            evidence_rules=tuple(G.EvidenceRule(kind, (source,), ("1",),
                                               SCOPE.EVIDENCE_MAX_AGE_SECONDS, True)
                                 for kind, source in SCOPE.EVIDENCE_SOURCES.items()),
            score_threshold=0.6, uncertainty_threshold=0.9, review_band_width=0.03,
            alert_capacity=SCOPE.CAPACITY, review_capacity=0, capacity_scope="session",
            claim_rules=(G.ClaimRule("cancel_booking", ("alert",), required_evidence_types=tuple(
                kind for kind in SCOPE.EVIDENCE_SOURCES if kind != "cancellation_eligible")),),
            blocked_claim_ids=("issue_compensation",),
            allowed_routes=("alert", "abstain", "no_action"),
        ).to_dict()
        self.policies = {"cancel_reservation": policy}
        self.core = S8.Adapter(self.db_path)
        self.core.ledger.register_policy(G.PolicyManifest.from_dict(policy))


class NoMetadataAdjudicator(G.OrderedAdjudicator):
    @staticmethod
    def _gate_evidence(manifest, proposal, evidence):
        """Keep type/use controls while bypassing metadata qualification."""
        rules = {rule.evidence_type: rule for rule in manifest.evidence_rules}
        admitted_ids, used_ids, excluded_ids, used_types = [], [], [], set()
        for item in evidence.items:
            rule = rules.get(item.evidence_type)
            if rule is None:
                excluded_ids.append(item.evidence_id)
                continue
            admitted_ids.append(item.evidence_id)
            if item.requested_for_use and rule.use_allowed:
                used_ids.append(item.evidence_id)
                used_types.add(item.evidence_type)
        return (tuple(sorted(admitted_ids)), tuple(sorted(used_ids)),
                tuple(sorted(excluded_ids)), used_types)


ORIGINAL_ISSUE = S8.Adapter.issue
ORIGINAL_ADJUDICATOR_BINDING = ORIGINAL_ISSUE.__globals__["OrderedAdjudicator"]
_isolated_issue_globals = dict(ORIGINAL_ISSUE.__globals__)
_isolated_issue_globals["OrderedAdjudicator"] = NoMetadataAdjudicator
_isolated_issue = types.FunctionType(
    ORIGINAL_ISSUE.__code__, _isolated_issue_globals,
    name=ORIGINAL_ISSUE.__name__, argdefs=ORIGINAL_ISSUE.__defaults__,
    closure=ORIGINAL_ISSUE.__closure__,
)
_isolated_issue.__kwdefaults__ = deepcopy(ORIGINAL_ISSUE.__kwdefaults__)
_isolated_issue.__annotations__ = dict(ORIGINAL_ISSUE.__annotations__)
_isolated_issue.__doc__ = ORIGINAL_ISSUE.__doc__
_isolated_issue.__qualname__ = "NoMetadataAdapter.issue"


class NoMetadataAdapter(S8.Adapter):
    issue = _isolated_issue


class WithoutMetadataQualificationGate(SCOPE.ScopeGate):
    def __init__(self, db_path):
        super().__init__(db_path)
        # The frozen constructor has only created tables and registered policy;
        # reopening its same database neither changes policy nor issues a grant.
        self.core = NoMetadataAdapter(self.db_path)


def make_gate(mode, db_path):
    if mode == "full":
        return SCOPE.ScopeGate(db_path)
    if mode == "without_claim_evidence_requirement":
        return WithoutClaimEvidenceRequirementGate(db_path)
    if mode == "without_metadata_qualification":
        return WithoutMetadataQualificationGate(db_path)
    raise ValueError("Unknown ablation gate mode: " + str(mode))
