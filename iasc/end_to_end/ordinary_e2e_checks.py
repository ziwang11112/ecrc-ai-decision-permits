"""Small development checks; excluded from the 36-run formal denominator.

Uses shared raw input data only. Synthetic acknowledgement checks here are
interface unit checks, not evidence of real HTTP recovery. Process-kill and
independent HTTP evidence belong to the separately reviewed formal runner.
"""
from __future__ import annotations

import copy
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ordinary_e2e import Adapter, digest

HERE = Path(__file__).resolve().parent
AT = "2026-09-12T12:00:10.000000Z"
LATER = "2026-09-12T13:00:10.000000Z"


def main():
    data = json.loads((HERE / "inputs/mixed_claim_fallback.json").read_text("utf-8"))["requests"]
    unsupported, action = data[0], data[1]
    policy = action["policy"]
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    def rejects(name, call):
        try:
            call()
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError(name)

    def renumber(request, name):
        result = copy.deepcopy(request)
        result["proposal"]["decision_id"] = name
        result["evidence"]["decision_id"] = name
        return result

    class SimulatedInterruption(Exception):
        pass

    def interrupt(target):
        def hook(stage):
            if stage == target:
                raise SimulatedInterruption(stage)
        return hook

    with tempfile.TemporaryDirectory(prefix="ordinary-e2e-dev-") as tmp:
        root = Path(tmp)
        adapter = Adapter(root / "fallback.sqlite", policy)
        adapter.ingest(unsupported, AT)
        first = adapter.issue("unsupported", AT)
        snapshot = adapter.snapshot()
        check("unsupported action registers abstain", first["route"] == "abstain" and first["reason_code"] == "no_claim_supported_by_used_evidence")
        check("unsupported action retains released hold and frees budget", snapshot["reserved"] == 0 and len(snapshot["reservations"]) == 1 and snapshot["reservations"][0]["status"] == "released")
        for request in data[1:]:
            adapter.ingest(request, AT)
            adapter.issue(request["proposal"]["decision_id"], AT)
        issued = adapter.snapshot()
        check("released alert budget reusable and review bounded", sum(p["route"] == "alert" for p in issued["permits"]) == 2 and sum(p["route"] == "review" for p in issued["permits"]) == 1 and issued["reserved"] == 3)
        check("ordinary raw journal hash binds original JSON", all(r["request_hash"] == digest(json.loads(r["request_json"])) for r in issued["requests"]))
        before = adapter.snapshot()
        for request in data:
            adapter.ingest(request, AT)
            recovered = adapter.issue(request["proposal"]["decision_id"], LATER)
            check("stable issued replay " + request["proposal"]["decision_id"], recovered == adapter.get_permit(request["proposal"]["decision_id"]))
        check("replays allocate nothing", before == adapter.snapshot())
        conflict = copy.deepcopy(action)
        conflict["proposal"]["score"] = 0.7
        rejects("same decision rejects altered raw request", lambda: adapter.ingest(conflict, AT))
        bad_policy = copy.deepcopy(action)
        bad_policy["policy"]["alert_capacity"] = 99
        rejects("raw request cannot replace trusted policy", lambda: adapter.ingest(bad_policy, AT))
        bad_model = copy.deepcopy(action)
        bad_model["proposal"]["model_hash"] = "b" * 64
        rejects("model ID does not permit an unrelated hash", lambda: adapter.ingest(bad_model, AT))
        malformed = copy.deepcopy(action)
        malformed["evidence"]["items"][0]["requested_for_use"] = "true"
        rejects("use request must be boolean", lambda: adapter.ingest(malformed, AT))

        for target, request in (("after_reservation", action), ("after_release", unsupported), ("before_issue_commit", action)):
            ad = Adapter(root / (target + ".sqlite"), policy)
            ad.ingest(request, AT)
            try:
                ad.issue(request["proposal"]["decision_id"], AT, interrupt(target))
            except SimulatedInterruption:
                pass
            else:
                raise AssertionError("checkpoint not reached: " + target)
            state = ad.snapshot()
            check(target + " rollback leaves durable received request only", len(state["requests"]) == 1 and state["requests"][0]["state"] == "received" and not state["permits"] and not state["reservations"] and state["reserved"] == 0)
            check(target + " recovery issues from durable request", ad.issue(request["proposal"]["decision_id"], AT) is not None)

        post = Adapter(root / "after_commit.sqlite", policy)
        post.ingest(action, AT)
        try:
            post.issue(action["proposal"]["decision_id"], AT, interrupt("after_issue_commit"))
        except SimulatedInterruption:
            pass
        durable = post.get_permit(action["proposal"]["decision_id"])
        check("postcommit interruption retains full permit", durable is not None and post.snapshot()["reserved"] == 1)
        post.cleanup("2026-09-12T12:00:11Z")
        check("early cleanup retains unarmed issued permit", post.issue(action["proposal"]["decision_id"], AT) == durable)
        post.cleanup(LATER)
        check("exact expiry cancels and releases unarmed permit", post.get_request(action["proposal"]["decision_id"])["state"] == "cancelled" and post.snapshot()["reserved"] == 0)
        check("cancelled issuance cannot restart", post.issue(action["proposal"]["decision_id"], LATER) is None)
        rejects("cancelled permit cannot arm even at earlier injected clock", lambda: post.arm(durable, AT))
        post.cleanup(LATER)
        check("cleanup is idempotent", post.snapshot()["reserved"] == 0)

        pending = Adapter(root / "pending.sqlite", policy)
        pending.ingest(action, AT)
        pending.cleanup("2026-09-12T12:01:09Z")
        check("raw request retained before lease boundary", pending.get_request(action["proposal"]["decision_id"])["state"] == "received")
        pending.cleanup("2026-09-12T12:01:10Z")
        check("raw request cancels at lease boundary", pending.get_request(action["proposal"]["decision_id"])["state"] == "cancelled")

        armed = Adapter(root / "armed.sqlite", policy)
        armed.ingest(action, AT)
        permit = armed.issue(action["proposal"]["decision_id"], AT)
        job = armed.arm(permit, AT)
        armed.cleanup(LATER)
        armed.revoke()
        check("expiry cleanup and revoke retain armed hold", armed.snapshot()["reserved"] == 1 and armed.arm(permit, LATER) == job)
        payload = json.loads(job["payload_json"])
        ack = dict(idempotency_key=job["idempotency_key"], payload_hash=digest(payload), payload=payload,
                   effect_id=1, committed_at="2026-09-12T12:00:11Z")
        receipt = armed.finish(permit["permit_id"], ack, LATER)
        check("late matching ACK commits held capacity", armed.snapshot()["committed"] == 1 and armed.snapshot()["reserved"] == 0)
        check("completed finish returns identical stored receipt", receipt == armed.finish(permit["permit_id"], ack, LATER))

        concurrent = Adapter(root / "concurrent.sqlite", policy)
        requests = [renumber(action, "distinct-" + str(i)) for i in range(8)]
        for request in requests:
            concurrent.ingest(request, AT)
        with ThreadPoolExecutor(max_workers=8) as pool:
            permits = list(pool.map(lambda req: concurrent.issue(req["proposal"]["decision_id"], AT), requests))
        check("eight distinct issuers cannot exceed two-unit alert budget", sum(p["route"] == "alert" for p in permits) == 2 and sum(p["route"] == "no_action" for p in permits) == 6 and concurrent.snapshot()["reserved"] == 2)

        for field, value in (("source", "untrusted"), ("schema_version", "unapproved"),
                             ("available_at", "2026-09-12T12:00:06Z"), ("observed_at", "2026-09-12T11:58:00Z"),
                             ("requested_for_use", False)):
            req = renumber(action, "gate-" + field)
            req["evidence"]["items"][0][field] = value
            ad = Adapter(root / ("gate-" + field + ".sqlite"), policy)
            ad.ingest(req, AT)
            p = ad.issue(req["proposal"]["decision_id"], AT)
            check("metadata gate rejects use for " + field, p["route"] == "abstain" and not p["used_evidence_ids"])

    report = {"kind": "development_unit_checks_only", "n_passed": len(checks), "checks": checks,
              "formal_denominator": False, "uses_real_HTTP": False,
              "precommit_injection": "exception rollback; formal process termination is separate"}
    (HERE / "ordinary_e2e_dev_checks.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
