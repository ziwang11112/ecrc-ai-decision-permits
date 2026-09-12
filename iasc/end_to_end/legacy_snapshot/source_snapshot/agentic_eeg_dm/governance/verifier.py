"""Stateful verification of ECRC execution-receipt chains."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .canonical import parse_timestamp
from .exceptions import ReceiptVerificationError
from .models import (
    ACTION_ROUTES,
    GENESIS_RECEIPT_HASH,
    DecisionPermit,
    ExecutionReceipt,
)


class StatefulReceiptVerifier:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.expected_sequence_no = 1
        self.expected_previous_hash = GENESIS_RECEIPT_HASH
        self.seen_permit_ids: set[str] = set()
        self.seen_receipt_ids: set[str] = set()

    def verify(self, receipt: ExecutionReceipt, permit: DecisionPermit) -> None:
        if receipt.sequence_no != self.expected_sequence_no:
            raise ReceiptVerificationError(
                f"expected receipt sequence {self.expected_sequence_no}, "
                f"got {receipt.sequence_no}"
            )
        if receipt.previous_receipt_hash != self.expected_previous_hash:
            raise ReceiptVerificationError("receipt hash-chain predecessor mismatch")
        if receipt.receipt_id in self.seen_receipt_ids:
            raise ReceiptVerificationError("duplicate receipt ID")
        if receipt.permit_id in self.seen_permit_ids:
            raise ReceiptVerificationError("permit replay detected in receipt chain")
        if receipt.permit_id != permit.permit_id:
            raise ReceiptVerificationError("receipt references the wrong permit")
        if receipt.permit_hash != permit.content_hash:
            raise ReceiptVerificationError(
                "receipt permit hash does not match permit content"
            )
        if (
            receipt.policy_id != permit.policy_id
            or receipt.policy_revision != permit.policy_revision
            or receipt.route != permit.route
        ):
            raise ReceiptVerificationError("receipt policy/route does not match permit")
        if parse_timestamp(receipt.executed_at) < parse_timestamp(permit.issued_at):
            raise ReceiptVerificationError("receipt predates permit issuance")
        if parse_timestamp(receipt.executed_at) >= parse_timestamp(permit.expires_at):
            raise ReceiptVerificationError("receipt was emitted after permit expiry")
        if receipt.execution_status == "executed":
            if permit.route not in ACTION_ROUTES:
                raise ReceiptVerificationError(
                    "non-action permit has an executed receipt"
                )
            if receipt.reservation_id != permit.reservation_id:
                raise ReceiptVerificationError(
                    "receipt reservation does not match permit"
                )
        elif (
            receipt.execution_status == "not_executed" and permit.route in ACTION_ROUTES
        ):
            raise ReceiptVerificationError(
                "action permit cannot be marked not_executed"
            )

        self.seen_receipt_ids.add(receipt.receipt_id)
        self.seen_permit_ids.add(receipt.permit_id)
        self.expected_previous_hash = receipt.content_hash
        self.expected_sequence_no += 1

    def verify_chain(
        self,
        receipts: Iterable[ExecutionReceipt],
        permits_by_id: Mapping[str, DecisionPermit],
        *,
        expected_tail_hash: str | None = None,
    ) -> None:
        for receipt in receipts:
            try:
                permit = permits_by_id[receipt.permit_id]
            except KeyError as exc:
                raise ReceiptVerificationError(
                    f"missing permit {receipt.permit_id!r} for receipt"
                ) from exc
            self.verify(receipt, permit)
        if (
            expected_tail_hash is not None
            and self.expected_previous_hash != expected_tail_hash
        ):
            raise ReceiptVerificationError(
                "receipt-chain tail does not match trusted anchor"
            )
