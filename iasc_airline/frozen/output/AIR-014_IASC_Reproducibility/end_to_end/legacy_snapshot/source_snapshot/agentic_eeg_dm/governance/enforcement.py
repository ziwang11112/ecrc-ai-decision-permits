"""Policy-enforcement-point simulation for ECRC permits."""

from __future__ import annotations

from .canonical import normalize_timestamp, parse_timestamp
from .exceptions import InvalidPermitError
from .ledger import SQLiteCapacityLedger
from .models import DecisionPermit, ExecutionReceipt, PolicyManifest


class PEPSimulator:
    """Validate and consume permits without performing an external side effect.

    The simulated side effect and receipt append are committed in the same
    SQLite transaction. This intentionally does not claim atomicity with a real
    alert service, ticketing API, or other external system.
    """

    def __init__(
        self,
        ledger: SQLiteCapacityLedger,
        *,
        enforcement_point_id: str = "ecrc_pep_simulator",
    ) -> None:
        if not enforcement_point_id.strip():
            raise ValueError("enforcement_point_id must not be empty")
        self.ledger = ledger
        self.enforcement_point_id = enforcement_point_id.strip()

    def validate(
        self,
        manifest: PolicyManifest,
        permit: DecisionPermit,
        *,
        at: str,
    ) -> None:
        now = normalize_timestamp(at)
        self.ledger.assert_policy_usable(manifest, at=now)
        if (
            permit.policy_id != manifest.policy_id
            or permit.policy_revision != manifest.revision
            or permit.policy_hash != manifest.policy_hash
        ):
            raise InvalidPermitError("permit is not bound to the active policy")
        self.ledger.assert_issued_permit(permit)
        if permit.route not in manifest.allowed_routes:
            raise InvalidPermitError("permit route is not allowed by policy")
        instant = parse_timestamp(now)
        if instant < parse_timestamp(permit.issued_at):
            raise InvalidPermitError("permit is not yet valid")
        if instant >= parse_timestamp(permit.expires_at):
            raise InvalidPermitError("permit has expired")
        if permit.route in {"alert", "review"}:
            if (
                permit.reservation_id is None
                or permit.reserved_resource != permit.route
            ):
                raise InvalidPermitError("action permit lacks a matching reservation")
            reservation = self.ledger.get_reservation(permit.reservation_id)
            if reservation.status == "committed" and (
                reservation.permit_id == permit.permit_id
                and reservation.permit_hash == permit.content_hash
            ):
                # Let the transactional execution registry produce the precise
                # PermitReplayError instead of misclassifying a retry as an
                # invalid reservation.
                return
            if reservation.status != "reserved":
                raise InvalidPermitError(
                    f"reservation is not executable from status {reservation.status!r}"
                )
            if (
                reservation.request_hash != permit.request_hash
                or reservation.policy_hash != permit.policy_hash
            ):
                raise InvalidPermitError("permit does not match the stored reservation")

    def execute(
        self,
        manifest: PolicyManifest,
        permit: DecisionPermit,
        *,
        at: str,
        simulate_pre_execution_failure: bool = False,
    ) -> ExecutionReceipt:
        self.validate(manifest, permit, at=at)
        failure_reason = (
            "simulated_pre_execution_failure"
            if simulate_pre_execution_failure
            else None
        )
        return self.ledger.complete_execution(
            manifest,
            permit,
            at=at,
            enforcement_point_id=self.enforcement_point_id,
            failure_reason=failure_reason,
        )
