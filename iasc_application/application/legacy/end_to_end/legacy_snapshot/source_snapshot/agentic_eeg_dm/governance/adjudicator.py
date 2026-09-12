"""Ordered, fail-closed adjudication for ECRC decision permits."""

from __future__ import annotations

from datetime import timedelta

from .canonical import canonical_hash, normalize_timestamp, parse_timestamp, stable_id
from .exceptions import CapacityExceededError, InvalidPermitError
from .ledger import Reservation, SQLiteCapacityLedger
from .models import (
    ClaimRule,
    DecisionPermit,
    EvidenceEnvelope,
    PolicyManifest,
    ProposalEnvelope,
)


class OrderedAdjudicator:
    """Convert a frozen proposal and evidence envelope into one decision permit."""

    def __init__(
        self,
        ledger: SQLiteCapacityLedger,
        *,
        permit_ttl_seconds: int = 300,
    ) -> None:
        if permit_ttl_seconds <= 0:
            raise ValueError("permit_ttl_seconds must be positive")
        self.ledger = ledger
        self.permit_ttl_seconds = int(permit_ttl_seconds)

    def adjudicate(
        self,
        manifest: PolicyManifest,
        proposal: ProposalEnvelope,
        evidence: EvidenceEnvelope,
        *,
        at: str,
    ) -> DecisionPermit:
        now = normalize_timestamp(at)
        self.ledger.assert_policy_usable(manifest, at=now)
        self._validate_inputs(manifest, proposal, evidence, at=now)
        admitted_ids, used_ids, excluded_ids, used_types = self._gate_evidence(
            manifest, proposal, evidence
        )
        scope_key = self._scope_key(manifest, proposal)
        request_hash = canonical_hash(
            {
                "policy_hash": manifest.policy_hash,
                "proposal_hash": proposal.content_hash,
                "evidence_hash": evidence.content_hash,
                "scope_key": scope_key,
            }
        )
        idempotency_key = f"{manifest.policy_id}:{manifest.revision}:{scope_key}:{proposal.decision_id}"

        reservation: Reservation | None = None
        if not used_ids:
            route = "abstain"
            reason = "no_policy_admitted_evidence_for_use"
        elif proposal.uncertainty >= manifest.uncertainty_threshold:
            route = "abstain"
            reason = "uncertainty_gate"
        else:
            distance = abs(proposal.score - manifest.score_threshold)
            if distance <= manifest.review_band_width:
                try:
                    reservation = self.ledger.reserve(
                        manifest,
                        scope_key=scope_key,
                        resource="review",
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        at=now,
                    )
                    route = "review"
                    reason = "score_within_review_band"
                except CapacityExceededError:
                    route = "abstain"
                    reason = "review_capacity_exhausted"
            elif proposal.score > manifest.score_threshold + manifest.review_band_width:
                try:
                    reservation = self.ledger.reserve(
                        manifest,
                        scope_key=scope_key,
                        resource="alert",
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        at=now,
                    )
                    route = "alert"
                    reason = "score_above_review_band"
                except CapacityExceededError:
                    route = "no_action"
                    reason = "alert_capacity_exhausted"
            else:
                route = "no_action"
                reason = "score_below_threshold"

        if route not in manifest.allowed_routes:
            if reservation is not None:
                self.ledger.release(reservation.reservation_id, at=now)
            if "no_action" not in manifest.allowed_routes:
                raise InvalidPermitError(
                    "policy excludes both the computed route and fail-closed no_action"
                )
            reservation = None
            route = "no_action"
            reason = "route_not_authorized_by_policy"

        permitted_claims = self._permitted_claims(
            manifest.claim_rules,
            route=route,
            reason=reason,
            used_evidence_types=used_types,
        )
        if route in ("alert", "review") and not permitted_claims:
            if reservation is not None:
                self.ledger.release(reservation.reservation_id, at=now)
            reservation = None
            if "abstain" in manifest.allowed_routes:
                route = "abstain"
            elif "no_action" in manifest.allowed_routes:
                route = "no_action"
            else:
                raise InvalidPermitError(
                    "action lacks a policy-supported claim and no fail-closed route is allowed"
                )
            reason = "no_claim_supported_by_used_evidence"
            permitted_claims = self._permitted_claims(
                manifest.claim_rules,
                route=route,
                reason=reason,
                used_evidence_types=used_types,
            )
        all_conditional_claims = {rule.claim_id for rule in manifest.claim_rules}
        blocked_claims = tuple(
            sorted(
                set(manifest.blocked_claim_ids)
                | (all_conditional_claims - set(permitted_claims))
            )
        )

        issued_at = reservation.created_at if reservation is not None else now
        expiry = min(
            parse_timestamp(issued_at) + timedelta(seconds=self.permit_ttl_seconds),
            parse_timestamp(manifest.expires_at),
        )
        expires_at = normalize_timestamp(expiry.isoformat())
        identity = {
            "decision_id": proposal.decision_id,
            "policy_hash": manifest.policy_hash,
            "request_hash": request_hash,
            "route": route,
            "reason": reason,
            "reservation_id": None
            if reservation is None
            else reservation.reservation_id,
        }
        permit = DecisionPermit(
            permit_id=stable_id("permit", identity),
            decision_id=proposal.decision_id,
            policy_id=manifest.policy_id,
            policy_revision=manifest.revision,
            policy_hash=manifest.policy_hash,
            proposal_hash=proposal.content_hash,
            evidence_hash=evidence.content_hash,
            request_hash=request_hash,
            route=route,
            reason_code=reason,
            issued_at=issued_at,
            expires_at=expires_at,
            pre_state_revision=(
                0 if reservation is None else reservation.pre_state_revision
            ),
            post_state_revision=(
                0 if reservation is None else reservation.post_state_revision
            ),
            reservation_id=None if reservation is None else reservation.reservation_id,
            reserved_resource=None if reservation is None else reservation.resource,
            admitted_evidence_ids=admitted_ids,
            used_evidence_ids=used_ids,
            excluded_evidence_ids=excluded_ids,
            permitted_claim_ids=permitted_claims,
            blocked_claim_ids=blocked_claims,
        )
        try:
            self.ledger.register_issued_permit(permit, at=now)
        except Exception:
            if reservation is not None and reservation.permit_id is None:
                self.ledger.release(reservation.reservation_id, at=now)
            raise
        return permit

    @staticmethod
    def _validate_inputs(
        manifest: PolicyManifest,
        proposal: ProposalEnvelope,
        evidence: EvidenceEnvelope,
        *,
        at: str,
    ) -> None:
        if proposal.decision_id != evidence.decision_id:
            raise InvalidPermitError("proposal and evidence decision IDs do not match")
        approved_model_pairs = {
            (binding.model_id, binding.model_hash)
            for binding in manifest.approved_models
        }
        if (proposal.model_id, proposal.model_hash) not in approved_model_pairs:
            raise InvalidPermitError(
                "proposal model ID/hash pair is not approved by policy"
            )
        if parse_timestamp(proposal.proposed_at) > parse_timestamp(at):
            raise InvalidPermitError("proposal timestamp is in the future")
        if parse_timestamp(evidence.created_at) > parse_timestamp(at):
            raise InvalidPermitError("evidence envelope timestamp is in the future")

    @staticmethod
    def _gate_evidence(
        manifest: PolicyManifest,
        proposal: ProposalEnvelope,
        evidence: EvidenceEnvelope,
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], set[str]]:
        """Recompute admission and use solely from the active policy.

        ``requested_for_use`` is only a request. It cannot make an item
        admitted or usable when source, schema, timing, or freshness fail.
        """

        rules = {rule.evidence_type: rule for rule in manifest.evidence_rules}
        decision_time = parse_timestamp(proposal.proposed_at)
        admitted_ids: list[str] = []
        used_ids: list[str] = []
        excluded_ids: list[str] = []
        used_types: set[str] = set()
        for item in evidence.items:
            rule = rules.get(item.evidence_type)
            admitted = rule is not None
            if rule is not None:
                observed_at = parse_timestamp(item.observed_at)
                available_at = parse_timestamp(item.available_at)
                age_seconds = (decision_time - observed_at).total_seconds()
                admitted = (
                    item.source in rule.allowed_sources
                    and item.schema_version in rule.allowed_schema_versions
                    and observed_at <= decision_time
                    and available_at <= decision_time
                    and 0.0 <= age_seconds <= rule.max_age_seconds
                )
            if admitted:
                admitted_ids.append(item.evidence_id)
                if item.requested_for_use and rule is not None and rule.use_allowed:
                    used_ids.append(item.evidence_id)
                    used_types.add(item.evidence_type)
            else:
                excluded_ids.append(item.evidence_id)
        return (
            tuple(sorted(admitted_ids)),
            tuple(sorted(used_ids)),
            tuple(sorted(excluded_ids)),
            used_types,
        )

    @staticmethod
    def _scope_key(manifest: PolicyManifest, proposal: ProposalEnvelope) -> str:
        if manifest.capacity_scope == "subject":
            return proposal.subject_id
        if manifest.capacity_scope == "session":
            return proposal.session_id
        if manifest.capacity_scope in {"subject_session", "participant_segment"}:
            return f"{proposal.subject_id}::{proposal.session_id}"
        raise InvalidPermitError(
            "unsupported capacity_scope; use subject, session, or subject_session"
        )

    @staticmethod
    def _permitted_claims(
        rules: tuple[ClaimRule, ...],
        *,
        route: str,
        reason: str,
        used_evidence_types: set[str],
    ) -> tuple[str, ...]:
        permitted = []
        for rule in rules:
            reason_matches = not rule.reason_codes or reason in rule.reason_codes
            evidence_matches = set(rule.required_evidence_types).issubset(
                used_evidence_types
            )
            if route in rule.routes and reason_matches and evidence_matches:
                permitted.append(rule.claim_id)
        return tuple(sorted(permitted))
