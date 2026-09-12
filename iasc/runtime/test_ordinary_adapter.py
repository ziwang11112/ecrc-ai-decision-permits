"""Independent hand-authored API checks; synthetic ACKs, not service results."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import ast
import copy
import hashlib
import json

from ordinary_adapter import Adapter

HERE = Path(__file__).resolve().parent
ARM = "2026-09-11T12:00:10Z"
LATER = "2031-01-01T00:00:00Z"


def wire(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def hash_value(x):
    return hashlib.sha256(wire(x).encode()).hexdigest()


def hand_fixture(nonaction=False):
    policy = {"policy_id": "manual-policy", "revision": 1, "effective_from": "2026-09-11T00:00:00Z",
              "expires_at": "2030-01-01T00:00:00Z", "allowed_routes": ["alert", "no_action"],
              "blocked_claim_ids": ["diagnosis"], "claim_rules": [
                  {"claim_id": "task_alert", "routes": ["alert"], "reason_codes": []},
                  {"claim_id": "task_no_action", "routes": ["no_action"], "reason_codes": []}]}
    permit = {"permit_id": "manual-permit", "decision_id": "manual-decision", "policy_id": policy["policy_id"],
              "policy_revision": 1, "policy_hash": hash_value(policy), "proposal_hash": "a" * 64,
              "evidence_hash": "b" * 64, "request_hash": "c" * 64,
              "route": "no_action" if nonaction else "alert", "reason_code": "manual-rule",
              "issued_at": ARM, "expires_at": "2026-09-12T12:00:10Z", "pre_state_revision": 0,
              "post_state_revision": 0 if nonaction else 1, "reservation_id": None if nonaction else "manual-hold",
              "reserved_resource": None if nonaction else "alert", "admitted_evidence_ids": ["manual-evidence"],
              "used_evidence_ids": ["manual-evidence"], "excluded_evidence_ids": [],
              "permitted_claim_ids": ["task_no_action" if nonaction else "task_alert"], "blocked_claim_ids": ["diagnosis"]}
    issued = {k: permit[k] for k in ("permit_id", "decision_id", "policy_id", "policy_revision", "policy_hash", "request_hash", "reservation_id", "route", "reason_code", "issued_at")}
    issued["permit_hash"] = hash_value(permit)
    reservation = {k: permit[k] for k in ("reservation_id", "permit_id", "request_hash", "policy_id", "policy_revision", "policy_hash", "pre_state_revision", "post_state_revision")}
    reservation.update(permit_hash=hash_value(permit), scope_key="manual-scope", resource="alert", amount=1, status="reserved", updated_at=ARM)
    budget = dict(policy_id=policy["policy_id"], policy_revision=1, scope_key="manual-scope", resource="alert",
                  capacity_limit=1, reserved=1, committed=0, state_revision=1)
    return {"policy": policy, "permits": [permit], "issued_permits": [issued],
            "reservations": [] if nonaction else [reservation], "capacity_state": [] if nonaction else [budget]}


def ack_for(job):
    return {"effect_id": 1, "idempotency_key": job["idempotency_key"],
            "payload_hash": job["payload_hash"], "payload": json.loads(job["payload_json"]),
            "committed_at": "2026-09-11T13:00:00Z", "created": True}


def rejected(fn):
    try:
        fn()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError("invalid operation accepted")


def main(out):
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = []

    def run(name, check, fixture=None):
        data = copy.deepcopy(fixture if fixture is not None else hand_fixture())
        path = out / (name + ".sqlite")
        assert not path.exists(), "Use a fresh test output directory"
        (out / (name + "_fixture.json")).write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        adapter = Adapter(path)
        check(adapter, data)
        state = adapter.snapshot()
        results.append({"name": name, "passed": True, "final_snapshot": state,
                        "fixture_sha256": hash_value(data), "ack_source": "synthetic_unit_check_only"})

    def normal(a, f):
        a.seed(f)
        p = f["permits"][0]
        j = a.arm(p, ARM)
        receipt = a.finish(p["permit_id"], ack_for(j), ARM)
        assert a.finish(p["permit_id"], ack_for(j), LATER) == receipt
        assert a.arm(p, LATER)["state"] == "receipted"
        assert receipt["committed_at"] == "2026-09-11T13:00:00Z"
        assert receipt["reconciliation_policy_clock"] == ARM
        assert receipt["reconciled_at"] != ARM
        s = a.snapshot()
        assert (s["n_receipts"], s["committed"], s["reserved"]) == (1, 1, 0)
    run("valid_and_idempotent_completion", normal)

    def altered(a, f):
        a.seed(f)
        p = copy.deepcopy(f["permits"][0]); p["permitted_claim_ids"] = ["diagnosis"]
        rejected(lambda: a.arm(p, ARM))
        assert a.snapshot()["n_jobs"] == 0
    run("altered_registered_claim", altered)
    run("expired_before_arm", lambda a, f: (a.seed(f), rejected(lambda: a.arm(f["permits"][0], LATER))))
    run("revoked_before_arm", lambda a, f: (a.seed(f), a.revoke(), rejected(lambda: a.arm(f["permits"][0], ARM))))
    run("nonaction_no_dispatch", lambda a, f: (a.seed(f), rejected(lambda: a.arm(f["permits"][0], ARM))), hand_fixture(True))

    def irrevocable(a, f, revoke):
        a.seed(f); p = f["permits"][0]; j = a.arm(p, ARM)
        if revoke: a.revoke()
        assert a.arm(p, LATER) == j
        result = a.finish(p["permit_id"], ack_for(j), LATER)
        assert result["armed_at"] == ARM and result["reconciliation_policy_clock"] == LATER
        assert result["committed_at"] == "2026-09-11T13:00:00Z"
        assert a.snapshot()["reserved"] == 0
    run("revoked_after_arm_durable_grant", lambda a, f: irrevocable(a, f, True))
    run("expired_after_arm_durable_grant", lambda a, f: irrevocable(a, f, False))

    def rollback(a, f):
        a.seed(f); p = f["permits"][0]; j = a.arm(p, ARM)
        def fault(): raise RuntimeError("synthetic pre-commit exception")
        try: a.finish(p["permit_id"], ack_for(j), ARM, before_commit=fault)
        except RuntimeError: pass
        else: raise AssertionError("fault did not fire")
        assert a.snapshot()["n_receipts"] == 0 and a.snapshot()["reserved"] == 1
        assert a.get_job(p["permit_id"])["state"] == "armed"
        a.finish(p["permit_id"], ack_for(j), ARM)
        assert a.snapshot()["n_receipts"] == 1
    run("transaction_exception_rollback", rollback)

    def conflict_after_arm(a, f):
        a.seed(f); p = f["permits"][0]; a.arm(p, ARM)
        changed = copy.deepcopy(p); changed["evidence_hash"] = "d" * 64
        rejected(lambda: a.arm(changed, LATER))
        assert a.snapshot()["n_jobs"] == 1
    run("changed_content_under_armed_key", conflict_after_arm)

    def invalid_ack(a, f, field, value):
        a.seed(f); p = f["permits"][0]; j = a.arm(p, ARM); ack = ack_for(j); ack[field] = value
        rejected(lambda: a.finish(p["permit_id"], ack, ARM))
        s = a.snapshot(); assert (s["n_receipts"], s["reserved"], s["committed"]) == (0, 1, 0)
    run("ack_wrong_key", lambda a, f: invalid_ack(a, f, "idempotency_key", "other-key"))
    run("ack_wrong_hash", lambda a, f: invalid_ack(a, f, "payload_hash", "d" * 64))
    run("ack_missing_effect_id", lambda a, f: invalid_ack(a, f, "effect_id", ""))
    run("ack_payload_hash_disagrees", lambda a, f: invalid_ack(a, f, "payload", {"unrelated": True}))

    bad_hold = hand_fixture(); bad_hold["reservations"][0]["request_hash"] = "d" * 64
    run("reservation_content_conflict", lambda a, f: (a.seed(f), rejected(lambda: a.arm(f["permits"][0], ARM))), bad_hold)
    bad_count = hand_fixture(); bad_count["capacity_state"][0]["reserved"] = 0
    run("reject_inconsistent_seed_accounting", lambda a, f: rejected(lambda: a.seed(f)), bad_count)

    def concurrency(a, f):
        a.seed(f); p = f["permits"][0]
        def attempt(_):
            j = a.arm(p, ARM)
            return a.finish(p["permit_id"], ack_for(j), ARM)
        with ThreadPoolExecutor(max_workers=8) as pool: receipts = list(pool.map(attempt, range(8)))
        assert all(r == receipts[0] for r in receipts)
        assert a.snapshot()["n_receipts"] == a.snapshot()["committed"] == 1
    run("eight_thread_duplicate_calls", concurrency)

    def reopen(a, f):
        a.seed(f); p = f["permits"][0]; j = a.arm(p, ARM)
        other = Adapter(a.path)
        assert other.get_job(p["permit_id"]) == j
        other.finish(p["permit_id"], ack_for(j), ARM)
        assert a.snapshot()["n_receipts"] == 1
    run("reopen_durable_intent", reopen)
    run("finish_unarmed_rejected", lambda a, f: (a.seed(f), rejected(lambda: a.finish(f["permits"][0]["permit_id"], {}, ARM))))

    actual = HERE / "smoke_fixture2/fixture.json"
    if actual.is_file():
        run("shared_real_adjudication_fixture_API_smoke", normal, json.loads(actual.read_text()))
    imports = ast.parse((HERE / "ordinary_adapter.py").read_text())
    modules = sorted({alias.name for node in ast.walk(imports) if isinstance(node, ast.Import) for alias in node.names} |
                     {node.module for node in ast.walk(imports) if isinstance(node, ast.ImportFrom)})
    assert not any("agentic" in x or "ecrc" in x for x in modules)
    report = {"scope": "API unit checks; synthetic acknowledgements, no HTTP or measured crash trial", "n_checks": len(results),
              "all_passed": True, "imports": modules, "adapter_sha256": hashlib.sha256((HERE / "ordinary_adapter.py").read_bytes()).hexdigest(),
              "test_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "results": results}
    (out / "ordinary_unit_results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "ordinary_unit_checks")
    main(parser.parse_args().out)
