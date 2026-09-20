"""Loopback service: execute one bound verification job before durable completion.

New jobs are serialized within the sink write transaction. Matching completed
retries use the durable result cache. This does not guarantee exactly-once CPU
across service failure before result commit; that failure is outside this pilot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid

from frozen_service import (EffectHandler, EffectLedger, EffectServer,
                            MAX_BODY_BYTES, canonical_payload, reject_nonfinite,
                            unique_object, valid_key)

JOB_HASH_FIELDS = ("task_id", "candidate_id", "solution_sha256", "test_sha256", "runner_sha256")
COMPLETED = {"pass", "fail", "timeout"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def job_hash(job):
    return digest({key: job[key] for key in JOB_HASH_FIELDS})


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_catalog(catalog_path, runner_path):
    """Validate the actual runner bundle and content-addressed catalog at startup."""
    document = json.loads(catalog_path.read_text("utf-8"), object_pairs_hook=unique_object,
                          parse_constant=reject_nonfinite)
    manifest = document.get("runner_manifest")
    require(isinstance(manifest, dict) and bool(manifest), "runner_manifest is required")
    runner_root = runner_path.parent.resolve()
    require(runner_path.name in manifest, "runner module absent from runner_manifest")
    for relative, expected in manifest.items():
        path = (runner_root / relative).resolve()
        require(path.is_relative_to(runner_root), "runner manifest path escapes workload directory")
        require(path.is_file() and file_hash(path) == expected, "runner file hash differs: " + relative)
    bundle_hash = digest(manifest)
    if "runner_sha256" in document:
        require(document["runner_sha256"] == bundle_hash, "catalog runner bundle hash differs")
    if "jobs" in document:
        require(isinstance(document["jobs"], list), "jobs must be a list")
        supplied = [(None, row) for row in document["jobs"]]
    else:
        require(isinstance(document.get("jobs_by_decision"), dict), "jobs or jobs_by_decision required")
        supplied = list(document["jobs_by_decision"].items())
    require(bool(supplied), "catalog contains no jobs")
    jobs = {}
    for mapped_decision, job in supplied:
        require(isinstance(job, dict), "job must be an object")
        require(all(key in job for key in JOB_HASH_FIELDS), "missing job binding field")
        require(job["runner_sha256"] == bundle_hash, "job runner bundle hash differs")
        for field in ("solution", "test"):
            if field in job:
                require(isinstance(job[field], str) and hashlib.sha256(job[field].encode("utf-8")).hexdigest() == job[field + "_sha256"],
                        "catalog embedded input hash differs: " + field)
        hashed = job_hash(job)
        decision = "verify:" + hashed
        require(mapped_decision is None or mapped_decision == decision, "catalog decision mapping differs")
        require(job.get("decision_id", decision) == decision, "job decision ID differs")
        require(job.get("job_hash", hashed) == hashed, "job hash differs")
        require(decision not in jobs, "duplicate job decision ID")
        jobs[decision] = dict(job)
    claims = document.get("permitted_claim_ids", ["run_verification"])
    require(isinstance(claims, list) and bool(claims) and all(isinstance(c, str) for c in claims),
            "invalid permitted_claim_ids")
    require(len(claims) == len(set(claims)), "duplicate permitted claim")
    return document, jobs, sorted(claims), bundle_hash


def load_runner(path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("verification_workload_runner", path)
    require(spec is not None and spec.loader is not None, "cannot load runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(callable(getattr(module, "run_job", None)), "runner lacks run_job")
    return module.run_job


class VerificationLedger(EffectLedger):
    def __init__(self, db_path, catalog_path, runner_path, runout):
        self.catalog_path, self.runner_path = catalog_path.resolve(), runner_path.resolve()
        self.catalog, self.jobs, self.claims, self.runner_bundle_hash = load_catalog(self.catalog_path, self.runner_path)
        self.run_job = load_runner(self.runner_path)
        self.runout = runout.resolve()
        self.runout.mkdir(parents=True, exist_ok=True)
        self.log_lock = threading.Lock()
        self.event_ordinal = 0
        super().__init__(db_path)
        connection = self.connect()
        try:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS job_results (
                    effect_id INTEGER PRIMARY KEY REFERENCES effects(effect_id),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    job_hash TEXT NOT NULL, task_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pass','fail','timeout')),
                    result_json TEXT NOT NULL, result_hash TEXT NOT NULL,
                    cpu_seconds REAL, wall_seconds REAL NOT NULL,
                    actual_starts INTEGER NOT NULL, run_dir TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_aborts (
                    idempotency_key TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL, result_hash TEXT NOT NULL,
                    recorded_at TEXT NOT NULL, run_dir TEXT NOT NULL
                );
            """)
            connection.commit()
        finally:
            connection.close()

    def event(self, name, **fields):
        with self.log_lock:
            self.event_ordinal += 1
            record = dict(event=name, recorded_at=utc_now(), service_pid=os.getpid(),
                          ordinal=self.event_ordinal, perf_counter_ns=fields.pop("perf_counter_ns", time.perf_counter_ns()), **fields)
            with (self.runout / "service_events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(canonical(record) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def bound_job(self, payload):
        require(set(payload) == {"decision_id", "route", "permitted_claim_ids", "used_evidence_ids"},
                "payload fields differ from registered delivery payload")
        job = self.jobs.get(payload["decision_id"])
        require(job is not None, "decision absent from frozen catalog")
        hashed = job_hash(job)
        require(payload["decision_id"] == "verify:" + hashed, "decision job hash differs")
        require(payload["used_evidence_ids"] == ["job:" + hashed], "used evidence does not bind job")
        require(payload["route"] == "alert", "only alert dispatches verification in this pilot")
        require(payload["permitted_claim_ids"] == self.claims, "verification claim set differs")
        return job, hashed

    @staticmethod
    def completed_ack(connection, row):
        result = connection.execute("SELECT * FROM job_results WHERE effect_id=?", (row["effect_id"],)).fetchone()
        require(result is not None, "effect lacks its atomic verification result")
        document = json.loads(result["result_json"])
        require(digest(document) == result["result_hash"], "stored verification result hash differs")
        return dict(EffectLedger.as_effect(row), job_result=document,
                    result_hash=result["result_hash"], job_hash=result["job_hash"])

    @staticmethod
    def validate_result(result, job):
        require(isinstance(result, dict), "runner result is not an object")
        canonical(result)
        require(result.get("status") in COMPLETED, "runner reported infrastructure error or unknown status")
        require(result.get("actual_start_known", True) is True, "runner cannot establish actual start")
        require(type(result.get("actual_starts")) is int and result["actual_starts"] == 1,
                "completed job must report exactly one actual suite start")
        for key in ("solution_sha256", "test_sha256"):
            require(result.get(key) == job[key], "runner result input hash differs: " + key)
        require(type(result.get("wall_seconds")) in (int, float) and math.isfinite(result["wall_seconds"])
                and result["wall_seconds"] >= 0, "invalid runner wall duration")
        cpu = result.get("cpu_seconds")
        require((cpu is None and result["status"] == "timeout") or
                (type(cpu) in (int, float) and math.isfinite(cpu) and cpu >= 0),
                "invalid runner CPU duration; only timeout may report unavailable CPU")

    def record_abort(self, connection, key, payload_text, payload_hash, result, run_dir):
        serialized = canonical(result)
        hashed = digest(result)
        connection.execute("INSERT INTO run_aborts VALUES(?,?,?,?,?,?,?)",
                           (key, payload_hash, payload_text, serialized, hashed, utc_now(), str(run_dir)))
        connection.commit()
        self.event("run_aborted", idempotency_key=key, result_hash=hashed, run_dir=str(run_dir))
        return 503, dict(error="job_infrastructure_error", idempotency_key=key,
                         job_result=result, result_hash=hashed, cached=False)

    def post(self, key, payload_text, payload_hash):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT * FROM effects WHERE idempotency_key=?", (key,)).fetchone()
            aborted = connection.execute("SELECT * FROM run_aborts WHERE idempotency_key=?", (key,)).fetchone()
            previous = old if old is not None else aborted
            if previous is not None:
                if previous["payload_hash"] != payload_hash or previous["payload_json"] != payload_text:
                    connection.rollback()
                    return 409, dict(error="idempotency_conflict", idempotency_key=key,
                                     existing_payload_hash=previous["payload_hash"], requested_payload_hash=payload_hash)
                if old is not None:
                    ack = self.completed_ack(connection, old)
                    connection.commit()
                    self.event("cache_hit", idempotency_key=key, effect_id=old["effect_id"])
                    return 200, dict(ack, created=False)
                connection.commit()
                return 503, dict(error="job_infrastructure_error", idempotency_key=key,
                                 job_result=json.loads(aborted["result_json"]), result_hash=aborted["result_hash"], cached=True)
            try:
                job, hashed = self.bound_job(json.loads(payload_text))
            except (ValueError, TypeError, KeyError) as exc:
                connection.rollback()
                return 422, dict(error="job_binding_rejected", message=str(exc), idempotency_key=key)
            # Keep Windows artifact paths short. Identity lives in durable rows
            # and bound_job.json, never in the directory's spelling.
            run_dir = self.runout / ("a-" + uuid.uuid4().hex)
            run_dir.mkdir(parents=True, exist_ok=False)
            (run_dir / "bound_job.json").write_text(canonical(job) + "\n", encoding="utf-8")
            self.event("runner_invoked", idempotency_key=key, job_hash=hashed, run_dir=str(run_dir))
            try:
                result = self.run_job(dict(job), run_dir / "work")
                (run_dir / "raw_result.json").write_text(canonical(result) + "\n", encoding="utf-8")
                if isinstance(result, dict) and type(result.get("host_launch_perf_counter_ns")) is int:
                    self.event("job_start", idempotency_key=key, job_hash=hashed, run_dir=str(run_dir),
                               perf_counter_ns=result["host_launch_perf_counter_ns"],
                               timestamp_source="trusted_runner_host_launcher_boundary", recorded_after_runner_return=True)
                self.validate_result(result, job)
            except Exception as exc:
                # Preserve a serializable returned report even when validation rejects it.
                try:
                    raw = result
                    canonical(raw)
                except (UnboundLocalError, TypeError, ValueError):
                    raw = None
                abort = dict(status="infrastructure_error", error_type=type(exc).__name__,
                             message=str(exc), returned_result=raw)
                (run_dir / "abort.json").write_text(canonical(abort) + "\n", encoding="utf-8")
                return self.record_abort(connection, key, payload_text, payload_hash, abort, run_dir)
            result_text, result_digest = canonical(result), digest(result)
            committed_at = utc_now()  # Durable record time, sampled immediately before INSERT.
            cursor = connection.execute("INSERT INTO effects(idempotency_key,payload_hash,payload_json,committed_at) VALUES(?,?,?,?)",
                                        (key, payload_hash, payload_text, committed_at))
            effect_id = cursor.lastrowid
            connection.execute("INSERT INTO job_results VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                               (effect_id, key, hashed, str(job["task_id"]), str(job["candidate_id"]), result["status"],
                                result_text, result_digest, result["cpu_seconds"], result["wall_seconds"],
                                result["actual_starts"], str(run_dir)))
            row = connection.execute("SELECT * FROM effects WHERE effect_id=?", (effect_id,)).fetchone()
            ack = self.completed_ack(connection, row)
            connection.commit()
            commit_return_ns = time.perf_counter_ns()
            self.event("result_commit_return", idempotency_key=key, effect_id=effect_id, perf_counter_ns=commit_return_ns,
                       job_hash=hashed, result_hash=result_digest, run_dir=str(run_dir))
            return 201, dict(ack, created=True)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, key):
        connection = self.connect()
        try:
            row = connection.execute("SELECT * FROM effects WHERE idempotency_key=?", (key,)).fetchone()
            return None if row is None else self.completed_ack(connection, row)
        finally:
            connection.close()


class VerificationHandler(EffectHandler):
    """Legacy framing and endpoints; loss injection only on a newly committed result."""
    server_version = "VerificationPilot/1"

    def do_POST(self):
        if urlsplit(self.path).path != "/effects":
            self.reply(404, dict(error="not_found")); return
        try:
            if self.headers.get("Transfer-Encoding") is not None:
                raise ValueError("transfer encoding unsupported")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isdigit():
                raise ValueError("one Content-Length required")
            length = int(lengths[0])
            if not 0 < length <= MAX_BODY_BYTES:
                raise ValueError("invalid body length")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete body")
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_nonfinite)
            if not isinstance(value, dict) or set(value) != {"idempotency_key", "payload"}:
                raise ValueError("invalid request object")
            if not valid_key(value["idempotency_key"]) or not isinstance(value["payload"], dict):
                raise ValueError("invalid key or payload")
            text, hashed = canonical_payload(value["payload"])
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
            self.reply(400, dict(error="invalid_request")); return
        try:
            code, response = self.server.ledger.post(value["idempotency_key"], text, hashed)
        except Exception as exc:
            self.server.ledger.event("service_error", error_type=type(exc).__name__, message=str(exc))
            self.reply(503, dict(error="service_error", error_type=type(exc).__name__)); return
        if code == 201 and self.headers.get("X-Test-Drop-Response", "").strip() == "1":
            self.server.ledger.event("response_drop", idempotency_key=value["idempotency_key"], effect_id=response["effect_id"])
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return
        self.reply(code, response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--runout", required=True, type=Path)
    parser.add_argument("--runner", type=Path, default=Path(__file__).resolve().parents[1] / "workload/job_runner.py")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    require(0 <= args.port <= 65535, "invalid port")
    ledger = VerificationLedger(args.db, args.catalog, args.runner, args.runout)
    server = EffectServer(("127.0.0.1", args.port), ledger)
    server.RequestHandlerClass = VerificationHandler
    print(canonical(dict(event="ready", host="127.0.0.1", port=server.server_port, pid=os.getpid(),
                         db=str(ledger.db_path), schema_version=1, application_schema_version=1,
                         catalog_sha256=file_hash(args.catalog), runner_sha256=ledger.runner_bundle_hash)), flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
