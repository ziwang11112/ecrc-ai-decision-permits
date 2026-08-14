#!/usr/bin/env python3
"""Replay every official Mendeley-v2 HGB proposal through the ECRC runtime.

This is a retrospective technical replay with simulated side effects.  It
tests equivalence between the frozen E1 array router and the executable ECRC
adjudicator/ledger/PEP/receipt stack; it is not a live deployment.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd
from e1.provenance import (
    environment_record,
    finalize_manifest,
    git_record,
    input_hash_table,
    sha256_file,
    write_csv,
    write_gzip_csv,
    write_json,
)

from agentic_eeg_dm.governance import (
    ClaimRule,
    EvidenceEnvelope,
    EvidenceItem,
    EvidenceRule,
    ModelBinding,
    OrderedAdjudicator,
    PEPSimulator,
    PolicyManifest,
    ProposalEnvelope,
    SQLiteCapacityLedger,
    StatefulReceiptVerifier,
    canonical_hash,
)

SCRIPT_VERSION = "1.0.0"
DATASET_ID = "mendeley_igt_official_v2"
MODEL_NAME = "hist_gradient_boosting"
CAP_LABEL = "8"
PROPOSED_AT = "2026-01-01T00:00:05Z"
ADJUDICATED_AT = "2026-01-01T00:00:10Z"
EXECUTED_AT = "2026-01-01T00:00:11Z"

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
EVIDENCE_ROOT = HERE / "evidence_v2"
DEFAULT_PREDICTIONS = EVIDENCE_ROOT / "predictions.csv.gz"
DEFAULT_ROUTES = EVIDENCE_ROOT / "route_assignments.csv.gz"
DEFAULT_OPERATING_POINTS = EVIDENCE_ROOT / "frozen_operating_points.csv"
DEFAULT_MODEL = EVIDENCE_ROOT / "models" / "hist_gradient_boosting.joblib"
DEFAULT_VERSION_RECORD = EVIDENCE_ROOT / "mendeley_local_version_record.json"
DEFAULT_OUTPUT_DIR = HERE / "evidence_bridge"

RUNTIME_INPUT_COLUMNS = (
    "dataset_id",
    "evaluation_scope",
    "model_name",
    "subject_id",
    "study_id",
    "trial_id",
    "outer_fold",
    "score",
)
ARRAY_ROUTE_COLUMNS = (
    "dataset_id",
    "model_name",
    "subject_id",
    "trial_id",
    "cap_label",
    "score",
    "primary_route",
    "reason_code",
)
ROUTE_MAP = {
    "alert": "alert",
    "review": "human_review",
    "abstain": "abstain",
    "no_action": "no_action",
}
REASON_MAP = {
    "uncertainty_gate": "uncertainty_gate",
    "score_within_review_band": "risk_within_threshold_review_band",
    "review_capacity_exhausted": "review_capacity_exhausted",
    "score_above_review_band": "risk_above_review_band",
    "alert_capacity_exhausted": "auto_alert_capacity_exhausted",
    "score_below_threshold": "risk_below_prompt_threshold",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--routes", type=Path, default=DEFAULT_ROUTES)
    parser.add_argument(
        "--operating-points", type=Path, default=DEFAULT_OPERATING_POINTS
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--version-record", type=Path, default=DEFAULT_VERSION_RECORD)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Development-only prefix limit; omit for the complete 11,800-row replay.",
    )
    return parser.parse_args()


def load_frozen_inputs(
    predictions_path: Path,
    routes_path: Path,
    operating_points_path: Path,
    *,
    limit: int | None,
) -> tuple[pd.DataFrame, dict[str, float | int | str]]:
    predictions = pd.read_csv(predictions_path, usecols=list(RUNTIME_INPUT_COLUMNS))
    predictions = predictions[
        predictions["dataset_id"].eq(DATASET_ID)
        & predictions["model_name"].eq(MODEL_NAME)
    ].copy()
    predictions = predictions.sort_values(
        ["subject_id", "trial_id"], kind="mergesort"
    ).reset_index(drop=True)
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        predictions = predictions.iloc[:limit].copy()

    array_routes = pd.read_csv(
        routes_path,
        usecols=list(ARRAY_ROUTE_COLUMNS),
        dtype={"cap_label": str},
    )
    array_routes = array_routes[
        array_routes["dataset_id"].eq(DATASET_ID)
        & array_routes["model_name"].eq(MODEL_NAME)
        & array_routes["cap_label"].eq(CAP_LABEL)
    ].copy()
    if predictions.duplicated(["subject_id", "trial_id"]).any():
        raise ValueError(
            "Official-v2 predictions contain duplicate participant/trial keys"
        )
    if array_routes.duplicated(["subject_id", "trial_id"]).any():
        raise ValueError(
            "Official-v2 array routes contain duplicate participant/trial keys"
        )
    joined = predictions.merge(
        array_routes[
            ["subject_id", "trial_id", "score", "primary_route", "reason_code"]
        ],
        on=["subject_id", "trial_id"],
        how="left",
        suffixes=("", "_array"),
        validate="one_to_one",
    )
    if joined[["primary_route", "reason_code"]].isna().any().any():
        raise ValueError("An official-v2 prediction lacks its frozen cap-8 array route")
    if not np.allclose(
        joined["score"].to_numpy(dtype=float),
        joined["score_array"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-15,
    ):
        raise ValueError("Prediction and frozen-route scores differ")
    joined = joined.drop(columns="score_array")

    operating = pd.read_csv(operating_points_path)
    row = operating[operating["model_name"].eq(MODEL_NAME)]
    if len(row) != 1:
        raise ValueError("Expected one frozen HGB operating point")
    settings = row.iloc[0].to_dict()
    expected = {
        "reference_alert_cap": 8,
        "review_cap": 2,
        "review_band_width": 0.03,
        "uncertainty_threshold": 0.90,
        "uncertainty_mode": "probability_margin",
    }
    for name, value in expected.items():
        if settings[name] != value:
            raise ValueError(f"Unexpected frozen setting {name}={settings[name]!r}")
    return joined, settings


def build_policy(settings: dict[str, object], model_hash: str) -> PolicyManifest:
    return PolicyManifest(
        policy_id="official-v2-hgb-cap8-runtime-bridge",
        revision=1,
        issuer_id="retrospective-technical-replay-authority",
        effective_from="2026-01-01T00:00:00Z",
        expires_at="2026-01-02T00:00:00Z",
        approved_models=(ModelBinding(MODEL_NAME, model_hash),),
        evidence_rules=(
            EvidenceRule(
                evidence_type="behavior_score",
                allowed_sources=("frozen-official-v2-predictions",),
                allowed_schema_versions=("1.0",),
                max_age_seconds=60,
                use_allowed=True,
            ),
        ),
        score_threshold=float(settings["prompt_threshold"]),
        uncertainty_threshold=float(settings["uncertainty_threshold"]),
        review_band_width=float(settings["review_band_width"]),
        alert_capacity=int(settings["reference_alert_cap"]),
        review_capacity=int(settings["review_cap"]),
        capacity_scope="subject_session",
        claim_rules=(
            ClaimRule(
                "task_alert",
                ("alert",),
                required_evidence_types=("behavior_score",),
            ),
            ClaimRule(
                "task_review",
                ("review",),
                required_evidence_types=("behavior_score",),
            ),
            ClaimRule("task_abstention", ("abstain",)),
            ClaimRule("task_no_action", ("no_action",)),
        ),
        blocked_claim_ids=("clinical_diagnosis", "intervention_efficacy"),
    )


def proposal_and_evidence(
    row: object,
    *,
    model_hash: str,
    predictions_hash: str,
) -> tuple[ProposalEnvelope, EvidenceEnvelope]:
    decision_id = f"official-v2:{row.subject_id}:{int(row.trial_id):03d}"
    uncertainty = float(np.clip(1.0 - abs(2.0 * float(row.score) - 1.0), 0.0, 1.0))
    proposal = ProposalEnvelope(
        decision_id=decision_id,
        subject_id=str(row.subject_id),
        session_id="official-v2-frozen-replay",
        model_id=MODEL_NAME,
        model_version="official-v2-frozen-external-replay",
        model_hash=model_hash,
        score=float(row.score),
        uncertainty=uncertainty,
        proposed_action="alert",
        proposed_at=PROPOSED_AT,
        input_hash=canonical_hash(
            {
                "dataset_id": DATASET_ID,
                "subject_id": str(row.subject_id),
                "trial_id": int(row.trial_id),
                "score": float(row.score),
                "model_hash": model_hash,
            }
        ),
        validation_scope_id="official-v2-frozen-external-same-task",
    )
    evidence_id = f"behavior-score::{decision_id}"
    evidence = EvidenceEnvelope(
        decision_id=decision_id,
        created_at="2026-01-01T00:00:04Z",
        items=(
            EvidenceItem(
                evidence_id=evidence_id,
                evidence_type="behavior_score",
                source="frozen-official-v2-predictions",
                schema_version="1.0",
                observed_at="2026-01-01T00:00:03Z",
                available_at="2026-01-01T00:00:04Z",
                provenance_hash=canonical_hash(
                    {
                        "predictions_sha256": predictions_hash,
                        "decision_id": decision_id,
                        "score": float(row.score),
                    }
                ),
                requested_for_use=True,
            ),
        ),
    )
    return proposal, evidence


def write_runtime_jsonl_gzip(
    path: Path,
    permits: list[object],
    receipts: list[object],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            for permit, receipt in zip(permits, receipts, strict=True):
                line = json.dumps(
                    {"permit": permit.to_dict(), "receipt": receipt.to_dict()},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                compressed.write(line.encode("utf-8") + b"\n")
    return path


def checkpoint_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    database_path = output_dir / "runtime_bridge.sqlite"
    if database_path.exists():
        database_path.unlink()

    source_paths = [
        args.predictions.resolve(),
        args.routes.resolve(),
        args.operating_points.resolve(),
        args.model.resolve(),
        args.version_record.resolve(),
    ]
    for path in source_paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    version_record = json.loads(args.version_record.read_text(encoding="utf-8"))
    if version_record.get("doi") != "10.17632/2pw2m39yct.2":
        raise ValueError("Version record is not official Mendeley v2")
    if (
        version_record.get("official_current_version_checked_2026_08_13", {}).get(
            "used_in_this_run"
        )
        is not True
    ):
        raise ValueError("Version record does not mark official v2 as used")

    frozen, settings = load_frozen_inputs(
        args.predictions,
        args.routes,
        args.operating_points,
        limit=args.limit,
    )
    complete_replay = args.limit is None
    if complete_replay and len(frozen) != 11_800:
        raise ValueError(
            f"Complete official-v2 replay requires 11,800 rows, got {len(frozen)}"
        )
    if complete_replay and frozen["subject_id"].nunique() != 59:
        raise ValueError("Complete official-v2 replay requires 59 participants")
    if "y_true" in frozen.columns or any(
        "label" in name.lower() for name in frozen.columns
    ):
        raise AssertionError("A current label entered the runtime bridge input")
    if any("eeg" in name.lower() for name in frozen.columns):
        raise AssertionError("An EEG column entered the runtime bridge input")

    model_hash = sha256_file(args.model)
    predictions_hash = sha256_file(args.predictions)
    policy = build_policy(settings, model_hash)
    ledger = SQLiteCapacityLedger(database_path)
    ledger.register_policy(policy)
    adjudicator = OrderedAdjudicator(ledger)
    pep = PEPSimulator(ledger, enforcement_point_id="official-v2-runtime-bridge-pep")
    permits: list[object] = []
    receipts: list[object] = []
    rows: list[dict[str, object]] = []
    started = time.perf_counter()
    for position, row in enumerate(frozen.itertuples(index=False), 1):
        proposal, evidence = proposal_and_evidence(
            row,
            model_hash=model_hash,
            predictions_hash=predictions_hash,
        )
        permit = adjudicator.adjudicate(policy, proposal, evidence, at=ADJUDICATED_AT)
        receipt = pep.execute(policy, permit, at=EXECUTED_AT)
        mapped_route = ROUTE_MAP[permit.route]
        mapped_reason = REASON_MAP[permit.reason_code]
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "subject_id": row.subject_id,
                "trial_id": int(row.trial_id),
                "score": float(row.score),
                "array_route": row.primary_route,
                "array_reason": row.reason_code,
                "runtime_route": permit.route,
                "runtime_route_mapped_to_e1": mapped_route,
                "runtime_reason": permit.reason_code,
                "runtime_reason_mapped_to_e1": mapped_reason,
                "route_match": mapped_route == row.primary_route,
                "reason_match": mapped_reason == row.reason_code,
                "permit_id": permit.permit_id,
                "permit_hash": permit.content_hash,
                "reservation_id": permit.reservation_id,
                "receipt_id": receipt.receipt_id,
                "receipt_hash": receipt.content_hash,
                "receipt_sequence_no": receipt.sequence_no,
                "execution_status": receipt.execution_status,
                "side_effect_id": receipt.side_effect_id,
                "proposal_hash": permit.proposal_hash,
                "evidence_hash": permit.evidence_hash,
                "policy_hash": permit.policy_hash,
                "current_label_in_runtime_payload": False,
                "simulated_side_effect": True,
            }
        )
        permits.append(permit)
        receipts.append(receipt)
        if position % 1_000 == 0:
            print(f"processed {position:,}/{len(frozen):,}", flush=True)
    elapsed = time.perf_counter() - started

    trusted_receipts = ledger.list_receipts()
    trusted_tail = ledger.tail_receipt_hash()
    StatefulReceiptVerifier().verify_chain(
        trusted_receipts,
        {permit.permit_id: permit for permit in permits},
        expected_tail_hash=trusted_tail,
    )
    decisions = pd.DataFrame(rows)
    if not decisions["route_match"].all() or not decisions["reason_match"].all():
        mismatch = decisions[~(decisions["route_match"] & decisions["reason_match"])]
        raise AssertionError(
            f"Runtime disagreed with array router on {len(mismatch)} rows"
        )

    snapshot_rows: list[dict[str, object]] = []
    for subject_id in sorted(frozen["subject_id"].unique()):
        scope = f"{subject_id}::official-v2-frozen-replay"
        for resource in ("alert", "review"):
            snapshot = ledger.capacity_snapshot(
                policy, scope_key=scope, resource=resource
            )
            snapshot_rows.append(
                {
                    "subject_id": subject_id,
                    "scope_key": scope,
                    "resource": resource,
                    "capacity_limit": snapshot.capacity_limit,
                    "reserved": snapshot.reserved,
                    "committed": snapshot.committed,
                    "available": snapshot.available,
                    "state_revision": snapshot.state_revision,
                    "quota_excess": max(
                        0,
                        snapshot.reserved
                        + snapshot.committed
                        - snapshot.capacity_limit,
                    ),
                }
            )
    snapshots = pd.DataFrame(snapshot_rows)
    if int(snapshots["quota_excess"].sum()) != 0:
        raise AssertionError("Runtime bridge exceeded a participant quota")

    counts = ledger.counts()
    n_action = int(decisions["runtime_route"].isin(("alert", "review")).sum())
    expected_count = len(frozen)
    if (
        counts.issued_permits != expected_count
        or counts.executions != expected_count
        or counts.receipts != expected_count
        or counts.reservations_committed != n_action
        or counts.reservations_reserved != 0
    ):
        raise AssertionError("Runtime ledger counts do not match the replay")
    checkpoint_database(database_path)

    artifacts: list[Path] = []
    artifacts.append(write_gzip_csv(output_dir / "bridge_decisions.csv.gz", decisions))
    artifacts.append(write_csv(output_dir / "capacity_snapshots.csv", snapshots))
    artifacts.append(
        write_runtime_jsonl_gzip(
            output_dir / "runtime_artifacts.jsonl.gz", permits, receipts
        )
    )
    artifacts.append(write_json(output_dir / "policy_manifest.json", policy.to_dict()))
    input_contract = {
        "runtime_input_columns": list(RUNTIME_INPUT_COLUMNS),
        "array_comparison_columns": list(ARRAY_ROUTE_COLUMNS),
        "current_label_read": False,
        "current_label_in_proposal": False,
        "current_label_in_evidence": False,
        "current_label_in_routing": False,
        "eeg_columns_read": [],
        "eeg_files_read": 0,
        "route_map": ROUTE_MAP,
        "reason_map": REASON_MAP,
        "processing_order": "subject_id then trial_id; one subject_session scope per participant",
    }
    artifacts.append(
        write_json(output_dir / "runtime_input_contract.json", input_contract)
    )
    artifacts.append(
        write_csv(
            output_dir / "input_hashes.csv",
            input_hash_table(source_paths, base=REPOSITORY_ROOT),
        )
    )
    code_paths = [
        Path(__file__),
        REPOSITORY_ROOT / "src" / "agentic_eeg_dm" / "governance" / "adjudicator.py",
        REPOSITORY_ROOT / "src" / "agentic_eeg_dm" / "governance" / "enforcement.py",
        REPOSITORY_ROOT / "src" / "agentic_eeg_dm" / "governance" / "ledger.py",
        REPOSITORY_ROOT / "src" / "agentic_eeg_dm" / "governance" / "models.py",
        REPOSITORY_ROOT / "src" / "agentic_eeg_dm" / "governance" / "verifier.py",
    ]
    artifacts.append(
        write_csv(
            output_dir / "code_hashes.csv",
            pd.DataFrame(
                [
                    {
                        "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                    for path in code_paths
                ]
            ),
        )
    )
    summary = {
        "experiment": "official_v2_frozen_hgb_runtime_bridge",
        "script_version": SCRIPT_VERSION,
        "complete_official_v2_replay": complete_replay,
        "dataset_id": DATASET_ID,
        "doi": version_record["doi"],
        "n_predictions": expected_count,
        "n_participants": int(frozen["subject_id"].nunique()),
        "model_name": MODEL_NAME,
        "model_sha256": model_hash,
        "array_route_match_count": int(decisions["route_match"].sum()),
        "array_route_mismatch_count": int((~decisions["route_match"]).sum()),
        "array_reason_match_count": int(decisions["reason_match"].sum()),
        "array_reason_mismatch_count": int((~decisions["reason_match"]).sum()),
        "issued_permits": counts.issued_permits,
        "executions": counts.executions,
        "receipts": counts.receipts,
        "committed_reservations": counts.reservations_committed,
        "pending_reservations": counts.reservations_reserved,
        "released_reservations": counts.reservations_released,
        "quota_excess_total": int(snapshots["quota_excess"].sum()),
        "receipt_chain_verified_against_trusted_tail": True,
        "trusted_tail_hash": trusted_tail,
        "current_label_read_or_used": False,
        "eeg_read_or_used": False,
        "elapsed_seconds": elapsed,
        "rows_per_second": expected_count / elapsed,
        "runtime_database_retained": False,
        "side_effect_mode": "SQLite PEP simulation only",
        "live_deployment": False,
        "interpretation": (
            "retrospective technical replay demonstrating exact route/reason "
            "equivalence and executable governance-state accounting; not live deployment"
        ),
    }
    artifacts.append(write_json(output_dir / "bridge_summary.json", summary))
    notes = """# Official Mendeley-v2 ECRC runtime bridge

Every frozen HGB proposal in the 11,800-decision official Mendeley-v2 replay is
sent, in participant/trial order, through `OrderedAdjudicator`, the trusted
SQLite issued-permit/capacity registry, `PEPSimulator`, and the stateful receipt
verifier. The comparison target is the frozen E1 cap-8/review-2 array router.

The current proxy label is never read by this script and is absent from the
proposal, evidence, and routing payloads. The bridge uses no EEG data. Side
effects are simulated inside SQLite; this is a retrospective technical replay,
not a live participant deployment or evidence of atomicity with an external
alert/ticketing service.
"""
    notes_path = output_dir / "README.md"
    notes_path.write_text(notes, encoding="utf-8")
    artifacts.append(notes_path)

    # The deterministic permits/receipts and capacity snapshots are the
    # versionable evidence.  Remove the implementation database (and any
    # sidecars) after all trusted-state checks have completed.
    for database_artifact in (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ):
        if database_artifact.exists():
            database_artifact.unlink()

    manifest_payload = {
        **summary,
        "policy_hash": policy.policy_hash,
        "frozen_settings": settings,
        "runtime_input_contract": input_contract,
        "environment": environment_record(),
        "git": git_record(REPOSITORY_ROOT),
    }
    manifest_path, checksums_path = finalize_manifest(
        output_dir,
        manifest_payload=manifest_payload,
        artifact_paths=artifacts,
    )
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    print(f"manifest: {manifest_path}", flush=True)
    print(f"checksums: {checksums_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
