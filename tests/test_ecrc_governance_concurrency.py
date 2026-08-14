from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from test_ecrc_governance_core import (
    EXECUTION_TIME,
    NOW,
    make_evidence,
    make_policy,
    make_proposal,
)

from agentic_eeg_dm.governance import (
    OrderedAdjudicator,
    PEPSimulator,
    SQLiteCapacityLedger,
)


def test_concurrent_reservations_never_oversubscribe_capacity(tmp_path) -> None:
    ledger = SQLiteCapacityLedger(tmp_path / "governance.sqlite")
    policy = make_policy(alert_capacity=3, review_capacity=0)
    ledger.register_policy(policy)
    adjudicator = OrderedAdjudicator(ledger)

    def issue(index: int):
        decision_id = f"concurrent-{index:02d}"
        return adjudicator.adjudicate(
            policy,
            make_proposal(decision_id),
            make_evidence(decision_id),
            at=NOW,
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        permits = list(pool.map(issue, range(24)))

    alerts = [permit for permit in permits if permit.route == "alert"]
    blocked = [permit for permit in permits if permit.route == "no_action"]
    assert len(alerts) == 3
    assert len(blocked) == 21
    assert {permit.reason_code for permit in blocked} == {"alert_capacity_exhausted"}

    reserved = ledger.capacity_snapshot(
        policy, scope_key="subject-1::session-1", resource="alert"
    )
    assert (reserved.reserved, reserved.committed, reserved.available) == (3, 0, 0)

    pep = PEPSimulator(ledger)
    with ThreadPoolExecutor(max_workers=3) as pool:
        receipts = list(
            pool.map(
                lambda permit: pep.execute(policy, permit, at=EXECUTION_TIME), alerts
            )
        )
    assert {receipt.execution_status for receipt in receipts} == {"executed"}
    committed = ledger.capacity_snapshot(
        policy, scope_key="subject-1::session-1", resource="alert"
    )
    assert (committed.reserved, committed.committed, committed.available) == (0, 3, 0)
