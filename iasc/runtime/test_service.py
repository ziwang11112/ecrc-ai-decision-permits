"""Independent HTTP/process tests for service.py; pure Python standard library."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import queue
import sqlite3
import subprocess
import sys
import threading
import traceback
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
SERVICE = HERE / "service.py"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ServiceProcess:
    def __init__(self, db, log):
        self.db = db
        self.stderr_file = log.open("w", encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            [sys.executable, str(SERVICE), "--db", str(db), "--port", "0"],
            stdout=subprocess.PIPE, stderr=self.stderr_file, text=True, encoding="utf-8",
            creationflags=flags,
        )
        lines = queue.Queue()
        reader = threading.Thread(target=lambda: lines.put(self.process.stdout.readline()), daemon=True)
        reader.start()
        try:
            line = lines.get(timeout=8)
            self.ready = json.loads(line)
            assert self.ready["event"] == "ready" and self.ready["host"] == "127.0.0.1"
            assert self.ready["pid"] == self.process.pid
            assert 0 < self.ready["port"] <= 65535
            assert Path(self.ready["db"]).resolve() == db.resolve()
            self.port = self.ready["port"]
        except Exception:
            self.stop()
            raise

    def stop(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        if self.process.stdout is not None:
            self.process.stdout.close()
        self.stderr_file.close()


def request(server, method, path, value=None, headers=None, raw=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    if raw is None and value is not None:
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    hdr = dict(headers or {})
    if raw is not None:
        hdr.setdefault("Content-Type", "application/json")
    try:
        connection.request(method, path, body=raw, headers=hdr)
        response = connection.getresponse()
        data = response.read()
        assert response.getheader("Content-Type").startswith("application/json")
        assert int(response.getheader("Content-Length")) == len(data)
        return response.status, json.loads(data)
    finally:
        connection.close()


def durable_rows(db):
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        return [dict(row) for row in connection.execute("SELECT * FROM effects ORDER BY effect_id")]
    finally:
        connection.close()


def test_concurrent_same_key(case):
    db = case / "sink.sqlite"
    server = ServiceProcess(db, case / "server.stderr.txt")
    try:
        assert request(server, "GET", "/health") == (200, {"status": "ok", "schema_version": 1})
        key = "concurrent/key-é"
        payload = {"account": "sandbox", "effect": {"b": 2, "a": 1}, "label": "é"}
        barrier = threading.Barrier(20)

        def worker(index):
            varied = payload if index % 2 == 0 else {"label": "é", "effect": {"a": 1, "b": 2}, "account": "sandbox"}
            body = json.dumps({"payload": varied, "idempotency_key": key}, ensure_ascii=index % 2 == 0,
                              indent=2 if index % 3 == 0 else None).encode("utf-8")
            barrier.wait(timeout=5)
            return request(server, "POST", "/effects", raw=body)

        with ThreadPoolExecutor(max_workers=20) as executor:
            responses = list(executor.map(worker, range(20)))
        statuses = [code for code, _ in responses]
        assert statuses.count(201) == 1 and statuses.count(200) == 19
        assert sum(value["created"] for _, value in responses) == 1
        effects = [{k: v for k, v in value.items() if k != "created"} for _, value in responses]
        assert all(effect == effects[0] for effect in effects)
        status, queried = request(server, "GET", "/effects/" + quote(key, safe=""))
        assert status == 200 and queried == effects[0]
        rows = durable_rows(db)
        assert len(rows) == 1 and rows[0]["effect_id"] == effects[0]["effect_id"]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert rows[0]["payload_json"] == canonical
        assert rows[0]["payload_hash"] == hashlib.sha256(canonical.encode()).hexdigest()
        return dict(requests=20, created_responses=1, replay_responses=19, durable_rows=1,
                    all_effects_identical=True, wire_key_order_and_whitespace_varied=True,
                    encoded_key_query_pass=True, service_pid=server.process.pid)
    finally:
        server.stop()


def test_conflicting_payload(case):
    db = case / "sink.sqlite"
    server = ServiceProcess(db, case / "server.stderr.txt")
    try:
        original = {"idempotency_key": "conflict", "payload": {"amount": 3, "operation": "sandbox-credit"}}
        code, first = request(server, "POST", "/effects", original)
        assert code == 201
        changed = {"idempotency_key": "conflict", "payload": {"amount": 4, "operation": "sandbox-credit"}}
        code, conflict = request(server, "POST", "/effects", changed)
        assert code == 409 and conflict["error"] == "idempotency_conflict"
        assert conflict["existing_payload_hash"] == first["payload_hash"]
        assert conflict["requested_payload_hash"] != first["payload_hash"]
        code, retry = request(server, "POST", "/effects", original)
        assert code == 200 and not retry["created"]
        assert {k: v for k, v in retry.items() if k != "created"} == {k: v for k, v in first.items() if k != "created"}
        rows = durable_rows(db)
        assert len(rows) == 1 and json.loads(rows[0]["payload_json"]) == original["payload"]
        return dict(conflict_status=409, durable_rows=1, original_effect_preserved=True)
    finally:
        server.stop()


def test_drop_restart_retry(case):
    db = case / "sink.sqlite"
    server = ServiceProcess(db, case / "server_before.stderr.txt")
    original = {"idempotency_key": "unknown-outcome", "payload": {"operation": "persistent-sandbox-effect", "units": 1}}
    try:
        transport_failure = None
        try:
            request(server, "POST", "/effects", original, headers={"X-Test-Drop-Response": "1"})
        except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError) as exc:
            transport_failure = type(exc).__name__
        assert transport_failure is not None, "The injected request must return no HTTP response"
        before = durable_rows(db)
        assert len(before) == 1
        old_pid = server.process.pid
    finally:
        # Kill the actual independent sink, not merely the requesting client.
        server.stop()
    restarted = ServiceProcess(db, case / "server_after.stderr.txt")
    try:
        code, found = request(restarted, "GET", "/effects/unknown-outcome")
        assert code == 200 and found["effect_id"] == before[0]["effect_id"]
        assert found["payload_hash"] == before[0]["payload_hash"]
        assert found["committed_at"] == before[0]["committed_at"]
        code, retry = request(restarted, "POST", "/effects", original)
        assert code == 200 and not retry["created"]
        assert {k: v for k, v in retry.items() if k != "created"} == found
        after = durable_rows(db)
        assert before == after and len(after) == 1
        return dict(injection="explicit commit-then-drop-response header", client_failure=transport_failure,
                    actual_service_process_killed=True, before_pid=old_pid, restarted_pid=restarted.process.pid,
                    query_after_restart_status=200, retry_after_restart_status=200,
                    durable_rows_before=1, durable_rows_after=1, original_effect_fields_preserved=True)
    finally:
        restarted.stop()


def test_invalid_requests(case):
    db = case / "sink.sqlite"
    server = ServiceProcess(db, case / "server.stderr.txt")
    try:
        assert request(server, "GET", "/effects/absent") == (404, {"error": "not_found"})
        bodies = [b"not json", b"[]", b'{"idempotency_key":"x","payload":[]}',
                  b'{"idempotency_key":"x","payload":{"v":NaN}}',
                  b'{"idempotency_key":"x","payload":{"v":1,"v":2}}',
                  b'{"idempotency_key":"","payload":{}}']
        for body in bodies:
            code, value = request(server, "POST", "/effects", raw=body)
            assert code == 400 and value["error"] == "invalid_request"
        assert len(durable_rows(db)) == 0
        return dict(invalid_bodies_rejected=len(bodies), absent_key_status=404, durable_rows=0)
    finally:
        server.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "service_test_run")
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(HERE):
        parser.error("test outputs must remain in the runtime-extension directory")
    out.mkdir(parents=True, exist_ok=False)
    cases = (test_concurrent_same_key, test_conflicting_payload, test_drop_restart_retry, test_invalid_requests)
    report = dict(started_at=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                  sqlite=sqlite3.sqlite_version, platform=platform.platform(), service_sha256=sha(SERVICE),
                  tests_sha256=sha(Path(__file__)), protocol_sha256=sha(HERE / "PROTOCOL_SERVICE.md"), tests=[])
    failed = False
    for function in cases:
        case = out / function.__name__
        case.mkdir()
        try:
            details = function(case)
            report["tests"].append(dict(name=function.__name__, passed=True, **details))
        except Exception:
            failed = True
            report["tests"].append(dict(name=function.__name__, passed=False, traceback=traceback.format_exc()))
    report["passed"] = not failed
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
