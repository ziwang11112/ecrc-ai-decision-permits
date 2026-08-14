"""Immutable schemas for the ECRC decision-permit core."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from .canonical import (
    canonical_hash,
    normalize_timestamp,
    parse_timestamp,
    to_primitive,
)

ROUTES = ("alert", "review", "abstain", "no_action")
ACTION_ROUTES = ("alert", "review")
RESOURCES = ("alert", "review")
RECEIPT_STATUSES = ("executed", "not_executed", "failed")
GENESIS_RECEIPT_HASH = "0" * 64
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _required_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _hash_text(name: str, value: str) -> str:
    normalized = _required_text(name, value).lower()
    if not _HASH_RE.fullmatch(normalized):
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    return normalized


def _unique_tuple(name: str, values: Any) -> tuple[str, ...]:
    normalized = tuple(_required_text(name, str(value)) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


class SchemaArtifact:
    SCHEMA: ClassVar[dict[str, Any]] = {}

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    @property
    def content_hash(self) -> str:
        return canonical_hash(self)

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        return copy.deepcopy(cls.SCHEMA)


@dataclass(frozen=True)
class ClaimRule(SchemaArtifact):
    claim_id: str
    routes: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()
    required_evidence_types: tuple[str, ...] = ()

    SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["claim_id", "routes", "reason_codes", "required_evidence_types"],
        "properties": {
            "claim_id": {"type": "string", "minLength": 1},
            "routes": {
                "type": "array",
                "items": {"enum": list(ROUTES)},
                "minItems": 1,
                "uniqueItems": True,
            },
            "reason_codes": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "uniqueItems": True,
            },
            "required_evidence_types": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "uniqueItems": True,
            },
        },
    }

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _required_text("claim_id", self.claim_id))
        routes = _unique_tuple("routes", self.routes)
        if not routes or any(route not in ROUTES for route in routes):
            raise ValueError(f"routes must be a non-empty subset of {ROUTES}")
        object.__setattr__(self, "routes", routes)
        object.__setattr__(
            self, "reason_codes", _unique_tuple("reason_codes", self.reason_codes)
        )
        object.__setattr__(
            self,
            "required_evidence_types",
            _unique_tuple("required_evidence_types", self.required_evidence_types),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ClaimRule:
        return cls(
            claim_id=str(value["claim_id"]),
            routes=tuple(value["routes"]),
            reason_codes=tuple(value.get("reason_codes", ())),
            required_evidence_types=tuple(value.get("required_evidence_types", ())),
        )


@dataclass(frozen=True)
class ModelBinding(SchemaArtifact):
    """An explicit, inseparable model identity-to-artifact binding."""

    model_id: str
    model_hash: str

    SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["model_id", "model_hash"],
        "properties": {
            "model_id": {"type": "string", "minLength": 1},
            "model_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
    }

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_id", _required_text("model_id", self.model_id))
        object.__setattr__(
            self, "model_hash", _hash_text("model_hash", self.model_hash)
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ModelBinding:
        return cls(model_id=str(value["model_id"]), model_hash=str(value["model_hash"]))


@dataclass(frozen=True)
class EvidenceRule(SchemaArtifact):
    """Executable admission and use rule for one evidence type."""

    evidence_type: str
    allowed_sources: tuple[str, ...]
    allowed_schema_versions: tuple[str, ...]
    max_age_seconds: int
    use_allowed: bool = True

    SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "evidence_type",
            "allowed_sources",
            "allowed_schema_versions",
            "max_age_seconds",
            "use_allowed",
        ],
        "properties": {
            "evidence_type": {"type": "string", "minLength": 1},
            "allowed_sources": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
                "uniqueItems": True,
            },
            "allowed_schema_versions": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
                "uniqueItems": True,
            },
            "max_age_seconds": {"type": "integer", "minimum": 0},
            "use_allowed": {"type": "boolean"},
        },
    }

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_type", _required_text("evidence_type", self.evidence_type)
        )
        sources = _unique_tuple("allowed_sources", self.allowed_sources)
        schemas = _unique_tuple("allowed_schema_versions", self.allowed_schema_versions)
        if not sources or not schemas:
            raise ValueError(
                "evidence rules require at least one source and schema version"
            )
        object.__setattr__(self, "allowed_sources", sources)
        object.__setattr__(self, "allowed_schema_versions", schemas)
        if (
            not isinstance(self.max_age_seconds, int)
            or isinstance(self.max_age_seconds, bool)
            or self.max_age_seconds < 0
        ):
            raise ValueError("max_age_seconds must be a non-negative integer")
        if not isinstance(self.use_allowed, bool):
            raise ValueError("use_allowed must be boolean")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvidenceRule:
        return cls(
            evidence_type=str(value["evidence_type"]),
            allowed_sources=tuple(value["allowed_sources"]),
            allowed_schema_versions=tuple(value["allowed_schema_versions"]),
            max_age_seconds=int(value["max_age_seconds"]),
            use_allowed=bool(value.get("use_allowed", True)),
        )


@dataclass(frozen=True)
class PolicyManifest(SchemaArtifact):
    policy_id: str
    revision: int
    issuer_id: str
    effective_from: str
    expires_at: str
    approved_models: tuple[ModelBinding, ...]
    evidence_rules: tuple[EvidenceRule, ...]
    score_threshold: float
    uncertainty_threshold: float
    review_band_width: float
    alert_capacity: int
    review_capacity: int
    capacity_scope: str
    claim_rules: tuple[ClaimRule, ...] = ()
    blocked_claim_ids: tuple[str, ...] = ()
    allowed_routes: tuple[str, ...] = ROUTES
    failure_mode: str = "fail_closed"

    SCHEMA: ClassVar[dict[str, Any]] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ECRC PolicyManifest",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "policy_id",
            "revision",
            "issuer_id",
            "effective_from",
            "expires_at",
            "approved_models",
            "evidence_rules",
            "score_threshold",
            "uncertainty_threshold",
            "review_band_width",
            "alert_capacity",
            "review_capacity",
            "capacity_scope",
            "claim_rules",
            "blocked_claim_ids",
            "allowed_routes",
            "failure_mode",
        ],
        "properties": {
            "policy_id": {"type": "string", "minLength": 1},
            "revision": {"type": "integer", "minimum": 1},
            "issuer_id": {"type": "string", "minLength": 1},
            "effective_from": {"type": "string", "format": "date-time"},
            "expires_at": {"type": "string", "format": "date-time"},
            "approved_models": {
                "type": "array",
                "items": ModelBinding.SCHEMA,
                "minItems": 1,
            },
            "evidence_rules": {
                "type": "array",
                "items": EvidenceRule.SCHEMA,
                "minItems": 1,
            },
            "score_threshold": {"type": "number", "minimum": 0, "maximum": 1},
            "uncertainty_threshold": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "review_band_width": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "alert_capacity": {"type": "integer", "minimum": 0},
            "review_capacity": {"type": "integer", "minimum": 0},
            "capacity_scope": {"type": "string", "minLength": 1},
            "claim_rules": {"type": "array", "items": ClaimRule.SCHEMA},
            "blocked_claim_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "uniqueItems": True,
            },
            "allowed_routes": {
                "type": "array",
                "items": {"enum": list(ROUTES)},
                "minItems": 1,
                "uniqueItems": True,
            },
            "failure_mode": {"const": "fail_closed"},
        },
    }

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_id", _required_text("policy_id", self.policy_id)
        )
        object.__setattr__(
            self, "issuer_id", _required_text("issuer_id", self.issuer_id)
        )
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            raise ValueError("revision must be a positive integer")
        effective = normalize_timestamp(self.effective_from)
        expires = normalize_timestamp(self.expires_at)
        if parse_timestamp(effective) >= parse_timestamp(expires):
            raise ValueError("effective_from must precede expires_at")
        object.__setattr__(self, "effective_from", effective)
        object.__setattr__(self, "expires_at", expires)

        models = tuple(
            binding
            if isinstance(binding, ModelBinding)
            else ModelBinding.from_dict(binding)
            for binding in self.approved_models
        )
        model_pairs = {(binding.model_id, binding.model_hash) for binding in models}
        if not models or len(model_pairs) != len(models):
            raise ValueError("approved_models must be non-empty and pairwise unique")
        if len({binding.model_id for binding in models}) != len(models):
            raise ValueError("each approved model ID must bind exactly one model hash")
        object.__setattr__(self, "approved_models", models)

        evidence_rules = tuple(
            rule if isinstance(rule, EvidenceRule) else EvidenceRule.from_dict(rule)
            for rule in self.evidence_rules
        )
        if not evidence_rules:
            raise ValueError("evidence_rules must not be empty")
        if len({rule.evidence_type for rule in evidence_rules}) != len(evidence_rules):
            raise ValueError("each evidence type must have exactly one admission rule")
        object.__setattr__(self, "evidence_rules", evidence_rules)

        for name in ("score_threshold", "uncertainty_threshold", "review_band_width"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
            object.__setattr__(self, name, value)
        for name in ("alert_capacity", "review_capacity"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        object.__setattr__(
            self,
            "capacity_scope",
            _required_text("capacity_scope", self.capacity_scope),
        )

        rules = tuple(
            rule if isinstance(rule, ClaimRule) else ClaimRule.from_dict(rule)
            for rule in self.claim_rules
        )
        claim_ids = [rule.claim_id for rule in rules]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim_rules must use unique claim IDs")
        blocked = _unique_tuple("blocked_claim_ids", self.blocked_claim_ids)
        if set(claim_ids) & set(blocked):
            raise ValueError(
                "a claim cannot be both conditionally permitted and blocked"
            )
        usable_evidence_types = {
            rule.evidence_type for rule in evidence_rules if rule.use_allowed
        }
        for rule in rules:
            if set(rule.routes) & set(ACTION_ROUTES):
                if not rule.required_evidence_types:
                    raise ValueError(
                        "action-route claim rules require at least one evidence type"
                    )
                if not set(rule.required_evidence_types).issubset(
                    usable_evidence_types
                ):
                    raise ValueError(
                        "action-route claim evidence types must have usable evidence rules"
                    )
        object.__setattr__(self, "claim_rules", rules)
        object.__setattr__(self, "blocked_claim_ids", blocked)

        allowed = _unique_tuple("allowed_routes", self.allowed_routes)
        if not allowed or any(route not in ROUTES for route in allowed):
            raise ValueError(f"allowed_routes must be a non-empty subset of {ROUTES}")
        for action_route in set(allowed) & set(ACTION_ROUTES):
            if not any(action_route in rule.routes for rule in rules):
                raise ValueError(
                    f"allowed action route {action_route!r} requires a claim rule"
                )
        object.__setattr__(self, "allowed_routes", allowed)
        if self.failure_mode != "fail_closed":
            raise ValueError("the ECRC core supports only fail_closed policy manifests")

    @property
    def policy_hash(self) -> str:
        return self.content_hash

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PolicyManifest:
        data = dict(value)
        data["approved_models"] = tuple(
            ModelBinding.from_dict(item) for item in data["approved_models"]
        )
        data["evidence_rules"] = tuple(
            EvidenceRule.from_dict(item) for item in data["evidence_rules"]
        )
        data["claim_rules"] = tuple(
            ClaimRule.from_dict(item) for item in data.get("claim_rules", ())
        )
        data["blocked_claim_ids"] = tuple(data.get("blocked_claim_ids", ()))
        data["allowed_routes"] = tuple(data.get("allowed_routes", ROUTES))
        return cls(**data)

    @classmethod
    def migrate_legacy_model_lists(
        cls,
        *,
        approved_model_ids: tuple[str, ...],
        approved_model_hashes: tuple[str, ...],
        **values: Any,
    ) -> PolicyManifest:
        """Explicitly migrate positional legacy ID/hash lists.

        The method rejects unequal lengths and duplicate IDs rather than
        preserving the former cross-product interpretation.
        """

        if len(approved_model_ids) != len(approved_model_hashes):
            raise ValueError("legacy model ID/hash lists must have equal lengths")
        bindings = tuple(
            ModelBinding(model_id=model_id, model_hash=model_hash)
            for model_id, model_hash in zip(
                approved_model_ids, approved_model_hashes, strict=True
            )
        )
        return cls(approved_models=bindings, **values)


@dataclass(frozen=True)
class ProposalEnvelope(SchemaArtifact):
    decision_id: str
    subject_id: str
    session_id: str
    model_id: str
    model_version: str
    model_hash: str
    score: float
    uncertainty: float
    proposed_action: str
    proposed_at: str
    input_hash: str
    validation_scope_id: str

    SCHEMA: ClassVar[dict[str, Any]] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ECRC ProposalEnvelope",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "decision_id",
            "subject_id",
            "session_id",
            "model_id",
            "model_version",
            "model_hash",
            "score",
            "uncertainty",
            "proposed_action",
            "proposed_at",
            "input_hash",
            "validation_scope_id",
        ],
        "properties": {
            "decision_id": {"type": "string", "minLength": 1},
            "subject_id": {"type": "string", "minLength": 1},
            "session_id": {"type": "string", "minLength": 1},
            "model_id": {"type": "string", "minLength": 1},
            "model_version": {"type": "string", "minLength": 1},
            "model_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "score": {"type": "number", "minimum": 0, "maximum": 1},
            "uncertainty": {"type": "number", "minimum": 0, "maximum": 1},
            "proposed_action": {"type": "string", "minLength": 1},
            "proposed_at": {"type": "string", "format": "date-time"},
            "input_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "validation_scope_id": {"type": "string", "minLength": 1},
        },
    }

    def __post_init__(self) -> None:
        for name in (
            "decision_id",
            "subject_id",
            "session_id",
            "model_id",
            "model_version",
            "proposed_action",
            "validation_scope_id",
        ):
            object.__setattr__(self, name, _required_text(name, getattr(self, name)))
        object.__setattr__(
            self, "model_hash", _hash_text("model_hash", self.model_hash)
        )
        object.__setattr__(
            self, "input_hash", _hash_text("input_hash", self.input_hash)
        )
        for name in ("score", "uncertainty"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "proposed_at", normalize_timestamp(self.proposed_at))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProposalEnvelope:
        return cls(**dict(value))


@dataclass(frozen=True)
class EvidenceItem(SchemaArtifact):
    evidence_id: str
    evidence_type: str
    source: str
    schema_version: str
    observed_at: str
    available_at: str
    provenance_hash: str
    requested_for_use: bool

    SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "evidence_id",
            "evidence_type",
            "source",
            "schema_version",
            "observed_at",
            "available_at",
            "provenance_hash",
            "requested_for_use",
        ],
        "properties": {
            "evidence_id": {"type": "string", "minLength": 1},
            "evidence_type": {"type": "string", "minLength": 1},
            "source": {"type": "string", "minLength": 1},
            "schema_version": {"type": "string", "minLength": 1},
            "observed_at": {"type": "string", "format": "date-time"},
            "available_at": {"type": "string", "format": "date-time"},
            "provenance_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "requested_for_use": {"type": "boolean"},
        },
    }

    def __post_init__(self) -> None:
        for name in ("evidence_id", "evidence_type", "source", "schema_version"):
            object.__setattr__(self, name, _required_text(name, getattr(self, name)))
        observed = normalize_timestamp(self.observed_at)
        available = normalize_timestamp(self.available_at)
        if parse_timestamp(observed) > parse_timestamp(available):
            raise ValueError("observed_at must not follow available_at")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(
            self, "provenance_hash", _hash_text("provenance_hash", self.provenance_hash)
        )
        if not isinstance(self.requested_for_use, bool):
            raise ValueError("requested_for_use must be boolean")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvidenceItem:
        return cls(**dict(value))


@dataclass(frozen=True)
class EvidenceEnvelope(SchemaArtifact):
    decision_id: str
    created_at: str
    items: tuple[EvidenceItem, ...]

    SCHEMA: ClassVar[dict[str, Any]] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ECRC EvidenceEnvelope",
        "type": "object",
        "additionalProperties": False,
        "required": ["decision_id", "created_at", "items"],
        "properties": {
            "decision_id": {"type": "string", "minLength": 1},
            "created_at": {"type": "string", "format": "date-time"},
            "items": {
                "type": "array",
                "items": EvidenceItem.SCHEMA,
                "minItems": 1,
            },
        },
    }

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decision_id", _required_text("decision_id", self.decision_id)
        )
        object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
        items = tuple(
            item if isinstance(item, EvidenceItem) else EvidenceItem.from_dict(item)
            for item in self.items
        )
        if not items:
            raise ValueError("evidence envelope must contain at least one item")
        if len({item.evidence_id for item in items}) != len(items):
            raise ValueError("evidence IDs must be unique within an envelope")
        object.__setattr__(
            self, "items", tuple(sorted(items, key=lambda item: item.evidence_id))
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvidenceEnvelope:
        return cls(
            decision_id=str(value["decision_id"]),
            created_at=str(value["created_at"]),
            items=tuple(EvidenceItem.from_dict(item) for item in value["items"]),
        )


@dataclass(frozen=True)
class DecisionPermit(SchemaArtifact):
    permit_id: str
    decision_id: str
    policy_id: str
    policy_revision: int
    policy_hash: str
    proposal_hash: str
    evidence_hash: str
    request_hash: str
    route: str
    reason_code: str
    issued_at: str
    expires_at: str
    pre_state_revision: int
    post_state_revision: int
    reservation_id: str | None
    reserved_resource: str | None
    admitted_evidence_ids: tuple[str, ...]
    used_evidence_ids: tuple[str, ...]
    excluded_evidence_ids: tuple[str, ...]
    permitted_claim_ids: tuple[str, ...]
    blocked_claim_ids: tuple[str, ...]

    SCHEMA: ClassVar[dict[str, Any]] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ECRC DecisionPermit",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "permit_id",
            "decision_id",
            "policy_id",
            "policy_revision",
            "policy_hash",
            "proposal_hash",
            "evidence_hash",
            "request_hash",
            "route",
            "reason_code",
            "issued_at",
            "expires_at",
            "pre_state_revision",
            "post_state_revision",
            "reservation_id",
            "reserved_resource",
            "admitted_evidence_ids",
            "used_evidence_ids",
            "excluded_evidence_ids",
            "permitted_claim_ids",
            "blocked_claim_ids",
        ],
        "properties": {
            "permit_id": {"type": "string", "minLength": 1},
            "decision_id": {"type": "string", "minLength": 1},
            "policy_id": {"type": "string", "minLength": 1},
            "policy_revision": {"type": "integer", "minimum": 1},
            "policy_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "proposal_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "evidence_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "request_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "route": {"enum": list(ROUTES)},
            "reason_code": {"type": "string", "minLength": 1},
            "issued_at": {"type": "string", "format": "date-time"},
            "expires_at": {"type": "string", "format": "date-time"},
            "pre_state_revision": {"type": "integer", "minimum": 0},
            "post_state_revision": {"type": "integer", "minimum": 0},
            "reservation_id": {"type": ["string", "null"]},
            "reserved_resource": {
                "type": ["string", "null"],
                "enum": [*RESOURCES, None],
            },
            "admitted_evidence_ids": {"type": "array", "items": {"type": "string"}},
            "used_evidence_ids": {"type": "array", "items": {"type": "string"}},
            "excluded_evidence_ids": {"type": "array", "items": {"type": "string"}},
            "permitted_claim_ids": {"type": "array", "items": {"type": "string"}},
            "blocked_claim_ids": {"type": "array", "items": {"type": "string"}},
        },
    }

    def __post_init__(self) -> None:
        for name in ("permit_id", "decision_id", "policy_id", "reason_code"):
            object.__setattr__(self, name, _required_text(name, getattr(self, name)))
        if not isinstance(self.policy_revision, int) or self.policy_revision < 1:
            raise ValueError("policy_revision must be a positive integer")
        for name in ("policy_hash", "proposal_hash", "evidence_hash", "request_hash"):
            object.__setattr__(self, name, _hash_text(name, getattr(self, name)))
        if self.route not in ROUTES:
            raise ValueError(f"route must be one of {ROUTES}")
        issued = normalize_timestamp(self.issued_at)
        expires = normalize_timestamp(self.expires_at)
        if parse_timestamp(issued) >= parse_timestamp(expires):
            raise ValueError("permit expires_at must follow issued_at")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)
        for name in ("pre_state_revision", "post_state_revision"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

        if self.route in ACTION_ROUTES:
            if not self.reservation_id or self.reserved_resource != self.route:
                raise ValueError(
                    "action routes require a matching capacity reservation"
                )
            if self.post_state_revision != self.pre_state_revision + 1:
                raise ValueError("a reservation must advance state revision by one")
        elif self.reservation_id is not None or self.reserved_resource is not None:
            raise ValueError("non-action routes must not carry a capacity reservation")
        if self.reservation_id is not None:
            object.__setattr__(
                self,
                "reservation_id",
                _required_text("reservation_id", self.reservation_id),
            )

        for name in (
            "admitted_evidence_ids",
            "used_evidence_ids",
            "excluded_evidence_ids",
            "permitted_claim_ids",
            "blocked_claim_ids",
        ):
            object.__setattr__(self, name, _unique_tuple(name, getattr(self, name)))
        if not set(self.used_evidence_ids).issubset(self.admitted_evidence_ids):
            raise ValueError("used evidence IDs must be a subset of admitted IDs")
        if set(self.admitted_evidence_ids) & set(self.excluded_evidence_ids):
            raise ValueError("evidence cannot be both admitted and excluded")
        if set(self.permitted_claim_ids) & set(self.blocked_claim_ids):
            raise ValueError("claims cannot be both permitted and blocked")
        if self.route in ACTION_ROUTES:
            if not self.used_evidence_ids:
                raise ValueError("action routes require used policy-admitted evidence")
            if not self.permitted_claim_ids:
                raise ValueError("action routes require at least one permitted claim")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DecisionPermit:
        data = dict(value)
        for name in (
            "admitted_evidence_ids",
            "used_evidence_ids",
            "excluded_evidence_ids",
            "permitted_claim_ids",
            "blocked_claim_ids",
        ):
            data[name] = tuple(data.get(name, ()))
        return cls(**data)


@dataclass(frozen=True)
class ExecutionReceipt(SchemaArtifact):
    receipt_id: str
    sequence_no: int
    permit_id: str
    permit_hash: str
    policy_id: str
    policy_revision: int
    route: str
    execution_status: str
    side_effect_id: str | None
    reservation_id: str | None
    executed_at: str
    enforcement_point_id: str
    previous_receipt_hash: str
    failure_reason: str | None = None

    SCHEMA: ClassVar[dict[str, Any]] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ECRC ExecutionReceipt",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "receipt_id",
            "sequence_no",
            "permit_id",
            "permit_hash",
            "policy_id",
            "policy_revision",
            "route",
            "execution_status",
            "side_effect_id",
            "reservation_id",
            "executed_at",
            "enforcement_point_id",
            "previous_receipt_hash",
            "failure_reason",
        ],
        "properties": {
            "receipt_id": {"type": "string", "minLength": 1},
            "sequence_no": {"type": "integer", "minimum": 1},
            "permit_id": {"type": "string", "minLength": 1},
            "permit_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "policy_id": {"type": "string", "minLength": 1},
            "policy_revision": {"type": "integer", "minimum": 1},
            "route": {"enum": list(ROUTES)},
            "execution_status": {"enum": list(RECEIPT_STATUSES)},
            "side_effect_id": {"type": ["string", "null"]},
            "reservation_id": {"type": ["string", "null"]},
            "executed_at": {"type": "string", "format": "date-time"},
            "enforcement_point_id": {"type": "string", "minLength": 1},
            "previous_receipt_hash": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "failure_reason": {"type": ["string", "null"]},
        },
    }

    def __post_init__(self) -> None:
        for name in ("receipt_id", "permit_id", "policy_id", "enforcement_point_id"):
            object.__setattr__(self, name, _required_text(name, getattr(self, name)))
        if not isinstance(self.sequence_no, int) or self.sequence_no < 1:
            raise ValueError("sequence_no must be a positive integer")
        if not isinstance(self.policy_revision, int) or self.policy_revision < 1:
            raise ValueError("policy_revision must be a positive integer")
        object.__setattr__(
            self, "permit_hash", _hash_text("permit_hash", self.permit_hash)
        )
        object.__setattr__(
            self,
            "previous_receipt_hash",
            _hash_text("previous_receipt_hash", self.previous_receipt_hash),
        )
        if self.route not in ROUTES:
            raise ValueError(f"route must be one of {ROUTES}")
        if self.execution_status not in RECEIPT_STATUSES:
            raise ValueError(f"execution_status must be one of {RECEIPT_STATUSES}")
        object.__setattr__(self, "executed_at", normalize_timestamp(self.executed_at))

        if self.execution_status == "executed":
            if self.route not in ACTION_ROUTES or not self.side_effect_id:
                raise ValueError(
                    "executed receipts require an action route and side effect"
                )
            if not self.reservation_id:
                raise ValueError("executed action receipts require a reservation")
        elif self.execution_status == "not_executed":
            if self.route in ACTION_ROUTES or self.side_effect_id is not None:
                raise ValueError("not_executed receipts are only for non-action routes")
        elif not self.failure_reason:
            raise ValueError("failed receipts require a failure_reason")

        if self.side_effect_id is not None:
            object.__setattr__(
                self,
                "side_effect_id",
                _required_text("side_effect_id", self.side_effect_id),
            )
        if self.reservation_id is not None:
            object.__setattr__(
                self,
                "reservation_id",
                _required_text("reservation_id", self.reservation_id),
            )
        if self.failure_reason is not None:
            object.__setattr__(
                self,
                "failure_reason",
                _required_text("failure_reason", self.failure_reason),
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ExecutionReceipt:
        return cls(**dict(value))
