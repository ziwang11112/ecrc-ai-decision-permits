"""Independent read-only audit of completed HTTP/crash suite artifacts.

Does not import any runtime, adapter, transport, fixture or service code.
Checks actual client/sink SQLite rows and recorded intermediate snapshots.
The original ECRC base chain is checked structurally and cryptographically;
new delivery metadata and durable-grant time semantics are audited separately.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import csv
import hashlib
import json
import sqlite3

HERE = Path(__file__).resolve().parent
PAYLOAD_FIELDS = ("decision_id", "route", "permitted_claim_ids", "used_evidence_ids")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def connect_readonly(path):
    # Do not use immutable=1: a valid completed database may still have WAL.
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def query(conn, text):
    return [dict(row) for row in conn.execute(text)]


class Audit:
    def __init__(self):
        self.findings = []
        self.cases = []
        self.input_hashes = {}
        self.check_count = 0

    def check(self, condition, code, context, detail=""):
        self.check_count += 1
        if not condition:
            self.findings.append(dict(code=code, context=context, detail=detail))

    def capacity(self, state, context):
        rows = state["capacity_rows"]
        self.check(len({tuple(r[k] for k in ("policy_id", "policy_revision", "scope_key", "resource")) for r in rows}) == len(rows), "duplicate_capacity_key", context)
        for pos, row in enumerate(rows):
            for key in ("reserved", "committed", "capacity_limit"):
                self.check(type(row[key]) is int and row[key] >= 0, "invalid_individual_capacity_value", context, f"row {pos}, {key}={row[key]}")
            self.check(row["reserved"] + row["committed"] <= row["capacity_limit"], "per_key_capacity_excess", context, f"row {pos}")
        for key in ("reserved", "committed", "capacity_limit"):
            self.check(sum(r[key] for r in rows) == state[key], "capacity_aggregate_disagrees", context, key)
        self.check(state["n_jobs"] == len(state["jobs"]), "job_count_disagrees", context)
        self.check(state["n_armed"] == sum(j["state"] == "armed" for j in state["jobs"]), "armed_count_disagrees", context)
        self.check(state["n_receipted"] == sum(j["state"] == "receipted" for j in state["jobs"]), "receipted_count_disagrees", context)

    def jobs_and_effects(self, jobs, effects, permits, context, completed):
        lookup = {r["idempotency_key"]: r for r in effects}
        self.check(len(lookup) == len(effects), "duplicate_service_key", context)
        self.check(len({r["effect_id"] for r in effects}) == len(effects), "duplicate_service_effect_id", context)
        self.check(len({j["permit_id"] for j in jobs}) == len(jobs), "duplicate_client_intent", context)
        self.check(set(lookup) <= {j["idempotency_key"] for j in jobs}, "effect_without_durable_intent", context)
        receipts = []
        for job in jobs:
            tag = context + ":" + job["permit_id"]
            permit = permits[job["permit_id"]]
            self.check(job["idempotency_key"] == permit["permit_id"], "unstable_operation_key", tag)
            self.check(job["permit_hash"] == digest(permit), "intent_permit_hash_mismatch", tag)
            expected_payload = {key: permit[key] for key in PAYLOAD_FIELDS}
            payload = json.loads(job["payload_json"])
            self.check(payload == expected_payload and digest(payload) == job["payload_hash"], "intent_payload_not_permit_projection", tag)
            self.check(permit["route"] in ("alert", "review"), "nonaction_intent", tag)
            self.check(instant(permit["issued_at"]) <= instant(job["armed_at"]) < instant(permit["expires_at"]), "authorization_outside_permit_interval", tag)
            actual = lookup.get(job["idempotency_key"])
            if actual is not None:
                self.check(type(actual["effect_id"]) is int and actual["effect_id"] > 0, "invalid_service_id", tag)
                self.check(actual["payload_hash"] == job["payload_hash"] == digest(json.loads(actual["payload_json"])), "sink_payload_hash_mismatch", tag)
                self.check(json.loads(actual["payload_json"]) == expected_payload, "sink_payload_not_authorized_projection", tag)
            if job["state"] == "armed":
                self.check(job["receipt_json"] is None and job["ack_json"] is None, "armed_has_partial_completion", tag)
                self.check(not completed, "unresolved_final_intent", tag)
                continue
            self.check(job["state"] == "receipted", "unknown_intent_state", tag)
            self.check(actual is not None, "receipt_without_service_effect", tag)
            if actual is None:
                continue
            ack = json.loads(job["ack_json"])
            receipt = json.loads(job["receipt_json"])
            receipts.append(receipt)
            self.check(ack["idempotency_key"] == job["idempotency_key"] and ack["effect_id"] == actual["effect_id"], "ack_identity_mismatch", tag)
            self.check(ack["payload_hash"] == actual["payload_hash"] and digest(ack["payload"]) == actual["payload_hash"], "ack_payload_mismatch", tag)
            self.check(instant(ack["committed_at"]) == instant(actual["committed_at"]), "ack_service_time_mismatch", tag)
            self.check(receipt["permit_id"] == permit["permit_id"] and receipt["permit_hash"] == digest(permit), "receipt_permit_binding_mismatch", tag)
            self.check(receipt["service_effect_id"] == actual["effect_id"] and str(receipt["side_effect_id"]) == str(actual["effect_id"]), "receipt_service_id_mismatch", tag)
            self.check(receipt["route"] == permit["route"] and receipt["reservation_id"] == permit["reservation_id"] and receipt["execution_status"] == "executed", "receipt_route_reservation_status_mismatch", tag)
            auth = receipt.get("authorized_at", receipt.get("armed_at"))
            service_time = receipt.get("service_committed_at", receipt.get("committed_at"))
            self.check(instant(auth) == instant(job["armed_at"]), "receipt_authorization_time_mismatch", tag)
            self.check(instant(service_time) == instant(actual["committed_at"]) == instant(receipt["executed_at"]), "receipt_effect_time_mismatch", tag)
            self.check(instant(receipt["reconciled_at"]) >= instant(actual["committed_at"]), "receipt_reconciled_before_effect", tag)
            self.check("reconciliation_policy_clock" in receipt, "logical_policy_clock_not_recorded", tag)
            # Do NOT assert executed_at < permit.expires_at: arm is the new
            # irrevocable grant boundary, and later reconciliation is allowed.
            if "service_ack" in receipt:
                self.check(receipt["service_ack"] == ack, "ordinary_embedded_ack_mismatch", tag)
            if "payload_hash" in receipt:
                self.check(receipt["payload_hash"] == actual["payload_hash"], "receipt_payload_hash_mismatch", tag)
        self.check(len({r["receipt_id"] for r in receipts}) == len(receipts), "duplicate_receipt_id", context)
        self.check(len({r["permit_id"] for r in receipts}) == len(receipts), "multiple_receipts_for_permit", context)
        return receipts

    def base_chain(self, rows, jobs, permits, context):
        prior = "0" * 64
        outbox = {j["permit_id"]: j for j in jobs}
        for index, row in enumerate(rows, 1):
            receipt = json.loads(row["receipt_json"])
            self.check(row["sequence_no"] == receipt["sequence_no"] == index, "base_chain_sequence", context)
            self.check(row["previous_receipt_hash"] == receipt["previous_receipt_hash"] == prior, "base_chain_link", context)
            self.check(row["receipt_hash"] == digest(receipt), "base_chain_content_hash", context)
            self.check(row["permit_id"] == receipt["permit_id"] and row["receipt_id"] == receipt["receipt_id"], "base_chain_row_binding", context)
            self.check(receipt["permit_hash"] == digest(permits[row["permit_id"]]), "base_chain_permit_binding", context)
            extended = json.loads(outbox[row["permit_id"]]["receipt_json"])
            self.check(all(extended[k] == v for k, v in receipt.items()), "extended_receipt_differs_from_base_chain", context)
            prior = row["receipt_hash"]
        return prior

    def audit_case(self, folder, relative):
        before = len(self.findings)
        trace = read_json(folder / "trace.json")
        fixture = read_json(folder / "fixture/fixture.json")
        permits = {p["permit_id"]: p for p in fixture["permits"]}
        for row in fixture["issued_permits"]:
            self.check(row["permit_hash"] == digest(permits[row["permit_id"]]), "fixture_registered_hash_mismatch", relative)
        arm = trace.get("arm", "ecrc" if "-ecrc-" in folder.name else "ordinary")
        boundary = relative.startswith("boundary/")
        final_state = trace["state"] if "state" in trace else trace["final"]
        final_effects = trace["sink"] if "sink" in trace else trace["effects"]
        completed = not boundary or trace["expected_accept"]
        self.capacity(final_state, relative + ":final_trace")
        self.jobs_and_effects(final_state["jobs"], final_effects, permits, relative + ":final_trace", completed)
        if completed:
            self.check(final_state["reserved"] == 0 and final_state["n_armed"] == 0, "completed_case_retains_uncertain_capacity", relative)
            self.check(len(final_effects) == final_state["n_receipts"] == final_state["n_receipted"] == final_state["committed"], "completed_counts_disagree", relative)
        if "intermediate" in trace:
            self.capacity(trace["intermediate"], relative + ":recorded_intermediate")
            self.jobs_and_effects(trace["intermediate"]["jobs"], trace["intermediate_effects"], permits, relative + ":recorded_intermediate", False)
        if boundary and not trace["expected_accept"]:
            self.check(not final_effects and not final_state["jobs"] and final_state["n_receipts"] == 0, "rejected_boundary_has_effect_or_intent", relative)
        # Independently read final client and sink rows; do not call snapshot().
        client = connect_readonly(folder / "client.sqlite")
        sink = connect_readonly(folder / "sink.sqlite")
        try:
            actual_effects = query(sink, "SELECT * FROM effects ORDER BY effect_id")
            self.check(actual_effects == final_effects, "trace_sink_differs_from_database", relative)
            if arm == "ecrc":
                jobs = query(client, "SELECT * FROM delivery_outbox ORDER BY permit_id")
                capacity = query(client, "SELECT * FROM capacity_state ORDER BY policy_id,policy_revision,scope_key,resource")
                holds = query(client, "SELECT * FROM reservations")
                base = query(client, "SELECT * FROM receipt_log ORDER BY sequence_no")
                n_receipts = len(base)
                self.base_chain(base, jobs, permits, relative)
            else:
                jobs = query(client, "SELECT * FROM delivery ORDER BY permit_id")
                raw = query(client, "SELECT * FROM budgets ORDER BY policy_id,policy_revision,scope_key,resource")
                capacity = [{**{k: r[k] for k in ("policy_id", "policy_revision", "scope_key", "resource", "state_revision")}, "reserved": r["held"], "committed": r["spent"], "capacity_limit": r["ceiling"]} for r in raw]
                holds = []
                for row in query(client, "SELECT * FROM holds"):
                    document = json.loads(row["document"])
                    self.check(document["status"] == row["status"], "hold_document_status_disagrees", relative)
                    holds.append(document)
                stored_receipts = query(client, "SELECT * FROM receipts ORDER BY permit_id")
                n_receipts = len(stored_receipts)
                lookup = {j["permit_id"]: j for j in jobs}
                for r in stored_receipts:
                    self.check(json.loads(r["document"]) == json.loads(lookup[r["permit_id"]]["receipt_json"]), "ordinary_receipt_table_differs_from_outbox", relative)
                    self.check(r["effect_id"] == json.loads(r["document"])["service_effect_id"], "ordinary_receipt_table_effect_id", relative)
            self.check(jobs == sorted(final_state["jobs"], key=lambda r: r["permit_id"]), "trace_jobs_differ_from_database", relative)
            self.check(capacity == sorted(final_state["capacity_rows"], key=lambda r: tuple(r[k] for k in ("policy_id", "policy_revision", "scope_key", "resource"))), "trace_capacity_differs_from_database", relative)
            self.check(n_receipts == final_state["n_receipts"], "trace_receipt_count_differs_from_database", relative)
            self.jobs_and_effects(jobs, actual_effects, permits, relative + ":independent_database", completed)
            for row in capacity:
                applicable = [r for r in holds if all(r[k] == row[k] for k in ("policy_id", "policy_revision", "scope_key", "resource"))]
                self.check(sum(r["amount"] for r in applicable if r["status"] == "reserved") == row["reserved"], "held_reservations_disagree_with_capacity", relative)
                self.check(sum(r["amount"] for r in applicable if r["status"] == "committed") == row["committed"], "committed_reservations_disagree_with_capacity", relative)
            job_lookup = {j["permit_id"]: j for j in jobs}
            for hold in holds:
                if hold["permit_id"] in job_lookup:
                    job = job_lookup[hold["permit_id"]]
                    wanted = "committed" if job["state"] == "receipted" else "reserved"
                    self.check(hold["status"] == wanted and hold["permit_hash"] == job["permit_hash"], "hold_state_or_binding_disagrees_with_intent", relative)
        finally:
            client.close(); sink.close()
        for crash in trace.get("crashes", []):
            self.check(type(crash["pid"]) is int and crash["pid"] > 0 and crash["exit_code"] != 0, "crash_not_recorded_as_terminated", relative)
        self.cases.append({"case": relative, "arm": arm, "effects": len(final_effects), "receipts": final_state["n_receipts"],
                           "reserved": final_state["reserved"], "committed": final_state["committed"],
                           "n_jobs": final_state["n_jobs"], "findings": len(self.findings) - before,
                           "intermediate_scope": "recorded snapshot checked; no independent historical DB snapshot" if "intermediate" in trace else "not applicable"})

    def run(self, directory):
        directory = directory.resolve()
        manifest = read_json(directory / "manifest.json")
        self.check(not (directory / "FAILURE.json").exists(), "suite_failure_artifact_exists", str(directory))
        for name, expected in manifest["outputs"].items():
            self.check(sha(directory / name) == expected, "top_level_output_manifest_hash", name)
        for name, expected in manifest["inputs"].items():
            self.check(sha(HERE / name) == expected, "runtime_source_changed_since_suite", name)
        traces = sorted(p for category in ("recovery", "boundary", "performance") for p in (directory / category).glob("*/trace.json"))
        expected_n = manifest["recovery_runs"] + manifest["boundary_cases"] + manifest["performance_runs"]
        self.check(len(traces) == expected_n, "trace_inventory_count", str(directory), f"{len(traces)} vs {expected_n}")
        for path in traces:
            folder = path.parent
            for filename in ("trace.json", "client.sqlite", "sink.sqlite", "fixture/fixture.json"):
                file = folder / filename
                self.input_hashes[str(file.relative_to(directory)).replace("\\", "/")] = sha(file)
            relative = folder.relative_to(directory).as_posix()
            try:
                self.audit_case(folder, relative)
            except Exception as exc:
                self.findings.append({"code": "audit_case_exception", "context": relative, "detail": repr(exc)})
        # Read-only assurance for persisted principal input artifacts.
        self.check(all(sha(directory / name) == expected for name, expected in self.input_hashes.items()), "audited_input_changed_during_review", str(directory))
        return {"suite": str(directory), "passed": not self.findings, "n_case_traces": len(traces), "n_completed_case_audits": len(self.cases),
                "n_checks": self.check_count, "n_findings": len(self.findings), "cases": self.cases, "findings": self.findings,
                "input_hashes": self.input_hashes, "auditor_sha256": sha(Path(__file__)),
                "scope": {"final_state": "independent read-only client and sink SQLite queries",
                          "intermediate_state": "per-row arithmetic and payload/receipt consistency of recorded snapshots; no separate historical DB copies",
                          "base_ECRC_chain": "sequence, predecessor, content hash and base-field consistency only; original expiry rule not applied to new durable grants",
                          "extended_metadata": "cross-checked with actual sink/job; not claimed to be covered by the original base receipt hash",
                          "time": "actual sink commit and local reconciliation times separate from injected authorization/reconciliation policy clocks",
                          "process_crashes": "recorded PID/nonzero exit checked; no new process failures injected by auditor"}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args()
    dest = args.report_dir or HERE / ("independent_trace_audit_" + args.suite.name)
    dest.mkdir(parents=True, exist_ok=True)
    report = Audit().run(args.suite)
    (dest / "audit_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["cases"]:
        with (dest / "case_audit.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(report["cases"][0])); writer.writeheader(); writer.writerows(report["cases"])
    print(json.dumps({k: report[k] for k in ("passed", "n_case_traces", "n_completed_case_audits", "n_checks", "n_findings")}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
