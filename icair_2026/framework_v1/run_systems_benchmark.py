#!/usr/bin/env python3
"""Reproducible systems benchmark for the isolated ECRC governance core."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from typing import Any

import numpy as np

from agentic_eeg_dm.governance import (
    ClaimRule,
    EvidenceEnvelope,
    EvidenceItem,
    EvidenceRule,
    InvalidPermitError,
    ModelBinding,
    OrderedAdjudicator,
    PEPSimulator,
    PermitReplayError,
    PolicyExpiredError,
    PolicyManifest,
    ProposalEnvelope,
    RevokedPolicyError,
    SQLiteCapacityLedger,
    StalePolicyError,
    StatefulReceiptVerifier,
    canonical_hash,
)

SCRIPT_VERSION = "1.1.0"
DEFAULT_SEED = 20260813
WORKER_SWEEP = (1, 2, 4, 8, 16)
ISSUE_TIME = "2026-01-01T00:00:10Z"
EXECUTE_TIME = "2026-01-01T00:00:11Z"
MODEL_HASH = "a" * 64
ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "evidence_systems"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--single-requests", type=int, default=96)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--warmup-requests", type=int, default=8)
    parser.add_argument("--run-id", default="primary")
    return parser.parse_args()


def make_policy(
    policy_id: str,
    *,
    revision: int = 1,
    alert_capacity: int,
    review_capacity: int = 0,
    effective_from: str = "2026-01-01T00:00:00Z",
    expires_at: str = "2026-01-02T00:00:00Z",
) -> PolicyManifest:
    return PolicyManifest(
        policy_id=policy_id,
        revision=revision,
        issuer_id="benchmark-technical-registry",
        effective_from=effective_from,
        expires_at=expires_at,
        approved_models=(ModelBinding("benchmark-model", MODEL_HASH),),
        evidence_rules=(
            EvidenceRule(
                evidence_type="behavior_score",
                allowed_sources=("benchmark-generator",),
                allowed_schema_versions=("1.0",),
                max_age_seconds=60,
                use_allowed=True,
            ),
        ),
        claim_rules=(
            ClaimRule(
                claim_id="task_alert",
                routes=("alert",),
                required_evidence_types=("behavior_score",),
            ),
            ClaimRule(
                claim_id="task_review",
                routes=("review",),
                required_evidence_types=("behavior_score",),
            ),
        ),
        score_threshold=0.60,
        uncertainty_threshold=0.80,
        review_band_width=0.05,
        alert_capacity=alert_capacity,
        review_capacity=review_capacity,
        capacity_scope="subject_session",
        blocked_claim_ids=("clinical_diagnosis", "intervention_efficacy"),
    )


def make_request(
    decision_id: str, *, score: float
) -> tuple[ProposalEnvelope, EvidenceEnvelope]:
    proposal = ProposalEnvelope(
        decision_id=decision_id,
        subject_id="benchmark-subject",
        session_id="benchmark-session",
        model_id="benchmark-model",
        model_version="1.0",
        model_hash=MODEL_HASH,
        score=score,
        uncertainty=0.10,
        proposed_action="alert",
        proposed_at="2026-01-01T00:00:05Z",
        input_hash=canonical_hash({"decision_id": decision_id}),
        validation_scope_id="systems-benchmark",
    )
    evidence = EvidenceEnvelope(
        decision_id=decision_id,
        created_at="2026-01-01T00:00:06Z",
        items=(
            EvidenceItem(
                evidence_id=f"evidence::{decision_id}",
                evidence_type="behavior_score",
                source="benchmark-generator",
                schema_version="1.0",
                observed_at="2026-01-01T00:00:03Z",
                available_at="2026-01-01T00:00:04Z",
                provenance_hash=canonical_hash({"evidence": decision_id}),
                requested_for_use=True,
            ),
        ),
    )
    return proposal, evidence


def latency_summary(latencies_ns: list[int]) -> dict[str, float]:
    values_ms = np.asarray(latencies_ns, dtype=float) / 1_000_000.0
    return {
        "p50_ms": float(np.percentile(values_ms, 50)),
        "p95_ms": float(np.percentile(values_ms, 95)),
        "p99_ms": float(np.percentile(values_ms, 99)),
        "mean_ms": float(np.mean(values_ms)),
        "maximum_ms": float(np.max(values_ms)),
    }


def run_pipeline(
    ledger: SQLiteCapacityLedger,
    policy: PolicyManifest,
    requests: list[tuple[ProposalEnvelope, EvidenceEnvelope]],
    *,
    workers: int,
) -> dict[str, Any]:
    adjudicator = OrderedAdjudicator(ledger)
    pep = PEPSimulator(ledger, enforcement_point_id="benchmark-pep")

    def one(request: tuple[ProposalEnvelope, EvidenceEnvelope]) -> dict[str, Any]:
        proposal, evidence = request
        start = time.perf_counter_ns()
        permit = adjudicator.adjudicate(policy, proposal, evidence, at=ISSUE_TIME)
        adjudicated = time.perf_counter_ns()
        receipt = pep.execute(policy, permit, at=EXECUTE_TIME)
        finished = time.perf_counter_ns()
        return {
            "permit": permit,
            "receipt": receipt,
            "adjudication_ns": adjudicated - start,
            "end_to_end_ns": finished - start,
        }

    wall_start = time.perf_counter_ns()
    if workers == 1:
        rows = [one(request) for request in requests]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(one, requests))
    wall_seconds = (time.perf_counter_ns() - wall_start) / 1_000_000_000.0
    routes: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for row in rows:
        route = row["permit"].route
        status = row["receipt"].execution_status
        routes[route] = routes.get(route, 0) + 1
        statuses[status] = statuses.get(status, 0) + 1
    StatefulReceiptVerifier().verify_chain(
        ledger.list_receipts(),
        {row["permit"].permit_id: row["permit"] for row in rows},
        expected_tail_hash=ledger.tail_receipt_hash(),
    )
    counts = ledger.counts()
    return {
        "n_requests": len(requests),
        "workers": workers,
        "wall_seconds": wall_seconds,
        "throughput_requests_per_second": len(requests) / wall_seconds,
        "adjudication_latency": latency_summary(
            [int(row["adjudication_ns"]) for row in rows]
        ),
        "end_to_end_latency": latency_summary(
            [int(row["end_to_end_ns"]) for row in rows]
        ),
        "route_counts": dict(sorted(routes.items())),
        "execution_status_counts": dict(sorted(statuses.items())),
        "issued_permits": counts.issued_permits,
        "reservation_counts": {
            "reserved": counts.reservations_reserved,
            "committed": counts.reservations_committed,
            "released": counts.reservations_released,
        },
        "receipt_count": counts.receipts,
        "invariant_violations": 0,
    }


def run_performance_cases(
    output_dir: Path,
    *,
    seed: int,
    repetitions: int,
    single_requests: int,
    workers: int,
    warmup_requests: int,
) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    cases = [("single_thread", 1, single_requests, single_requests)]
    cases.extend(
        (f"worker_sweep_96_cap8_w{worker_count}", worker_count, 96, 8)
        for worker_count in WORKER_SWEEP
    )
    cases.extend(
        (
            ("concurrent_24_cap3", workers, 24, 3),
            ("concurrent_96_cap8", workers, 96, 8),
        )
    )
    results: list[dict[str, Any]] = []
    for case_name, case_workers, n_requests, capacity in cases:
        score_values = rng.uniform(0.80, 0.99, size=n_requests).tolist()
        request_specs = [
            (f"{case_name}-{index:04d}", float(score))
            for index, score in enumerate(score_values)
        ]
        for repetition in range(repetitions):
            database = output_dir / "databases" / f"{case_name}_r{repetition}.sqlite"
            if database.exists():
                database.unlink()
            ledger = SQLiteCapacityLedger(database)
            policy = make_policy(
                f"{case_name}-policy-r{repetition}", alert_capacity=capacity
            )
            ledger.register_policy(policy)
            if warmup_requests:
                warmup_db = (
                    output_dir
                    / "databases"
                    / f"warmup_{case_name}_r{repetition}.sqlite"
                )
                if warmup_db.exists():
                    warmup_db.unlink()
                warmup_ledger = SQLiteCapacityLedger(warmup_db)
                warmup_policy = make_policy(
                    f"warmup-{case_name}-r{repetition}",
                    alert_capacity=warmup_requests,
                )
                warmup_ledger.register_policy(warmup_policy)
                run_pipeline(
                    warmup_ledger,
                    warmup_policy,
                    [
                        make_request(f"warmup-{index}", score=0.90)
                        for index in range(warmup_requests)
                    ],
                    workers=min(case_workers, warmup_requests),
                )
            requests = [
                make_request(decision_id, score=score)
                for decision_id, score in request_specs
            ]
            result = run_pipeline(ledger, policy, requests, workers=case_workers)
            result.update(
                {
                    "case": case_name,
                    "repetition": repetition,
                    "capacity": capacity,
                    "oversubscription_count": max(
                        0,
                        result["reservation_counts"]["committed"] - capacity,
                    ),
                    "capacity_rejections": result["route_counts"].get("no_action", 0),
                }
            )
            results.append(result)
    return results


def _median_range(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    return {
        "median": float(np.median(array)),
        "minimum": float(np.min(array)),
        "maximum": float(np.max(array)),
    }


def aggregate_performance(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize timing across repetitions without selecting a favorable run."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        grouped.setdefault(str(row["case"]), []).append(row)
    aggregate: list[dict[str, Any]] = []
    for case, rows in grouped.items():
        latency_metrics = ("p50_ms", "p95_ms", "p99_ms")
        aggregate.append(
            {
                "case": case,
                "repetitions": len(rows),
                "n_requests": rows[0]["n_requests"],
                "workers": rows[0]["workers"],
                "capacity": rows[0]["capacity"],
                "throughput_requests_per_second": _median_range(
                    [float(row["throughput_requests_per_second"]) for row in rows]
                ),
                "adjudication_latency": {
                    metric: _median_range(
                        [float(row["adjudication_latency"][metric]) for row in rows]
                    )
                    for metric in latency_metrics
                },
                "end_to_end_latency": {
                    metric: _median_range(
                        [float(row["end_to_end_latency"][metric]) for row in rows]
                    )
                    for metric in latency_metrics
                },
            }
        )
    return aggregate


def run_unsafe_race_witness() -> dict[str, Any]:
    """Deterministic witness for an intentionally unsafe read-check-write gate.

    Barriers force two workers to inspect the same stale capacity value before
    either writes. This fixture is explanatory only, not a production baseline.
    """

    capacity = 1
    state = {"committed": 0}
    after_read = Barrier(2)
    before_write = Barrier(2)

    def unsafe_attempt(worker_id: int) -> dict[str, Any]:
        observed = state["committed"]
        after_read.wait()
        accepted = observed < capacity
        if accepted:
            before_write.wait()
            state["committed"] = observed + 1
        return {
            "worker_id": worker_id,
            "observed_committed": observed,
            "accepted": accepted,
        }

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(unsafe_attempt, (0, 1)))
    logical_acceptances = sum(int(row["accepted"]) for row in attempts)
    oversubscription = max(0, logical_acceptances - capacity)
    lost_updates = logical_acceptances - state["committed"]
    return {
        "fixture_type": "unsafe_non_atomic_race_witness",
        "production_comparator": False,
        "barrier_forced_interleaving": True,
        "capacity": capacity,
        "attempts": attempts,
        "logical_acceptances": logical_acceptances,
        "stored_counter": state["committed"],
        "oversubscription_count": oversubscription,
        "lost_update_count": lost_updates,
        "passed": logical_acceptances == 2
        and oversubscription == 1
        and lost_updates == 1,
    }


def expect_error(
    label: str, expected: type[Exception], operation: Callable[[], Any]
) -> dict[str, Any]:
    try:
        operation()
    except expected as exc:
        return {
            "scenario": label,
            "expected_result": expected.__name__,
            "observed_result": type(exc).__name__,
            "passed": True,
        }
    except Exception as exc:  # pragma: no cover - diagnostic branch
        return {
            "scenario": label,
            "expected_result": expected.__name__,
            "observed_result": type(exc).__name__,
            "passed": False,
        }
    return {
        "scenario": label,
        "expected_result": expected.__name__,
        "observed_result": "no_error",
        "passed": False,
    }


def run_fault_scenarios(output_dir: Path) -> list[dict[str, Any]]:
    database_dir = output_dir / "databases"
    rows: list[dict[str, Any]] = []

    duplicate_db = database_dir / "fault_duplicate.sqlite"
    duplicate_db.unlink(missing_ok=True)
    ledger = SQLiteCapacityLedger(duplicate_db)
    policy = make_policy("fault-duplicate", alert_capacity=1)
    ledger.register_policy(policy)
    proposal, evidence = make_request("duplicate", score=0.90)
    adjudicator = OrderedAdjudicator(ledger)
    first = adjudicator.adjudicate(policy, proposal, evidence, at=ISSUE_TIME)
    second = adjudicator.adjudicate(policy, proposal, evidence, at=ISSUE_TIME)
    rows.append(
        {
            "scenario": "duplicate_adjudication",
            "expected_result": "same_permit",
            "observed_result": "same_permit" if first == second else "different_permit",
            "passed": first == second,
        }
    )
    pep = PEPSimulator(ledger)
    pep.execute(policy, first, at=EXECUTE_TIME)
    rows.append(
        expect_error(
            "permit_replay",
            PermitReplayError,
            lambda: pep.execute(policy, second, at=EXECUTE_TIME),
        )
    )

    expired_db = database_dir / "fault_expired.sqlite"
    expired_db.unlink(missing_ok=True)
    expired_ledger = SQLiteCapacityLedger(expired_db)
    expired_policy = make_policy(
        "fault-expired",
        alert_capacity=1,
        effective_from="2025-12-31T00:00:00Z",
        expires_at="2026-01-01T00:00:09Z",
    )
    expired_ledger.register_policy(expired_policy)
    expired_request = make_request("expired", score=0.90)
    rows.append(
        expect_error(
            "expired_policy",
            PolicyExpiredError,
            lambda: OrderedAdjudicator(expired_ledger).adjudicate(
                expired_policy, *expired_request, at=ISSUE_TIME
            ),
        )
    )

    revoked_db = database_dir / "fault_revoked.sqlite"
    revoked_db.unlink(missing_ok=True)
    revoked_ledger = SQLiteCapacityLedger(revoked_db)
    revoked_policy = make_policy("fault-revoked", alert_capacity=1)
    revoked_ledger.register_policy(revoked_policy)
    revoked_ledger.revoke_policy(revoked_policy.policy_id, expected_revision=1)
    revoked_request = make_request("revoked", score=0.90)
    rows.append(
        expect_error(
            "revoked_policy",
            RevokedPolicyError,
            lambda: OrderedAdjudicator(revoked_ledger).adjudicate(
                revoked_policy, *revoked_request, at=ISSUE_TIME
            ),
        )
    )

    stale_db = database_dir / "fault_stale.sqlite"
    stale_db.unlink(missing_ok=True)
    stale_ledger = SQLiteCapacityLedger(stale_db)
    old_policy = make_policy("fault-stale", alert_capacity=1)
    stale_ledger.register_policy(old_policy)
    stale_ledger.register_policy(replace(old_policy, revision=2, alert_capacity=2))
    stale_request = make_request("stale", score=0.90)
    rows.append(
        expect_error(
            "stale_policy",
            StalePolicyError,
            lambda: OrderedAdjudicator(stale_ledger).adjudicate(
                old_policy, *stale_request, at=ISSUE_TIME
            ),
        )
    )

    failure_db = database_dir / "fault_side_effect.sqlite"
    failure_db.unlink(missing_ok=True)
    failure_ledger = SQLiteCapacityLedger(failure_db)
    failure_policy = make_policy("fault-side-effect", alert_capacity=1)
    failure_ledger.register_policy(failure_policy)
    failure_request = make_request("side-effect-failure", score=0.90)
    failure_permit = OrderedAdjudicator(failure_ledger).adjudicate(
        failure_policy, *failure_request, at=ISSUE_TIME
    )
    receipt = PEPSimulator(failure_ledger).execute(
        failure_policy,
        failure_permit,
        at=EXECUTE_TIME,
        simulate_pre_execution_failure=True,
    )
    counts = failure_ledger.counts()
    passed = (
        receipt.execution_status == "failed"
        and counts.reservations_released == 1
        and counts.reservations_committed == 0
    )
    rows.append(
        {
            "scenario": "simulated_pre_execution_failure",
            "expected_result": "failed_receipt_and_release",
            "observed_result": (
                f"{receipt.execution_status};released={counts.reservations_released};"
                f"committed={counts.reservations_committed}"
            ),
            "passed": passed,
        }
    )

    forged_db = database_dir / "fault_forged.sqlite"
    forged_db.unlink(missing_ok=True)
    forged_ledger = SQLiteCapacityLedger(forged_db)
    forged_policy = make_policy("fault-forged", alert_capacity=1)
    forged_ledger.register_policy(forged_policy)
    forged_request = make_request("forged", score=0.90)
    issued = OrderedAdjudicator(forged_ledger).adjudicate(
        forged_policy, *forged_request, at=ISSUE_TIME
    )
    forged = replace(issued, permitted_claim_ids=("forged_claim",))
    rows.append(
        expect_error(
            "forged_permit_content",
            InvalidPermitError,
            lambda: PEPSimulator(forged_ledger).execute(
                forged_policy, forged, at=EXECUTE_TIME
            ),
        )
    )

    crash_db = database_dir / "fault_crash_gap.sqlite"
    crash_db.unlink(missing_ok=True)
    crash_ledger = SQLiteCapacityLedger(crash_db, reservation_lease_seconds=1)
    crash_policy = make_policy("fault-crash-gap", alert_capacity=1)
    crash_ledger.register_policy(crash_policy)
    crash_reservation = crash_ledger.reserve(
        crash_policy,
        scope_key="benchmark-subject::benchmark-session",
        resource="alert",
        idempotency_key="crashed-after-reserve",
        request_hash=canonical_hash("crashed-after-reserve"),
        at=ISSUE_TIME,
    )
    reaped = crash_ledger.reap_expired_reservations(at=EXECUTE_TIME)
    recovered_request = make_request("after-crash-gap", score=0.90)
    recovered_permit = OrderedAdjudicator(crash_ledger).adjudicate(
        crash_policy,
        *recovered_request,
        at="2026-01-01T00:00:12Z",
    )
    crash_counts = crash_ledger.counts()
    crash_passed = (
        tuple(row.reservation_id for row in reaped)
        == (crash_reservation.reservation_id,)
        and crash_counts.reservations_released == 1
        and recovered_permit.route == "alert"
    )
    rows.append(
        {
            "scenario": "crash_after_reserve_lease_recovery",
            "expected_result": "expired_unissued_reservation_reaped",
            "observed_result": (
                f"reaped={len(reaped)};released={crash_counts.reservations_released};"
                f"next_route={recovered_permit.route}"
            ),
            "passed": crash_passed,
        }
    )
    return rows


def structural_projection(
    performance: list[dict[str, Any]],
    faults: list[dict[str, Any]],
    unsafe_race_witness: dict[str, Any],
) -> dict[str, Any]:
    performance_projection = []
    for row in performance:
        performance_projection.append(
            {
                "case": row["case"],
                "repetition": row["repetition"],
                "n_requests": row["n_requests"],
                "workers": row["workers"],
                "capacity": row["capacity"],
                "route_counts": row["route_counts"],
                "execution_status_counts": row["execution_status_counts"],
                "reservation_counts": row["reservation_counts"],
                "receipt_count": row["receipt_count"],
                "oversubscription_count": row["oversubscription_count"],
                "capacity_rejections": row["capacity_rejections"],
                "invariant_violations": row["invariant_violations"],
            }
        )
    return {
        "performance": performance_projection,
        "faults": faults,
        "unsafe_race_witness": unsafe_race_witness,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    flat_rows = []
    for row in rows:
        flat: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    if isinstance(nested_value, dict):
                        for leaf_key, leaf_value in nested_value.items():
                            flat[f"{key}.{nested_key}.{leaf_key}"] = leaf_value
                    else:
                        flat[f"{key}.{nested_key}"] = nested_value
            else:
                flat[key] = value
        flat_rows.append(flat)
    fieldnames = sorted({key for row in flat_rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_rows)


def main() -> int:
    args = parse_args()
    if args.repetitions < 1 or args.single_requests < 1 or args.workers < 1:
        raise ValueError("repetitions, single-requests, and workers must be positive")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ecrc_systems_") as scratch:
        scratch_dir = Path(scratch)
        (scratch_dir / "databases").mkdir()
        performance = run_performance_cases(
            scratch_dir,
            seed=args.seed,
            repetitions=args.repetitions,
            single_requests=args.single_requests,
            workers=args.workers,
            warmup_requests=args.warmup_requests,
        )
        faults = run_fault_scenarios(scratch_dir)
    performance_aggregate = aggregate_performance(performance)
    unsafe_race_witness = run_unsafe_race_witness()
    projection = structural_projection(performance, faults, unsafe_race_witness)
    summary = {
        "script_version": SCRIPT_VERSION,
        "run_id": args.run_id,
        "seed": args.seed,
        "configuration": {
            "repetitions": args.repetitions,
            "single_requests": args.single_requests,
            "workers": args.workers,
            "worker_sweep": list(WORKER_SWEEP),
            "warmup_requests": args.warmup_requests,
        },
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "sqlite": __import__("sqlite3").sqlite_version,
        },
        "performance": performance,
        "performance_aggregate": performance_aggregate,
        "fault_scenarios": faults,
        "unsafe_race_witness": unsafe_race_witness,
        "structural_digest": canonical_hash(projection),
        "all_fault_scenarios_passed": all(row["passed"] for row in faults),
        "all_system_invariants_passed": all(
            row["invariant_violations"] == 0 and row["oversubscription_count"] == 0
            for row in performance
        ),
        "unsafe_race_witness_passed": unsafe_race_witness["passed"],
        "measurement_boundary": (
            "Single-host, file-backed SQLite WAL with simulated side effects. "
            "Worker-sweep tail latency includes single-file SQLite lock contention. "
            "Latency is wall-clock dependent and is not expected to be byte-identical "
            "across runs; seeded inputs, scenario structure, counts, rejection classes, "
            "and invariants are expected to be deterministic."
        ),
    }
    (output_dir / "systems_benchmark_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_dir / "systems_benchmark_structure.json").write_text(
        json.dumps(projection, indent=2, sort_keys=True), encoding="utf-8"
    )
    write_csv(output_dir / "systems_performance_runs.csv", performance)
    write_csv(output_dir / "systems_performance_aggregate.csv", performance_aggregate)
    write_csv(output_dir / "systems_fault_scenarios.csv", faults)
    (output_dir / "systems_unsafe_race_witness.json").write_text(
        json.dumps(unsafe_race_witness, indent=2, sort_keys=True), encoding="utf-8"
    )
    return int(
        not summary["all_fault_scenarios_passed"]
        or not summary["all_system_invariants_passed"]
        or not summary["unsafe_race_witness_passed"]
    )


if __name__ == "__main__":
    raise SystemExit(main())
