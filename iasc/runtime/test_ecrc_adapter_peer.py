"""Independent supplementary ECRC adapter checks against real HTTP subprocesses."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import platform
import sqlite3
import sys
import traceback
from urllib.parse import quote

from ecrc_adapter import Adapter
from fixture import make_fixture, ARM_AT, DONE_AT, EXPIRED_AT
from test_service import ServiceProcess, request, durable_rows

HERE = Path(__file__).resolve().parent


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observed(db):
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        result = {name: [dict(r) for r in connection.execute("SELECT * FROM " + name)]
                  for name in ("capacity_state", "reservations", "issued_permits",
                               "delivery_outbox", "receipt_log", "executions")}
        result["reserved"] = sum(r["reserved"] for r in result["capacity_state"])
        result["committed"] = sum(r["committed"] for r in result["capacity_state"])
        assert all(0 <= r["reserved"] and 0 <= r["committed"] and
                   r["reserved"] + r["committed"] <= r["capacity_limit"]
                   for r in result["capacity_state"])
        return result
    finally:
        connection.close()


def expect_error(call):
    try:
        call()
    except Exception as error:
        return type(error).__name__ + ": " + str(error)
    raise AssertionError("expected operation to fail")


def post(server, job, drop=False):
    return request(server, "POST", "/effects",
                   {"idempotency_key": job["idempotency_key"], "payload": json.loads(job["payload_json"])},
                   headers={"X-Test-Drop-Response": "1"} if drop else None)


def completed_checks(adapter, server, db, permit, receipt, ack):
    state = observed(db)
    assert len(state["receipt_log"]) == len(state["executions"]) == len(state["delivery_outbox"]) == 1
    assert state["reserved"] == 0 and state["committed"] == 1
    assert state["delivery_outbox"][0]["state"] == "receipted"
    rows = durable_rows(server.db)
    assert len(rows) == 1
    row = rows[0]
    assert type(receipt["service_effect_id"]) is int
    assert receipt["service_effect_id"] == row["effect_id"] == ack["effect_id"]
    assert receipt["side_effect_id"] == str(row["effect_id"])
    # Timestamp syntax may normalize UTC +00:00 to Z, but the observed instant is unchanged.
    from datetime import datetime
    stamp = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert stamp(receipt["service_committed_at"]) == stamp(row["committed_at"])
    assert stamp(receipt["executed_at"]) == stamp(row["committed_at"])
    assert stamp(receipt["reconciled_at"]) >= stamp(row["committed_at"])
    assert stamp(receipt["authorized_at"]) == stamp(ARM_AT)
    saved_ack = json.loads(state["delivery_outbox"][0]["ack_json"])
    assert saved_ack["payload_hash"] == row["payload_hash"]
    assert saved_ack["payload"] == json.loads(row["payload_json"])
    assert row["idempotency_key"] == permit["permit_id"]
    assert row["payload_hash"] == hashlib.sha256(row["payload_json"].encode()).hexdigest()
    base_receipt = json.loads(state["receipt_log"][0]["receipt_json"])
    assert all(receipt[k] == v for k, v in base_receipt.items())
    assert hashlib.sha256(canonical(base_receipt).encode()).hexdigest() == state["receipt_log"][0]["receipt_hash"]
    return {"sink_effects": 1, "local_receipts": 1, "reserved": 0, "committed": 1,
            "effect_binding_and_base_receipt_hash_checked": True}


def run_case(case, name):
    fixture = make_fixture(case / "fixture", include_nonaction=True)
    permit = fixture["permits"][0]
    db = case / "client.sqlite"
    adapter = Adapter(db)
    adapter.seed(fixture)
    server = ServiceProcess(case / "sink.sqlite", case / "service.stderr.txt")
    extra = {}
    try:
        if name.startswith("reject_"):
            value = deepcopy(permit)
            at = ARM_AT
            if name == "reject_changed":
                value["decision_id"] = "unregistered-changed-id"
            elif name == "reject_expired":
                at = permit["expires_at"]
            elif name == "reject_policy_expired":
                at = EXPIRED_AT
            elif name == "reject_before_issuance":
                at = "2026-09-11T12:00:09Z"
            elif name == "reject_revoked":
                adapter.revoke()
            elif name == "reject_nonaction":
                value = fixture["permits"][1]
            extra["rejection"] = expect_error(lambda: adapter.arm(value, at))
            state = observed(db)
            assert len(state["delivery_outbox"]) == len(state["receipt_log"]) == len(state["executions"]) == 0
            assert state["reserved"] == 1 and state["committed"] == 0
            assert durable_rows(server.db) == []
            return dict(extra, sink_effects=0, local_receipts=0, preissued_reservation_still_held=1)

        if name == "canonical_payload":
            submitted = deepcopy(permit)
            for key in ("decision_id",):
                submitted[key] = "  " + submitted[key] + "  "
            for key in ("permitted_claim_ids", "used_evidence_ids", "admitted_evidence_ids"):
                submitted[key] = ["  " + v + "  " for v in submitted[key]]
            try:
                job = adapter.arm(submitted, ARM_AT)
            except ValueError as error:
                state = observed(db)
                assert not state["delivery_outbox"] and not state["receipt_log"] and not durable_rows(server.db)
                return dict(noncanonical_input_safely_rejected=str(error), sink_effects=0, local_receipts=0)
            expected = {k: permit[k] for k in ("decision_id", "route", "permitted_claim_ids", "used_evidence_ids")}
            assert json.loads(job["payload_json"]) == expected, "payload differs from validated canonical permit projection"
            extra["noncanonical_input_normalized_before_payload_projection"] = True
        else:
            job = adapter.arm(permit, ARM_AT)

        if name == "unknown_hold_and_postarm_authorization":
            status, _ = request(server, "GET", "/effects/" + quote(job["idempotency_key"], safe=""))
            assert status == 404
            adapter.revoke()
            # Original reaper deliberately excludes issued reservations, even after its lease has passed.
            reclaimed = adapter.ledger.reap_expired_reservations(at=EXPIRED_AT)
            assert not reclaimed
            state = observed(db)
            assert state["reserved"] == 1 and state["committed"] == len(state["receipt_log"]) == 0
            adapter = Adapter(db)
            recovered = adapter.arm(permit, EXPIRED_AT)
            assert recovered["payload_json"] == job["payload_json"] and recovered["armed_at"] == job["armed_at"]
            extra["negative_lookup_and_expired_lease_leave_held"] = True
            extra["postarm_revocation_and_expiry_resume_original_intent"] = True

        if name == "lost_response":
            try:
                post(server, job, drop=True)
            except (http.client.RemoteDisconnected, ConnectionResetError) as error:
                extra["transport_failure"] = type(error).__name__
            else:
                raise AssertionError("drop injection unexpectedly returned an HTTP reply")
            assert len(durable_rows(server.db)) == 1
            state = observed(db)
            assert state["reserved"] == 1 and state["committed"] == len(state["receipt_log"]) == 0
            adapter.revoke()
            adapter = Adapter(db)
            adapter.arm(permit, EXPIRED_AT)
            status, ack = request(server, "GET", "/effects/" + quote(job["idempotency_key"], safe=""))
            assert status == 200
            extra["unknown_effect_present_reservation_held"] = True
        else:
            status, ack = post(server, job)
            assert status == 201

        if name == "rollback_before_commit":
            class InjectedRollback(Exception):
                pass
            def interrupted():
                # A second reader sees only the prior committed state while completion is still open.
                state = observed(db)
                assert state["reserved"] == 1 and state["committed"] == len(state["receipt_log"]) == 0
                assert state["delivery_outbox"][0]["state"] == "armed"
                raise InjectedRollback("controlled exception before local commit")
            extra["failure"] = expect_error(lambda: adapter.finish(permit["permit_id"], ack, DONE_AT, before_commit=interrupted))
            assert extra["failure"].startswith("InjectedRollback:")
            state = observed(db)
            assert state["reserved"] == 1 and state["committed"] == len(state["receipt_log"]) == len(state["executions"]) == 0
            assert state["delivery_outbox"][0]["state"] == "armed"
            extra["all_local_completion_writes_rolled_back"] = True

        if name == "invalid_ack":
            errors = []
            for field, value in (("idempotency_key", "different"), ("payload_hash", "0" * 64),
                                 ("effect_id", 0), ("effect_id", True), ("committed_at", "invalid"),
                                 ("payload", {"different": "body"})):
                wrong = dict(ack, **{field: value})
                errors.append(expect_error(lambda: adapter.finish(permit["permit_id"], wrong, DONE_AT)))
                state = observed(db)
                assert state["reserved"] == 1 and state["committed"] == len(state["receipt_log"]) == len(state["executions"]) == 0
            extra["rejections"] = errors

        finish_at = EXPIRED_AT if name in ("unknown_hold_and_postarm_authorization", "lost_response") else DONE_AT
        if name == "concurrent_finish":
            with ThreadPoolExecutor(max_workers=20) as pool:
                receipts = list(pool.map(lambda _: Adapter(db).finish(permit["permit_id"], ack, finish_at), range(20)))
            assert all(r == receipts[0] for r in receipts)
            receipt = receipts[0]
            extra["concurrent_reconciliations"] = 20
        else:
            receipt = adapter.finish(permit["permit_id"], ack, finish_at)
        replay = Adapter(db).finish(permit["permit_id"], ack, EXPIRED_AT)
        assert replay == receipt
        return dict(completed_checks(adapter, server, db, permit, receipt, ack), **extra)
    finally:
        server.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    assert out.is_relative_to(HERE.resolve()) and not out.exists()
    out.mkdir(parents=True)
    paths = [HERE / name for name in ("ecrc_adapter.py", "fixture.py", "service.py", "test_ecrc_adapter_peer.py", "PROTOCOL_ECRC_PEER.md", "PROTOCOL.md")]
    report = {"python": sys.version, "sqlite": sqlite3.sqlite_version, "platform": platform.platform(),
              "input_hashes_before": {str(p.relative_to(HERE)): digest(p) for p in paths}, "cases": []}
    names = ["normal", "canonical_payload", "reject_changed", "reject_expired", "reject_policy_expired", "reject_before_issuance", "reject_revoked",
             "reject_nonaction", "unknown_hold_and_postarm_authorization", "lost_response",
             "rollback_before_commit", "invalid_ack", "concurrent_finish"]
    for name in names:
        case = out / name
        case.mkdir()
        try:
            details = run_case(case, name)
            result = {"case": name, "passed": True, "details": details}
        except Exception:
            result = {"case": name, "passed": False, "error": traceback.format_exc()}
        report["cases"].append(result)
        print(json.dumps(result), flush=True)
    report["input_hashes_after"] = {str(p.relative_to(HERE)): digest(p) for p in paths}
    report["code_unchanged_during_run"] = report["input_hashes_before"] == report["input_hashes_after"]
    report["passed"] = all(r["passed"] for r in report["cases"]) and report["code_unchanged_during_run"]
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
