"""A traditional durable cumulative counter for direct task submissions.

This is the explicitly strengthened ``durable_direct_count`` comparator. The
unmodified raw DirectClient remains a separate comparator. This module has no
ECRC imports, evidence qualification, route, claim, permit, expiry or release
semantics. Each new operation is counted durably before its descriptor leaves
prepare(); acknowledgements and unknown outcomes never refund that count.

Only the submitted payload is bound: the original direct interface selects a
catalog entry using job_hash, so other queue metadata is not execution content.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _descriptor(job: dict) -> dict:
    if not isinstance(job, dict):
        raise ValueError("job must be an object")
    job_hash = job.get("job_hash")
    if not isinstance(job_hash, str) or not job_hash:
        raise ValueError("job_hash must be a nonempty string")
    return {"idempotency_key": "direct:" + job_hash,
            "payload": {"job_hash": job_hash}}


class DurableDirectCount:
    """Persistent, fixed-scope cumulative admission with stable direct keys.

    prepare returns exactly the raw DirectClient's submission descriptor, or
    None when a *new* operation exceeds the cumulative limit. Preparing the
    same key returns its existing descriptor without another charge, including
    after restart or acknowledgement. pending returns only descriptors that
    lack an acknowledgement. No service state or future outcome is consulted.
    """

    def __init__(self, path: str | Path, scope: str, limit: int = 2):
        if not isinstance(scope, str) or not scope:
            raise ValueError("scope must be a nonempty string")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        self.path = Path(path).resolve()
        self.scope = scope
        self.limit = limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = self._connect()
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("BEGIN IMMEDIATE")
            con.execute("""CREATE TABLE IF NOT EXISTS direct_scopes (
                scope TEXT PRIMARY KEY,
                action_limit INTEGER NOT NULL CHECK(action_limit > 0)
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS direct_operations (
                scope TEXT NOT NULL REFERENCES direct_scopes(scope),
                idempotency_key TEXT NOT NULL,
                job_hash TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                descriptor_json TEXT NOT NULL,
                ack_json TEXT,
                PRIMARY KEY (scope, idempotency_key)
            )""")
            row = con.execute("SELECT action_limit FROM direct_scopes WHERE scope=?",
                              (scope,)).fetchone()
            if row is None:
                con.execute("INSERT INTO direct_scopes VALUES (?, ?)", (scope, limit))
            elif row["action_limit"] != limit:
                raise ValueError("persisted scope limit cannot change on restart")
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA synchronous=FULL")
        return con

    def prepare(self, job: dict) -> dict | None:
        descriptor = _descriptor(job)
        key = descriptor["idempotency_key"]
        payload_hash = digest(descriptor["payload"])
        serialized = canonical(descriptor)
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            previous = con.execute("""SELECT * FROM direct_operations
                WHERE scope=? AND idempotency_key=?""", (self.scope, key)).fetchone()
            if previous is not None:
                if (previous["payload_hash"] != payload_hash or
                        previous["descriptor_json"] != serialized):
                    raise ValueError("operation key is already bound to different content")
                con.commit()
                return json.loads(previous["descriptor_json"])
            count = con.execute("SELECT COUNT(*) FROM direct_operations WHERE scope=?",
                                (self.scope,)).fetchone()[0]
            if count >= self.limit:
                con.commit()
                return None
            con.execute("""INSERT INTO direct_operations
                (scope, idempotency_key, job_hash, payload_hash, descriptor_json)
                VALUES (?, ?, ?, ?, ?)""",
                (self.scope, key, job["job_hash"], payload_hash, serialized))
            con.commit()
            return descriptor
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def finish(self, job: dict, ack: dict) -> None:
        """Record a bound S8 service acknowledgement, retaining cumulative cost.

        ``created`` is response metadata: first POST and cached POST may differ
        on it. All other fields, including effect identity and committed_at,
        must be identical if finish is repeated. No task-quality judgement is
        inferred from the service acknowledgement.
        """
        descriptor = _descriptor(job)
        if not isinstance(ack, dict):
            raise ValueError("ack must be an object")
        # Round-trip before comparison/persistence rejects non-JSON payloads and
        # prevents a caller's later mutation from changing the stored document.
        stable_ack = json.loads(canonical(ack))
        if stable_ack.get("idempotency_key") != descriptor["idempotency_key"]:
            raise ValueError("ack idempotency key does not match the request")
        if stable_ack.get("payload") != descriptor["payload"]:
            raise ValueError("ack payload does not match the request")
        if stable_ack.get("payload_hash") != digest(descriptor["payload"]):
            raise ValueError("ack payload hash does not match the request")
        if type(stable_ack.get("effect_id")) is not int or stable_ack["effect_id"] <= 0:
            raise ValueError("ack effect_id must be a positive integer")
        if not isinstance(stable_ack.get("committed_at"), str) or not stable_ack["committed_at"]:
            raise ValueError("ack must include its service commit timestamp")
        if "error" in stable_ack:
            raise ValueError("service error is not a completed acknowledgement")
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("""SELECT * FROM direct_operations
                WHERE scope=? AND idempotency_key=?""",
                (self.scope, descriptor["idempotency_key"])).fetchone()
            if row is None:
                raise ValueError("cannot finish an operation that was not prepared")
            if (row["payload_hash"] != stable_ack["payload_hash"] or
                    row["descriptor_json"] != canonical(descriptor)):
                raise ValueError("ack does not match the persisted request binding")
            if row["ack_json"] is not None:
                old = json.loads(row["ack_json"])
                old.pop("created", None)
                comparison = dict(stable_ack)
                comparison.pop("created", None)
                if canonical(old) != canonical(comparison):
                    raise ValueError("conflicting acknowledgement for an existing operation")
            else:
                con.execute("""UPDATE direct_operations SET ack_json=?
                    WHERE scope=? AND idempotency_key=?""",
                    (canonical(stable_ack), self.scope, descriptor["idempotency_key"]))
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def pending(self) -> list[dict]:
        con = self._connect()
        try:
            rows = con.execute("""SELECT descriptor_json FROM direct_operations
                WHERE scope=? AND ack_json IS NULL ORDER BY rowid""", (self.scope,)).fetchall()
            return [json.loads(row["descriptor_json"]) for row in rows]
        finally:
            con.close()

    def snapshot(self) -> dict:
        con = self._connect()
        try:
            rows = con.execute("""SELECT * FROM direct_operations
                WHERE scope=? ORDER BY rowid""", (self.scope,)).fetchall()
            operations = [{"descriptor": json.loads(row["descriptor_json"]),
                           "payload_hash": row["payload_hash"],
                           "ack": None if row["ack_json"] is None else json.loads(row["ack_json"])}
                          for row in rows]
            acknowledged = sum(op["ack"] is not None for op in operations)
            return {"method": "durable_direct_count", "scope": self.scope,
                    "limit": self.limit, "reserved_count": len(operations),
                    "acknowledged_count": acknowledged,
                    "pending_count": len(operations) - acknowledged,
                    "persistence": "sqlite", "operations": operations}
        finally:
            con.close()
