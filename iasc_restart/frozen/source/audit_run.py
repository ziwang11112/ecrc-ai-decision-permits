"""Read-only, implementation-independent audit of a bounded synthetic run.

This module imports neither client nor service implementation.  CASE describes
the public workload; SQLite tables provide effect and accountability facts.
An external-capability failure is deliberately distinct from a broken run.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _db_files(path: Path) -> dict:
    # WAL is authoritative when present. SHM is a transient reader index.
    return {candidate.name: {"sha256": _file_hash(candidate),
                             "bytes": candidate.stat().st_size}
            for candidate in (path, Path(str(path) + "-wal"))
            if candidate.is_file()}


def _read_db(path: Path) -> tuple[dict, dict]:
    before = _db_files(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        schema = [dict(row) for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
        tables = {}
        for item in schema:
            if item["type"] == "table":
                name = item["name"]
                quoted = '"' + name.replace('"', '""') + '"'
                tables[name] = sorted((dict(row) for row in connection.execute(
                    "SELECT * FROM " + quoted)), key=_json)
        connection.rollback()
    finally:
        connection.close()
    after = _db_files(path)
    return tables, {
        "path": str(path.resolve()), "files_before": before, "files_after": after,
        "file_bytes_unchanged_while_reading": before == after,
        "integrity_check": integrity, "schema_sha256": _hash(schema),
        "all_tables_sha256": _hash(tables),
        "table_rows": {name: len(rows) for name, rows in tables.items()},
        "hash_scope": "Full main database and WAL bytes, plus canonical full SQL table content; transient SHM excluded.",
    }


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp without timezone")
    return parsed.astimezone(timezone.utc)


def _decode(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def _binding_errors(ack: dict, effect: dict) -> list[str]:
    errors = []
    for field in ("effect_id", "idempotency_key", "payload_hash", "payload"):
        if ack.get(field) != effect.get(field):
            errors.append("ack_" + field + "_mismatch")
    if "committed_at" in ack and _time(ack["committed_at"]) != _time(effect["committed_at"]):
        errors.append("ack_committed_at_mismatch")
    return errors


def _audit_ecrc(tables: dict, effects: list[dict], limit: int) -> dict:
    failures = []
    required = ("active_policies", "requests", "issued_permits", "delivery_outbox",
                "reservations", "capacity_state", "executions", "receipt_log")
    for table in required:
        if table not in tables:
            failures.append("missing_table:" + table)
    if failures:
        return {"applicable": True, "passed": False, "failures": failures}
    issued = {r["permit_id"]: r for r in tables["issued_permits"]}
    requests = {r["decision_id"]: r for r in tables["requests"]}
    reservations = {r["reservation_id"]: r for r in tables["reservations"]}
    outbox = {r["permit_id"]: r for r in tables["delivery_outbox"]}
    by_key = {r["idempotency_key"]: r for r in tables["delivery_outbox"]}
    by_effect_key = {r["idempotency_key"]: r for r in effects}
    executions = {r["permit_id"]: r for r in tables["executions"]}
    receipt_rows = {r["permit_id"]: r for r in tables["receipt_log"]}
    policies = {r["policy_id"]: r for r in tables["active_policies"]}
    if len(policies) != 1:
        failures.append("expected_one_fixed_policy_for_run")
    for policy_id, policy in policies.items():
        if _hash(_decode(policy["manifest_json"])) != policy["policy_hash"]:
            failures.append("registered_policy_hash_mismatch:" + policy_id)
    for decision, request in requests.items():
        if _hash(_decode(request["request_json"])) != request["request_hash"]:
            failures.append("request_content_hash_mismatch:" + decision)

    for pid, job in outbox.items():
        prefix = "outbox:" + pid + ":"
        permit = _decode(job["permit_json"])
        payload = _decode(job["payload_json"])
        record = issued.get(pid)
        reservation = reservations.get(permit.get("reservation_id"))
        request = requests.get(permit["decision_id"])
        if not record or record["permit_hash"] != _hash(permit):
            failures.append(prefix + "not_registered_with_exact_permit_hash")
        elif any(record.get(key) != permit.get(key) for key in
                 ("permit_id", "decision_id", "policy_id", "policy_revision", "policy_hash",
                  "request_hash", "reservation_id", "route", "reason_code", "issued_at")):
            failures.append(prefix + "registry_fields_mismatch")
        policy = policies.get(permit["policy_id"])
        if not policy or (policy["revision"], policy["policy_hash"]) != (permit["policy_revision"], permit["policy_hash"]):
            failures.append(prefix + "registered_policy_binding_mismatch")
        if job["permit_hash"] != _hash(permit) or pid != permit["permit_id"]:
            failures.append(prefix + "permit_binding_mismatch")
        if not request or _decode(request["permit_json"]) != permit:
            failures.append(prefix + "request_permit_binding_mismatch")
        if request and request["state"] == "cancelled":
            failures.append(prefix + "armed_request_cancelled")
        expected_payload = {key: permit[key] for key in
                            ("decision_id", "route", "permitted_claim_ids", "used_evidence_ids")}
        if payload != expected_payload or _hash(payload) != job["payload_hash"]:
            failures.append(prefix + "payload_binding_mismatch")
        if job["idempotency_key"] != pid:
            failures.append(prefix + "key_not_original_permit_id")
        if not (_time(permit["issued_at"]) <= _time(job["armed_at"]) < _time(permit["expires_at"])):
            failures.append(prefix + "new_arm_outside_permit_time")
        if permit["route"] not in ("alert", "review"):
            failures.append(prefix + "nonaction_armed")
        if not reservation:
            failures.append(prefix + "reservation_missing")
        else:
            for key, value in {"permit_id": pid, "permit_hash": _hash(permit),
                               "policy_id": permit["policy_id"],
                               "policy_revision": permit["policy_revision"],
                               "policy_hash": permit["policy_hash"],
                               "request_hash": permit["request_hash"],
                               "resource": permit["route"]}.items():
                if reservation.get(key) != value:
                    failures.append(prefix + "reservation_" + key + "_mismatch")
            if reservation["status"] not in ("reserved", "committed"):
                failures.append(prefix + "armed_responsibility_released")
            expected_status = "committed" if job["state"] == "receipted" else "reserved"
            if reservation["status"] != expected_status:
                failures.append(prefix + "completion_reservation_state_mismatch")
        if job["state"] not in ("armed", "receipted"):
            failures.append(prefix + "unknown_outbox_state")
        if job["state"] == "receipted":
            effect = by_effect_key.get(job["idempotency_key"])
            ack = _decode(job["ack_json"])
            delivery_receipt = _decode(job["receipt_json"])
            receipt_row = receipt_rows.get(pid)
            execution = executions.get(pid)
            if effect is None or ack is None:
                failures.append(prefix + "receipt_without_real_sink_effect")
            else:
                failures.extend(prefix + issue for issue in _binding_errors(ack, effect))
            if not receipt_row or not execution or not delivery_receipt:
                failures.append(prefix + "completion_records_incomplete")
            else:
                receipt = _decode(receipt_row["receipt_json"])
                if any(delivery_receipt.get(key) != value for key, value in receipt.items()):
                    failures.append(prefix + "delivery_receipt_core_mismatch")
                if receipt["permit_hash"] != _hash(permit) or receipt["reservation_id"] != permit["reservation_id"]:
                    failures.append(prefix + "receipt_permit_binding_mismatch")
                if effect and (receipt["side_effect_id"] != str(effect["effect_id"]) or
                               _time(receipt["executed_at"]) != _time(effect["committed_at"])):
                    failures.append(prefix + "receipt_effect_binding_mismatch")
                if execution["receipt_id"] != receipt["receipt_id"] or execution["permit_hash"] != _hash(permit):
                    failures.append(prefix + "execution_binding_mismatch")
                if effect and delivery_receipt.get("service_effect_id") != effect["effect_id"]:
                    failures.append(prefix + "delivery_effect_id_mismatch")
        elif job["ack_json"] is not None or job["receipt_json"] is not None or pid in executions or pid in receipt_rows:
            failures.append(prefix + "armed_state_has_completion_record")

    for effect in effects:
        job = by_key.get(effect["idempotency_key"])
        if not job:
            failures.append("effect:" + str(effect["effect_id"]) + ":no_registered_armed_job")
        elif job["payload_hash"] != effect["payload_hash"] or _decode(job["payload_json"]) != effect["payload"]:
            failures.append("effect:" + str(effect["effect_id"]) + ":armed_payload_mismatch")
    for pid in set(executions) | set(receipt_rows):
        if pid not in outbox:
            failures.append("completion_without_outbox:" + pid)

    previous = "0" * 64
    for sequence, row in enumerate(sorted(tables["receipt_log"], key=lambda r: r["sequence_no"]), 1):
        receipt = _decode(row["receipt_json"])
        if row["sequence_no"] != sequence or receipt["sequence_no"] != sequence:
            failures.append("receipt_sequence_gap:" + str(sequence))
        if row["previous_receipt_hash"] != previous or receipt["previous_receipt_hash"] != previous:
            failures.append("receipt_chain_mismatch:" + str(sequence))
        if row["receipt_hash"] != _hash(receipt):
            failures.append("receipt_content_hash_mismatch:" + str(sequence))
        previous = row["receipt_hash"]

    key_fields = ("policy_id", "policy_revision", "scope_key", "resource")
    capacity_keys = set()
    for row in tables["capacity_state"]:
        key = tuple(row[field] for field in key_fields)
        capacity_keys.add(key)
        matching = [r for r in reservations.values() if tuple(r[f] for f in key_fields) == key]
        totals = {status: sum(r["amount"] for r in matching if r["status"] == status)
                  for status in ("reserved", "committed")}
        if totals["reserved"] != row["reserved"] or totals["committed"] != row["committed"]:
            failures.append("capacity_aggregate_mismatch:" + str(key))
        if min(row["reserved"], row["committed"]) < 0 or row["reserved"] + row["committed"] > row["capacity_limit"]:
            failures.append("capacity_bounds_violation:" + str(key))
        if row["capacity_limit"] > 0 and row["capacity_limit"] != limit:
            failures.append("configured_limit_differs_from_external_limit:" + str(key))
    active_keys = {tuple(r[field] for field in key_fields) for r in reservations.values()}
    if len(active_keys) > 1:
        failures.append("multiple_budget_keys_in_single_scope_run")
    if not active_keys.issubset(capacity_keys):
        failures.append("reservation_without_capacity_row")
    return {"applicable": True, "passed": not failures, "failures": failures,
            "outbox_count": len(outbox), "receipts": len(receipt_rows),
            "reserved": sum(r["reserved"] for r in tables["capacity_state"]),
            "committed": sum(r["committed"] for r in tables["capacity_state"]),
            "capacity_rows": tables["capacity_state"],
            "reservation_status_counts": dict(Counter(r["status"] for r in reservations.values())),
            "request_state_counts": dict(Counter(r["state"] for r in requests.values())),
            "scope": "Final SQL bindings, responsibility and real sink receipts; historical timing requires preserved event trace."}


def _audit_durable(tables: dict, effects: list[dict], limit: int) -> dict:
    failures = []
    for table in ("direct_scopes", "direct_operations"):
        if table not in tables:
            failures.append("missing_table:" + table)
    if failures:
        return {"applicable": True, "passed": False, "failures": failures}
    scopes = {row["scope"]: row["action_limit"] for row in tables["direct_scopes"]}
    operations = tables["direct_operations"]
    if len(scopes) != 1:
        failures.append("expected_one_persistent_budget_scope")
    for scope, action_limit in scopes.items():
        if action_limit != limit:
            failures.append("configured_limit_differs_from_external_limit:" + scope)
        if sum(row["scope"] == scope for row in operations) > action_limit:
            failures.append("durable_admission_count_over_limit:" + scope)
    by_key = {}
    by_effect_key = {row["idempotency_key"]: row for row in effects}
    acknowledged = 0
    unknown_effects = []
    for row in operations:
        key = row["idempotency_key"]
        prefix = "operation:" + key + ":"
        if key in by_key:
            failures.append(prefix + "same_key_in_multiple_scopes")
        by_key[key] = row
        if row["scope"] not in scopes:
            failures.append(prefix + "scope_missing")
        descriptor = _decode(row["descriptor_json"])
        expected = {"idempotency_key": "direct:" + row["job_hash"],
                    "payload": {"job_hash": row["job_hash"]}}
        if descriptor != expected or key != expected["idempotency_key"]:
            failures.append(prefix + "original_descriptor_binding_mismatch")
        if row["payload_hash"] != _hash(descriptor["payload"]):
            failures.append(prefix + "payload_hash_mismatch")
        effect = by_effect_key.get(key)
        if effect and (effect["payload"] != descriptor["payload"] or
                       effect["payload_hash"] != row["payload_hash"]):
            failures.append(prefix + "effect_payload_binding_mismatch")
        if row["ack_json"] is not None:
            acknowledged += 1
            ack = _decode(row["ack_json"])
            if effect is None:
                failures.append(prefix + "ack_without_real_sink_effect")
            else:
                failures.extend(prefix + issue for issue in _binding_errors(ack, effect))
        elif effect:
            unknown_effects.append(effect["effect_id"])
    for effect in effects:
        if effect["idempotency_key"] not in by_key:
            failures.append("effect_without_durable_operation:" + str(effect["effect_id"]))
    return {"applicable": True, "passed": not failures, "failures": failures,
            "persisted_scopes": scopes, "cumulative_registered_count": len(operations),
            "acknowledged_count": acknowledged,
            "unacknowledged_count": len(operations) - acknowledged,
            "sink_effects_still_unacknowledged": unknown_effects,
            "scope": "Every registered distinct operation counts permanently, including acknowledged and unknown outcomes; final bindings checked directly in SQLite."}


def _audit_transport(folder: Path, effects: list[dict], case: dict) -> dict:
    path = folder / "PROXY.jsonl"
    if not path.is_file():
        return {"applicable": False, "passed": None,
                "reason": "PROXY.jsonl absent; final committed effects alone do not establish replay exercise."}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    actual = {effect["idempotency_key"]: effect for effect in effects}
    post_counts = Counter()
    identities = {}
    failures = []
    withheld = 0
    created = Counter()
    b_events = []
    for index, event in enumerate(rows):
        if event.get("method") not in ("POST", "GET"):
            continue
        response = event.get("upstream_response", {})
        if event.get("upstream_code") not in (200, 201) or "effect_id" not in response:
            continue
        key = event["key"]
        effect = actual.get(key)
        if effect is None:
            failures.append("transport_effect_missing_from_database:" + str(index))
            continue
        failures.extend("transport:" + str(index) + ":" + issue
                        for issue in _binding_errors(response, effect))
        identities.setdefault(key, set()).add(response["effect_id"])
        if event.get("method") == "POST":
            post_counts[key] += 1
            descriptor = event.get("request")
            if descriptor != {"idempotency_key": key, "payload": effect["payload"]}:
                failures.append("transport_request_descriptor_mismatch:" + str(index))
            if effect.get("logical_job") == "B":
                b_events.append(event)
            if event.get("withheld"):
                withheld += 1
            if response.get("created") is True:
                created[key] += 1
            if "request_payload" in event and event["request_payload"] != effect["payload"]:
                failures.append("transport_request_payload_mismatch:" + str(index))
    for key, found in identities.items():
        if len(found) != 1:
            failures.append("replay_changed_effect_identity:" + key)
    for key, count in created.items():
        if count > 1:
            failures.append("same_key_reported_created_more_than_once:" + key)
    b_replay = None
    if case["condition"] == "mixed":
        first = b_events[0] if b_events else None
        last = b_events[-1] if len(b_events) > 1 else None
        b_replay = bool(first and last and first["withheld"] is True and
                        first["upstream_code"] == 201 and
                        first["upstream_response"].get("created") is True and
                        last["withheld"] is False and last["upstream_code"] == 200 and
                        last["upstream_response"].get("created") is False and
                        first["key"] == last["key"] and
                        first["upstream_response"]["effect_id"] == last["upstream_response"]["effect_id"])
        if not b_replay:
            failures.append("declared_B_loss_and_cached_recovery_not_observed")
    return {"applicable": True, "passed": not failures, "failures": failures,
            "source_sha256": _file_hash(path), "transport_record_count": len(rows),
            "successful_upstream_posts": sum(post_counts.values()),
            "withheld_successful_post_responses": withheld,
            "post_counts_by_key": dict(post_counts),
            "same_key_additional_post_count": sum(max(0, n - 1) for n in post_counts.values()),
            "B_withheld_creation_and_same_effect_cached_recovery": b_replay,
            "effect_ids_observed_by_key": {key: sorted(value) for key, value in identities.items()},
            "scope": "Actual proxy observations of committed/cached responses checked against sink; does not measure pre-commit CPU or all crash schedules."}


def _audit_trace(folder: Path, trace: dict, case: dict, effects: list[dict], transport: dict) -> dict:
    failures = []
    events = trace.get("events", [])
    workers = [(i, event) for i, event in enumerate(events)
               if event.get("event") == "ready" and event.get("arm") == case["arm"]]
    expected_worker_count = 2 if case["condition"] == "mixed" else 1
    if len(workers) != expected_worker_count:
        failures.append("wrong_number_of_worker_process_ready_records")
    actual = {effect["idempotency_key"]: effect for effect in effects}
    dispatched = []
    for index, event in enumerate(events):
        if event.get("op") not in ("send", "recover") or event.get("descriptor") is None:
            continue
        dispatched.append((index, event))
        descriptor = event["descriptor"]
        effect = actual.get(descriptor["idempotency_key"])
        if not effect or descriptor.get("payload") != effect["payload"]:
            failures.append("worker_dispatch_not_bound_to_real_effect:" + str(index))
        if event.get("status") == "acknowledged":
            if effect:
                failures.extend("worker_ack:" + str(index) + ":" + issue
                                for issue in _binding_errors(event.get("ack", {}), effect))
        elif event.get("status") != "transport_unknown":
            failures.append("unexpected_dispatched_worker_status:" + str(index))
    if transport.get("applicable") and len(dispatched) != transport["successful_upstream_posts"]:
        failures.append("worker_and_proxy_post_counts_differ")
    killed = [event for event in events if event.get("event") == "client_killed_while_B_unknown"]
    restart_valid = None
    if case["condition"] == "mixed":
        kill_records = [(i, event) for i, event in enumerate(events)
                        if event.get("event") == "client_killed_while_B_unknown"]
        unknown = [(i, event) for i, event in dispatched
                   if event.get("job") == "B" and event.get("status") == "transport_unknown"]
        recovered = [(i, event) for i, event in dispatched
                     if event.get("job") == "B" and event.get("op") == "recover"]
        released = [i for i, event in enumerate(events)
                    if event.get("event") == "fixed_response_window_released"]
        restart_valid = False
        if len(workers) == 2 and len(kill_records) == len(unknown) == len(recovered) == len(released) == 1:
            ki, kill = kill_records[0]
            ui, prior = unknown[0]
            ri, after = recovered[0]
            restart_valid = bool(workers[0][0] < ui < ki < workers[1][0] < released[0] < ri and
                                 kill.get("pid") == workers[0][1].get("pid") and
                                 workers[0][1].get("pid") != workers[1][1].get("pid") and
                                 kill.get("exit_code") is not None and kill["exit_code"] != 0 and
                                 kill.get("terminated") is True)
            if prior["descriptor"] != after["descriptor"] or after.get("command", {}).get("descriptor") != prior["descriptor"]:
                failures.append("queue_replay_descriptor_changed")
            expected_origin = {"ecrc": "ecrc_durable_outbox", "durable_count": "direct_durable_log",
                               "raw": "shared_upstream_unacknowledged_message",
                               "volatile_count": "shared_upstream_unacknowledged_message"}[case["arm"]]
            if after.get("recovery_origin") != expected_origin or after.get("status") != "acknowledged":
                failures.append("recovery_origin_or_completion_mismatch")
            queue_path = folder / "QUEUE_REDELIVERY.json"
            if not queue_path.is_file():
                failures.append("shared_queue_redelivery_artifact_missing")
            else:
                queue = json.loads(queue_path.read_text(encoding="utf-8"))
                if queue != {"job": "B", "descriptor": prior["descriptor"], "acknowledged": False}:
                    failures.append("shared_queue_contains_changed_envelope_or_hidden_ack")
        if not restart_valid:
            failures.append("actual_process_restart_while_B_unknown_not_established")
    return {"passed": not failures, "failures": failures,
            "worker_ready_pids": [event["pid"] for _, event in workers],
            "forced_termination_records": killed,
            "worker_post_attempts": len(dispatched),
            "actual_restart_between_unknown_B_and_recovery": restart_valid,
            "scope": "Runner process lifecycle and exact shared queue envelope checked against transport and committed effects."}


def audit(folder: Path) -> dict:
    folder = Path(folder).resolve()
    case = json.loads((folder / "CASE.json").read_text(encoding="utf-8"))
    trace = json.loads((folder / "TRACE.json").read_text(encoding="utf-8"))
    arm = case["arm"]
    condition = case["condition"]
    limit = case["external_limit"]
    if arm not in ("raw", "volatile_count", "durable_count", "ecrc"):
        raise ValueError("unknown arm")
    if condition not in ("normal", "mixed") or type(limit) is not int or limit < 1:
        raise ValueError("invalid public workload configuration")
    jobs = case["jobs"]
    if len(jobs) != 4 or {job["name"] for job in jobs} != {"A", "B", "C", "D"}:
        raise ValueError("public denominator must retain all A/B/C/D inputs")
    by_hash = {job["job_hash"]: job["name"] for job in jobs}
    by_decision = {job["decision_id"]: job["name"] for job in jobs}
    if len(by_hash) != 4 or len(by_decision) != 4:
        raise ValueError("public task identities must be unique")
    failures = []
    sink_tables, sink_source = _read_db(folder / "sink.sqlite")
    if sink_source["integrity_check"] != ["ok"] or not sink_source["file_bytes_unchanged_while_reading"]:
        failures.append("sink_database_unstable_or_corrupt")
    if "effects" not in sink_tables:
        raise ValueError("sink effects table missing")
    effects = []
    counts = Counter({job["name"]: 0 for job in jobs})
    unknown = []
    for row in sink_tables["effects"]:
        effect = dict(row)
        effect["payload"] = _decode(effect.pop("payload_json"))
        if _hash(effect["payload"]) != effect["payload_hash"]:
            failures.append("sink_payload_hash_mismatch:" + str(effect["effect_id"]))
        payload = effect["payload"]
        name = by_decision.get(payload.get("decision_id")) if arm == "ecrc" else by_hash.get(payload.get("job_hash"))
        if name is None:
            unknown.append(effect["effect_id"])
        else:
            counts[name] += 1
        if arm != "ecrc" and name is not None:
            if set(payload) != {"job_hash"}:
                failures.append("ordinary_payload_not_original_descriptor:" + str(effect["effect_id"]))
            if effect["idempotency_key"] != "direct:" + payload["job_hash"]:
                failures.append("ordinary_stable_key_changed:" + str(effect["effect_id"]))
        effect["logical_job"] = name
        effects.append(effect)
    if unknown:
        failures.append("effect_outside_public_input_set")
    same_key_duplicates = sum(max(0, count - 1) for count in Counter(e["idempotency_key"] for e in effects).values())
    if same_key_duplicates:
        failures.append("same_key_has_multiple_committed_effects")
    client_source = None
    if arm in ("ecrc", "durable_count"):
        client_tables, client_source = _read_db(folder / "client.sqlite")
        if client_source["integrity_check"] != ["ok"] or not client_source["file_bytes_unchanged_while_reading"]:
            failures.append("client_database_unstable_or_corrupt")
        account = (_audit_ecrc if arm == "ecrc" else _audit_durable)(client_tables, effects, limit)
        if not account["passed"]:
            failures.extend("client_audit:" + issue for issue in account["failures"])
    else:
        account = {"applicable": False, "passed": None,
                   "reason": "Original direct client has no persistent client ledger; shared queue and sink cache remain available."}
        if (folder / "client.sqlite").exists():
            failures.append("unexpected_persistent_client_database_for_original_client")
    if trace.get("failure") is not None:
        failures.append("runner_reported_failure")
    transport = _audit_transport(folder, effects, case)
    if transport["passed"] is False:
        failures.extend(transport["failures"])
    execution_trace = _audit_trace(folder, trace, case, effects, transport)
    if not execution_trace["passed"]:
        failures.extend(execution_trace["failures"])
    eligible = [job["name"] for job in jobs if condition != "mixed" or job["name"] != "A"]
    expired = ["A"] if condition == "mixed" else []
    over = max(0, len(effects) - limit)
    repeats = sum(max(0, value - 1) for value in counts.values())
    return {
        "schema_version": 1, "arm": arm, "condition": condition,
        "evidence_type": "Controlled synthetic durable-effect interface development; not business benefit.",
        "technical_audit_passed": not failures, "technical_failures": failures,
        "runner_failure": trace.get("failure"), "input_denominator": len(jobs),
        "all_job_names": [job["name"] for job in jobs],
        "effect_counts_by_job": dict(counts), "actual_effect_count": len(effects),
        "distinct_completed_jobs": sum(value > 0 for value in counts.values()),
        "eligible_job_names": eligible, "eligible_input_count": len(eligible),
        "eligible_completed_jobs": sum(counts[name] > 0 for name in eligible),
        "eligible_uncompleted_job_names": [name for name in eligible if counts[name] == 0],
        "queue_expired_job_names": expired,
        "queue_expired_jobs_with_effects": [name for name in expired if counts[name] > 0],
        "extra_repeats": repeats, "same_key_duplicate_effects": same_key_duplicates,
        "external_limit": limit, "external_over_limit": over,
        "external_budget_requirement_met": over == 0,
        "public_queue_deadline_requirement_met": not any(counts[name] for name in expired),
        "effects": effects, "client_accountability": account, "transport_audit": transport,
        "execution_trace_audit": execution_trace,
        "source_databases": {"sink": sink_source, "client": client_source},
        "source_json_sha256": {name: _file_hash(folder / name) for name in ("CASE.json", "TRACE.json")},
        "limitations": [
            "No desired execution subset is hard-coded as success: all A/B/C/D outcomes remain visible.",
            "Budget and queue capability outcomes are separate from technical run validity.",
            "A final effects table establishes duplicate committed effects, not how many retries or pre-commit CPU attempts occurred.",
            "Replay exercise and unknown-state timing require the preserved transport/event trace in addition to this final-state audit.",
            "Public queue cutoff is logical test time, independent of real sink commit timestamps and permit TTL.",
            "No estimate of application benefit, statistical significance, or universal superiority is made.",
        ],
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.folder), ensure_ascii=False, indent=2))
