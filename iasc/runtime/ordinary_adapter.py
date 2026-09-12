"""Independent conventional JSON/SQLite durable-grant delivery adapter.

No ECRC imports, no HTTP, and no use of the other arm's validation/recovery
helpers. A shared trusted preissued fixture and transport contract are inputs.
Authorization becomes irrevocable at the committed arm transaction. Expiry or
revocation subsequently prevents new grants, but cannot cancel an armed grant.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp is not text")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp lacks timezone")
    return result.astimezone(timezone.utc)


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Adapter:
    """Ordinary relational implementation with separately designed tables."""

    def __init__(self, db_path):
        self.path = str(Path(db_path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(name TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS policy(id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    digest TEXT NOT NULL, document TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS permit_registry(id TEXT PRIMARY KEY, digest TEXT NOT NULL,
                    document TEXT NOT NULL, registration TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS budgets(policy_id TEXT NOT NULL, policy_revision INTEGER NOT NULL,
                    scope_key TEXT NOT NULL, resource TEXT NOT NULL, ceiling INTEGER NOT NULL,
                    held INTEGER NOT NULL, spent INTEGER NOT NULL, state_revision INTEGER NOT NULL,
                    PRIMARY KEY(policy_id,policy_revision,scope_key,resource),
                    CHECK(held>=0 AND spent>=0 AND held+spent<=ceiling));
                CREATE TABLE IF NOT EXISTS holds(id TEXT PRIMARY KEY, document TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('reserved','committed','released')));
                CREATE TABLE IF NOT EXISTS delivery(permit_id TEXT PRIMARY KEY, permit_hash TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('armed','receipted')), receipt_json TEXT,
                    ack_json TEXT, armed_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts(permit_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE,
                    effect_id INTEGER NOT NULL UNIQUE, document TEXT NOT NULL);
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def seed(self, fixture: dict) -> None:
        """Copy and verify the trusted fixture, without re-adjudicating it.

        Seed is excluded from measured delivery. A repeated identical seed is
        harmless; a different seed cannot overwrite a used database.
        """
        fingerprint = digest(fixture)
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT value FROM metadata WHERE name='fixture_digest'").fetchone()
            if previous:
                require(previous[0] == fingerprint, "different fixture cannot replace existing state")
                db.commit()
                return
            policy = fixture["policy"]
            policy_hash = digest(policy)
            db.execute("INSERT INTO policy(id,revision,digest,document) VALUES(?,?,?,?)",
                       (policy["policy_id"], policy["revision"], policy_hash, canonical(policy)))
            registered = {row["permit_id"]: row for row in fixture["issued_permits"]}
            require(len(registered) == len(fixture["issued_permits"]), "duplicate trusted issuance")
            require(len({p["permit_id"] for p in fixture["permits"]}) == len(fixture["permits"]), "duplicate permit document")
            require(set(registered) == {p["permit_id"] for p in fixture["permits"]}, "permit/registry inventory differs")
            for permit in fixture["permits"]:
                row = registered[permit["permit_id"]]
                require(row["permit_hash"] == digest(permit), "trusted permit document digest mismatch")
                require(permit["policy_id"] == policy["policy_id"] and permit["policy_revision"] == policy["revision"] and permit["policy_hash"] == policy_hash,
                        "seed permit policy mismatch")
                for field in ("decision_id", "policy_id", "policy_revision", "policy_hash", "request_hash", "reservation_id", "route", "reason_code", "issued_at"):
                    require(row[field] == permit[field], "trusted issuance field mismatch: " + field)
                db.execute("INSERT INTO permit_registry VALUES(?,?,?,?)", (permit["permit_id"], digest(permit), canonical(permit), canonical(row)))
            for row in fixture["capacity_state"]:
                db.execute("INSERT INTO budgets VALUES(?,?,?,?,?,?,?,?)", (
                    row["policy_id"], row["policy_revision"], row["scope_key"], row["resource"],
                    row["capacity_limit"], row["reserved"], row["committed"], row["state_revision"]))
            for row in fixture["reservations"]:
                db.execute("INSERT INTO holds VALUES(?,?,?)", (row["reservation_id"], canonical(row), row["status"]))
            # Independently verify imported capacity accounting by every key.
            for budget in db.execute("SELECT * FROM budgets"):
                matches = [r for r in fixture["reservations"] if all(r[k] == budget[k] for k in ("policy_id", "policy_revision", "scope_key", "resource"))]
                held = sum(r["amount"] for r in matches if r["status"] == "reserved")
                spent = sum(r["amount"] for r in matches if r["status"] == "committed")
                require(held == budget["held"] and spent == budget["spent"], "trusted capacity/reservation accounting differs")
            db.execute("INSERT INTO metadata VALUES('fixture_digest',?)", (fingerprint,))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def arm(self, permit: dict, at: str) -> dict:
        content_hash = digest(permit)
        permit_id = permit["permit_id"]
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM delivery WHERE permit_id=?", (permit_id,)).fetchone()
            if existing:
                require(existing["permit_hash"] == content_hash, "operation key has conflicting permit content")
                db.commit()
                return dict(existing)
            registration = db.execute("SELECT * FROM permit_registry WHERE id=?", (permit_id,)).fetchone()
            require(registration is not None and registration["digest"] == content_hash,
                    "permit is not the exact trusted issued content")
            row = json.loads(registration["registration"])
            for field in ("decision_id", "policy_id", "policy_revision", "policy_hash", "request_hash", "reservation_id", "route", "reason_code", "issued_at"):
                require(row[field] == permit[field], "issued binding differs: " + field)
            active = db.execute("SELECT * FROM policy WHERE id=?", (permit["policy_id"],)).fetchone()
            require(active is not None and not active["revoked"], "policy unavailable or revoked")
            require(active["revision"] == permit["policy_revision"] and active["digest"] == permit["policy_hash"], "policy revision/hash differs")
            policy = json.loads(active["document"])
            when = timestamp(at)
            require(timestamp(policy["effective_from"]) <= when < timestamp(policy["expires_at"]), "policy is not currently valid")
            require(timestamp(permit["issued_at"]) <= when < timestamp(permit["expires_at"]), "permit is not currently valid")
            require(permit["route"] in ("alert", "review") and permit["route"] in policy["allowed_routes"], "only a permitted action can create a service intent")
            require(permit["reserved_resource"] == permit["route"] and permit["post_state_revision"] == permit["pre_state_revision"] + 1,
                    "permit action/state transition invalid")
            admitted, used, excluded = (set(permit[k]) for k in ("admitted_evidence_ids", "used_evidence_ids", "excluded_evidence_ids"))
            require(bool(used) and used <= admitted and not admitted.intersection(excluded), "permit evidence membership invalid")
            claims = set(permit["permitted_claim_ids"])
            require(bool(claims) and not claims.intersection(permit["blocked_claim_ids"]) and not claims.intersection(policy["blocked_claim_ids"]), "permit claim scope invalid")
            rules = {rule["claim_id"]: rule for rule in policy["claim_rules"]}
            require(all(c in rules and permit["route"] in rules[c]["routes"] and
                        (not rules[c]["reason_codes"] or permit["reason_code"] in rules[c]["reason_codes"]) for c in claims), "claim not supported on this route")
            hold_row = db.execute("SELECT * FROM holds WHERE id=?", (permit["reservation_id"],)).fetchone()
            require(hold_row is not None and hold_row["status"] == "reserved", "held reservation required")
            hold = json.loads(hold_row["document"])
            for key in ("permit_id", "request_hash", "policy_id", "policy_revision", "policy_hash", "pre_state_revision", "post_state_revision"):
                require(hold[key] == permit[key], "reservation binding differs: " + key)
            require(hold["permit_hash"] == content_hash and hold["resource"] == permit["route"] and hold["amount"] == 1,
                    "reservation content/resource/amount differs")
            budget = db.execute("SELECT * FROM budgets WHERE policy_id=? AND policy_revision=? AND scope_key=? AND resource=?",
                                tuple(hold[k] for k in ("policy_id", "policy_revision", "scope_key", "resource"))).fetchone()
            require(budget is not None and budget["held"] >= 1 and budget["held"] + budget["spent"] <= budget["ceiling"], "held capacity is absent or excessive")
            payload = {key: permit[key] for key in ("decision_id", "route", "permitted_claim_ids", "used_evidence_ids")}
            job = dict(permit_id=permit_id, permit_hash=content_hash, idempotency_key=permit_id,
                       payload_json=canonical(payload), payload_hash=digest(payload), state="armed",
                       receipt_json=None, ack_json=None, armed_at=at)
            db.execute("INSERT INTO delivery VALUES(:permit_id,:permit_hash,:idempotency_key,:payload_json,:payload_hash,:state,:receipt_json,:ack_json,:armed_at)", job)
            db.commit()
            return job
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def finish(self, permit_id: str, ack: dict, at: str, before_commit=None) -> dict:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM delivery WHERE permit_id=?", (permit_id,)).fetchone()
            require(job is not None, "cannot complete an unarmed operation")
            require(ack.get("idempotency_key") == job["idempotency_key"] and ack.get("payload_hash") == job["payload_hash"], "service acknowledgement binding differs")
            require(type(ack.get("effect_id")) is int and ack["effect_id"] > 0, "service effect identifier must be a positive integer")
            require(digest(ack["payload"]) == job["payload_hash"], "acknowledged payload differs")
            timestamp(ack["committed_at"])
            if job["state"] == "receipted":
                receipt = json.loads(job["receipt_json"])
                require(receipt["service_effect_id"] == ack["effect_id"], "acknowledgement conflicts with completed effect")
                db.commit()
                return receipt
            permit_row = db.execute("SELECT * FROM permit_registry WHERE id=?", (permit_id,)).fetchone()
            require(permit_row["digest"] == job["permit_hash"], "issued content changed after arm")
            permit = json.loads(permit_row["document"])
            row = db.execute("SELECT * FROM holds WHERE id=?", (permit["reservation_id"],)).fetchone()
            require(row is not None and row["status"] == "reserved", "armed reservation is no longer held")
            hold = json.loads(row["document"])
            require(hold["permit_id"] == permit_id and hold["permit_hash"] == job["permit_hash"], "reservation no longer binds grant")
            key = tuple(hold[k] for k in ("policy_id", "policy_revision", "scope_key", "resource"))
            changed = db.execute("UPDATE budgets SET held=held-?,spent=spent+?,state_revision=state_revision+1 WHERE policy_id=? AND policy_revision=? AND scope_key=? AND resource=? AND held>=?",
                                 (hold["amount"], hold["amount"], *key, hold["amount"]))
            require(changed.rowcount == 1, "cannot commit held capacity")
            reconciled_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            hold.update(status="committed", updated_at=reconciled_at)
            db.execute("UPDATE holds SET status='committed',document=? WHERE id=?", (canonical(hold), permit["reservation_id"]))
            receipt = {"receipt_id": "ordinary-receipt-" + digest({"permit_id": permit_id, "payload_hash": job["payload_hash"], "effect_id": ack["effect_id"]})[:32],
                       "permit_id": permit_id, "permit_hash": job["permit_hash"], "idempotency_key": job["idempotency_key"],
                       "payload_hash": job["payload_hash"], "side_effect_id": str(ack["effect_id"]), "effect_id": ack["effect_id"], "service_effect_id": ack["effect_id"],
                       "route": permit["route"], "execution_status": "executed", "reservation_id": permit["reservation_id"],
                       "armed_at": job["armed_at"], "committed_at": ack["committed_at"], "executed_at": ack["committed_at"],
                       "reconciled_at": reconciled_at, "reconciliation_policy_clock": at, "service_ack": ack}
            db.execute("INSERT INTO receipts VALUES(?,?,?,?)", (permit_id, receipt["receipt_id"], ack["effect_id"], canonical(receipt)))
            db.execute("UPDATE delivery SET state='receipted',receipt_json=?,ack_json=? WHERE permit_id=?",
                       (canonical(receipt), canonical(ack), permit_id))
            if before_commit is not None:
                before_commit()
            db.commit()
            return receipt
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get_job(self, permit_id):
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM delivery WHERE permit_id=?", (permit_id,)).fetchone()
            return dict(row) if row else None
        finally:
            db.close()

    def snapshot(self):
        db = self._connect()
        try:
            db.execute("BEGIN")
            counts = {row["state"]: row["n"] for row in db.execute("SELECT state,COUNT(*) n FROM delivery GROUP BY state")}
            totals = db.execute("SELECT COALESCE(SUM(held),0),COALESCE(SUM(spent),0),COALESCE(SUM(ceiling),0) FROM budgets").fetchone()
            result = {"n_receipts": db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], "n_armed": counts.get("armed", 0),
                      "n_receipted": counts.get("receipted", 0), "n_jobs": sum(counts.values()), "reserved": totals[0],
                      "committed": totals[1], "capacity_limit": totals[2], "budgets": [dict(row) for row in db.execute("SELECT * FROM budgets ORDER BY policy_id,policy_revision,scope_key,resource")]}
            result["jobs"] = [dict(row) for row in db.execute("SELECT * FROM delivery ORDER BY permit_id")]
            result["capacity_rows"] = [
                {**{k: row[k] for k in ("policy_id", "policy_revision", "scope_key", "resource", "state_revision")},
                 "reserved": row["held"], "committed": row["spent"], "capacity_limit": row["ceiling"]}
                for row in result["budgets"]
            ]
            db.commit()
            return result
        finally:
            db.close()

    def revoke(self):
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE policy SET revoked=1")
            db.commit()
        finally:
            db.close()
