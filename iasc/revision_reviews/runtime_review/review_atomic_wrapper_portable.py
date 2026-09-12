"""Independent QA of new issuance boundaries, excluded from formal runs.

Injects BaseException, not process death; formal harness covers process kills.
Also forces cleanup to hold the SQLite write lock before a competing arm.
Does not send HTTP, forge acknowledgements, or modify implementation files.
"""
from pathlib import Path
import hashlib
import json
import sqlite3
import sys
import threading

HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parents[1]
E2E = PACKAGE_ROOT / "end_to_end"
required = ("CODE_FREEZE.json", "ecrc_e2e.py", "ordinary_e2e.py",
            "inputs/distinct_contenders.json", "inputs/mixed_claim_fallback.json")
if not all((E2E / name).is_file() for name in required):
    raise FileNotFoundError("Expected frozen end_to_end beside revision_reviews: " + str(E2E))
sys.path.insert(0, str(E2E))
sys.path.insert(0, str(E2E / "legacy_snapshot" / "source_snapshot"))
from ecrc_e2e import Adapter as Ecrc
from ordinary_e2e import Adapter as Ordinary

AT, EXPIRY = "2026-09-12T12:00:10.000000Z", "2026-09-12T13:00:10.000000Z"


class InjectedInterruption(BaseException):
    pass


def raw_state(path, arm):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        req = [dict(r) for r in db.execute("SELECT * FROM requests")]
        holds = [dict(r) for r in db.execute("SELECT * FROM " + ("reservations" if arm == "ecrc" else "holds"))]
        caps = [dict(r) for r in db.execute("SELECT * FROM " + ("capacity_state" if arm == "ecrc" else "budgets"))]
        return {"requests": req, "holds": holds, "caps": caps,
                "registry": db.execute("SELECT COUNT(*) FROM " + ("issued_permits" if arm == "ecrc" else "permit_registry")).fetchone()[0],
                "jobs": db.execute("SELECT COUNT(*) FROM " + ("delivery_outbox" if arm == "ecrc" else "delivery")).fetchone()[0]}
    finally:
        db.close()


def main():
    report_path = HERE / "WRAPPER_QA_PORTABLE_RESULT.json"
    if report_path.exists():
        raise FileExistsError("Preserve prior QA; use a fresh package copy: " + str(report_path))
    evidence_dir = HERE / "wrapper_qa_portable"
    assert not evidence_dir.exists(), "Preserve prior QA; use a new directory"
    evidence_dir.mkdir()
    normal = json.loads((E2E / "inputs/distinct_contenders.json").read_text())["requests"][0]
    unsupported = json.loads((E2E / "inputs/mixed_claim_fallback.json").read_text())["requests"][0]
    results = []
    for arm, cls in (("ecrc", Ecrc), ("ordinary", Ordinary)):
        for checkpoint in ("after_reservation", "after_release", "before_issue_commit"):
            request = unsupported if checkpoint == "after_release" else normal
            db_path = evidence_dir / (arm + "_" + checkpoint + ".sqlite")
            adapter = cls(db_path, request["policy"])
            adapter.ingest(request, AT)
            def stop(name):
                if name == checkpoint:
                    raise InjectedInterruption(name)
            try:
                adapter.issue(request["proposal"]["decision_id"], AT, stop)
                raise AssertionError("checkpoint did not interrupt")
            except InjectedInterruption:
                pass
            before = raw_state(db_path, arm)
            assert len(before["requests"]) == 1
            assert before["requests"][0]["state"] == "received" and before["requests"][0]["permit_json"] is None
            assert before["holds"] == before["caps"] == [] and before["registry"] == before["jobs"] == 0
            recovered = cls(db_path).issue(request["proposal"]["decision_id"], AT)
            assert recovered["route"] == ("abstain" if checkpoint == "after_release" else "alert")
            after = raw_state(db_path, arm)
            assert after["registry"] == 1 and len(after["holds"]) == 1
            assert after["holds"][0]["status"] == ("released" if checkpoint == "after_release" else "reserved")
            results.append({"arm": arm, "case": checkpoint, "pass": True, "before_recovery": before, "after_recovery": after})

        # Force cleanup-first linearization while another thread attempts arm.
        db_path = evidence_dir / (arm + "_cleanup_arm_race.sqlite")
        issue_adapter = cls(db_path, normal["policy"])
        issue_adapter.ingest(normal, AT)
        permit = issue_adapter.issue(normal["proposal"]["decision_id"], AT)
        cleaning, arming = cls(db_path), cls(db_path)
        entered, proceed = threading.Event(), threading.Event()
        if arm == "ecrc":
            original = cleaning.ledger._release_reservation_conn
            def intercept(*args, **kwargs):
                entered.set()
                assert proceed.wait(10), "cleanup barrier timeout"
                return original(*args, **kwargs)
            cleaning.ledger._release_reservation_conn = intercept
        else:
            original = cleaning._release
            def intercept(*args, **kwargs):
                entered.set()
                assert proceed.wait(10), "cleanup barrier timeout"
                return original(*args, **kwargs)
            cleaning._release = intercept
        outcomes = {}
        def cleanup():
            try:
                outcomes["cleanup"] = cleaning.cleanup(EXPIRY)
            except BaseException as exc:
                outcomes["cleanup_error"] = repr(exc)
        def arm_request():
            try:
                outcomes["armed"] = arming.arm(permit, AT)
            except Exception as exc:
                outcomes["arm_rejected"] = type(exc).__name__ + ": " + str(exc)
        cleaner = threading.Thread(target=cleanup)
        caller = threading.Thread(target=arm_request)
        cleaner.start()
        assert entered.wait(10), "cleanup did not acquire write transaction"
        caller.start()
        proceed.set()
        cleaner.join(12)
        caller.join(12)
        assert not cleaner.is_alive() and not caller.is_alive()
        assert "arm_rejected" in outcomes and "armed" not in outcomes and "cleanup_error" not in outcomes, outcomes
        final = raw_state(db_path, arm)
        assert final["requests"][0]["state"] == "cancelled" and final["jobs"] == 0
        assert final["holds"][0]["status"] == "released"
        assert sum(row["reserved" if arm == "ecrc" else "held"] for row in final["caps"]) == 0
        results.append({"arm": arm, "case": "cleanup_first_competing_arm", "pass": True, "outcomes": outcomes, "final": final})

        # Opposite legal order: a durable grant remains reserved after expiry.
        db_path = evidence_dir / (arm + "_armed_then_cleanup.sqlite")
        adapter = cls(db_path, normal["policy"])
        adapter.ingest(normal, AT)
        permit = adapter.issue(normal["proposal"]["decision_id"], AT)
        adapter.arm(permit, AT)
        adapter.cleanup(EXPIRY)
        final = raw_state(db_path, arm)
        assert final["jobs"] == 1 and final["requests"][0]["state"] == "issued"
        assert final["holds"][0]["status"] == "reserved"
        results.append({"arm": arm, "case": "armed_then_expiry_cleanup", "pass": True, "final": final})
    report = {"passed": all(r["pass"] for r in results), "qa_cases": len(results), "formal_denominator": False,
              "process_kills": False, "real_http": False,
              "source_sha256": {name: hashlib.sha256((E2E / name).read_bytes()).hexdigest() for name in ("ecrc_e2e.py", "ordinary_e2e.py", "service_e2e.py")},
              "results": results}
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
