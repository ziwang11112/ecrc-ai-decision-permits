"""Independent plain-JSON end-to-end issuance with a conventional SQLite outbox.

This source-informed comparator imports only its own earlier delivery adapter.
It does not use the other arm's policy classes, adjudicator, ledger, fixtures,
canonicalization, or issuance helpers.  Ingestion and issuance are separate
durable transactions. Reservation, fallback release, registration, and storage
of the complete issued document share one issuance transaction.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import timedelta

from legacy_snapshot.ordinary_adapter import Adapter as DeliveryAdapter
from legacy_snapshot.ordinary_adapter import canonical, digest, require, timestamp


ROUTES = {"alert", "review", "abstain", "no_action"}
ACTIONS = {"alert", "review"}
POLICY_FIELDS = {
    "policy_id", "revision", "issuer_id", "effective_from", "expires_at",
    "approved_models", "evidence_rules", "score_threshold",
    "uncertainty_threshold", "review_band_width", "alert_capacity",
    "review_capacity", "capacity_scope", "claim_rules", "blocked_claim_ids",
    "allowed_routes", "failure_mode",
}
PROPOSAL_FIELDS = {
    "decision_id", "subject_id", "session_id", "model_id", "model_version",
    "model_hash", "score", "uncertainty", "proposed_action", "proposed_at",
    "input_hash", "validation_scope_id",
}
ITEM_FIELDS = {
    "evidence_id", "evidence_type", "source", "schema_version", "observed_at",
    "available_at", "provenance_hash", "requested_for_use",
}


def _object(value, fields, name):
    require(type(value) is dict and set(value) == fields, name + " fields differ")


def _text(value, name):
    require(type(value) is str and bool(value) and value == value.strip(),
            name + " must be nonempty, unpadded text")


def _hash(value, name):
    require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None,
            name + " must be a lowercase SHA-256 digest")


def _names(value, name, *, nonempty=False):
    require(type(value) is list and (not nonempty or bool(value)), name + " must be a list")
    for item in value:
        _text(item, name)
    require(len(set(value)) == len(value), name + " contains duplicates")


def _unit(value, name):
    require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1,
            name + " must be finite and in [0,1]")


def _integer(value, name, minimum=0):
    require(type(value) is int and value >= minimum, name + " is not a bounded integer")


def _time(value):
    return timestamp(value).isoformat().replace("+00:00", "Z")


def validate_policy(policy):
    """Validate the full supported policy vocabulary, without normalizing inputs."""
    _object(policy, POLICY_FIELDS, "policy")
    canonical(policy)
    for field in ("policy_id", "issuer_id"):
        _text(policy[field], field)
    _integer(policy["revision"], "revision", 1)
    require(timestamp(policy["effective_from"]) < timestamp(policy["expires_at"]),
            "policy validity interval is empty")
    for field in ("score_threshold", "uncertainty_threshold", "review_band_width"):
        _unit(policy[field], field)
    for field in ("alert_capacity", "review_capacity"):
        _integer(policy[field], field)
    require(policy["capacity_scope"] in ("subject", "session", "subject_session", "participant_segment"),
            "unsupported capacity scope")
    require(policy["failure_mode"] == "fail_closed", "unsupported failure mode")
    _names(policy["allowed_routes"], "allowed_routes", nonempty=True)
    require(set(policy["allowed_routes"]) <= ROUTES, "unknown route")
    _names(policy["blocked_claim_ids"], "blocked_claim_ids")
    models = policy["approved_models"]
    require(type(models) is list and bool(models), "approved_models must be nonempty")
    for model in models:
        _object(model, {"model_id", "model_hash"}, "model")
        _text(model["model_id"], "model_id")
        _hash(model["model_hash"], "model_hash")
    require(len({m["model_id"] for m in models}) == len(models), "duplicate model ID")
    evidence_rules = policy["evidence_rules"]
    require(type(evidence_rules) is list and bool(evidence_rules), "evidence_rules must be nonempty")
    for rule in evidence_rules:
        _object(rule, {"evidence_type", "allowed_sources", "allowed_schema_versions",
                       "max_age_seconds", "use_allowed"}, "evidence rule")
        _text(rule["evidence_type"], "evidence_type")
        _names(rule["allowed_sources"], "allowed_sources", nonempty=True)
        _names(rule["allowed_schema_versions"], "allowed_schema_versions", nonempty=True)
        _integer(rule["max_age_seconds"], "max_age_seconds")
        require(type(rule["use_allowed"]) is bool, "use_allowed must be boolean")
    require(len({r["evidence_type"] for r in evidence_rules}) == len(evidence_rules),
            "duplicate evidence rule")
    claims = policy["claim_rules"]
    require(type(claims) is list, "claim_rules must be a list")
    usable_types = {r["evidence_type"] for r in evidence_rules if r["use_allowed"]}
    for rule in claims:
        _object(rule, {"claim_id", "routes", "reason_codes", "required_evidence_types"}, "claim rule")
        _text(rule["claim_id"], "claim_id")
        _names(rule["routes"], "claim routes", nonempty=True)
        require(set(rule["routes"]) <= ROUTES, "unknown claim route")
        _names(rule["reason_codes"], "reason_codes")
        _names(rule["required_evidence_types"], "required_evidence_types")
        if set(rule["routes"]) & ACTIONS:
            require(bool(rule["required_evidence_types"]) and
                    set(rule["required_evidence_types"]) <= usable_types,
                    "action claim needs usable evidence types")
    require(len({r["claim_id"] for r in claims}) == len(claims), "duplicate claim rule")
    require(not ({r["claim_id"] for r in claims} & set(policy["blocked_claim_ids"])),
            "conditionally allowed claim is also blocked")
    for route in set(policy["allowed_routes"]) & ACTIONS:
        require(any(route in r["routes"] for r in claims), "action route lacks any claim rule")


def validate_request(request, at):
    _object(request, {"policy", "proposal", "evidence"}, "request")
    canonical(request)
    policy, proposal, envelope = (request[k] for k in ("policy", "proposal", "evidence"))
    validate_policy(policy)
    _object(proposal, PROPOSAL_FIELDS, "proposal")
    for field in PROPOSAL_FIELDS - {"score", "uncertainty", "proposed_at", "model_hash", "input_hash"}:
        _text(proposal[field], field)
    for field in ("model_hash", "input_hash"):
        _hash(proposal[field], field)
    for field in ("score", "uncertainty"):
        _unit(proposal[field], field)
    require(timestamp(proposal["proposed_at"]) <= timestamp(at), "future proposal")
    require(any(m["model_id"] == proposal["model_id"] and m["model_hash"] == proposal["model_hash"]
                for m in policy["approved_models"]), "unapproved model ID/hash pair")
    _object(envelope, {"decision_id", "created_at", "items"}, "evidence envelope")
    require(envelope["decision_id"] == proposal["decision_id"], "evidence decision differs")
    require(timestamp(envelope["created_at"]) <= timestamp(at), "future evidence envelope")
    require(type(envelope["items"]) is list and bool(envelope["items"]), "evidence items must be nonempty")
    for item in envelope["items"]:
        _object(item, ITEM_FIELDS, "evidence item")
        for field in ("evidence_id", "evidence_type", "source", "schema_version"):
            _text(item[field], field)
        _hash(item["provenance_hash"], "provenance_hash")
        require(timestamp(item["observed_at"]) <= timestamp(item["available_at"]),
                "evidence observed after availability")
        require(type(item["requested_for_use"]) is bool, "requested_for_use must be boolean")
    require(len({i["evidence_id"] for i in envelope["items"]}) == len(envelope["items"]),
            "duplicate evidence ID")


def _scope(policy, proposal):
    if policy["capacity_scope"] == "subject":
        return proposal["subject_id"]
    if policy["capacity_scope"] == "session":
        return proposal["session_id"]
    return proposal["subject_id"] + "::" + proposal["session_id"]


def _evidence_sets(policy, proposal, envelope):
    rules = {rule["evidence_type"]: rule for rule in policy["evidence_rules"]}
    decision_time = timestamp(proposal["proposed_at"])
    admitted, used, excluded, used_types = [], [], [], set()
    for item in envelope["items"]:
        rule = rules.get(item["evidence_type"])
        age = (decision_time - timestamp(item["observed_at"])).total_seconds()
        eligible = (rule is not None and item["source"] in rule["allowed_sources"] and
                    item["schema_version"] in rule["allowed_schema_versions"] and
                    timestamp(item["available_at"]) <= decision_time and
                    0 <= age <= rule["max_age_seconds"])
        if eligible:
            admitted.append(item["evidence_id"])
            if item["requested_for_use"] and rule["use_allowed"]:
                used.append(item["evidence_id"])
                used_types.add(item["evidence_type"])
        else:
            excluded.append(item["evidence_id"])
    return sorted(admitted), sorted(used), sorted(excluded), used_types


def _claims(policy, route, reason, used_types):
    return sorted(rule["claim_id"] for rule in policy["claim_rules"]
                  if route in rule["routes"] and
                  (not rule["reason_codes"] or reason in rule["reason_codes"]) and
                  set(rule["required_evidence_types"]) <= used_types)


class _Connection(sqlite3.Connection):
    """Also close a constructor's context-managed connection on Windows."""

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Adapter(DeliveryAdapter):
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30.0, isolation_level=None, factory=_Connection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def __init__(self, db_path, policy=None):
        super().__init__(db_path)
        db = self._connect()
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS requests(
                decision_id TEXT PRIMARY KEY, request_json TEXT NOT NULL,
                request_hash TEXT NOT NULL, received_at TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('received','issued','nonaction','cancelled')),
                permit_json TEXT, cancelled_at TEXT)""")
            if policy is not None:
                validate_policy(policy)
                doc, hashed = canonical(policy), digest(policy)
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT * FROM policy").fetchall()
                if old:
                    require(len(old) == 1 and old[0]["document"] == doc and old[0]["digest"] == hashed,
                            "trusted policy cannot be replaced")
                else:
                    db.execute("INSERT INTO policy(id,revision,digest,document) VALUES(?,?,?,?)",
                               (policy["policy_id"], policy["revision"], hashed, doc))
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _active(db, policy, at):
        row = db.execute("SELECT * FROM policy WHERE id=?", (policy["policy_id"],)).fetchone()
        require(row is not None and not row["revoked"], "trusted policy absent or revoked")
        require(row["document"] == canonical(policy) and row["digest"] == digest(policy) and
                row["revision"] == policy["revision"], "request policy differs from active trusted policy")
        require(timestamp(policy["effective_from"]) <= timestamp(at) < timestamp(policy["expires_at"]),
                "policy is not currently valid")

    def ingest(self, request, at):
        validate_request(request, at)
        now = _time(at)
        document, hashed = canonical(request), digest(request)
        decision_id = request["proposal"]["decision_id"]
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._active(db, request["policy"], now)
            old = db.execute("SELECT * FROM requests WHERE decision_id=?", (decision_id,)).fetchone()
            if old:
                require(old["request_json"] == document and old["request_hash"] == hashed,
                        "decision ID reused with different raw request")
            else:
                db.execute("INSERT INTO requests VALUES(?,?,?,?,'received',NULL,NULL)",
                           (decision_id, document, hashed, now))
            row = db.execute("SELECT * FROM requests WHERE decision_id=?", (decision_id,)).fetchone()
            db.commit()
            return dict(row)
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _reserve(db, policy, scope, resource, decision_id, request_hash, now):
        key = (policy["policy_id"], policy["revision"], scope, resource)
        limit = policy[resource + "_capacity"]
        db.execute("INSERT OR IGNORE INTO budgets VALUES(?,?,?,?,?,0,0,0)", (*key, limit))
        budget = db.execute("SELECT * FROM budgets WHERE policy_id=? AND policy_revision=? AND scope_key=? AND resource=?", key).fetchone()
        require(budget["ceiling"] == limit, "capacity ceiling differs")
        if budget["held"] + budget["spent"] >= limit:
            return None
        before = budget["state_revision"]
        db.execute("UPDATE budgets SET held=held+1,state_revision=state_revision+1 WHERE policy_id=? AND policy_revision=? AND scope_key=? AND resource=?", key)
        hold = dict(reservation_id="ordinary-hold-" + digest({"key": key, "decision_id": decision_id})[:32],
                    policy_id=policy["policy_id"], policy_revision=policy["revision"],
                    policy_hash=digest(policy), scope_key=scope, resource=resource, amount=1,
                    request_hash=request_hash, idempotency_key=decision_id, status="reserved",
                    created_at=now, updated_at=now,
                    lease_expires_at=_time((timestamp(now) + timedelta(seconds=60)).isoformat()),
                    pre_state_revision=before, post_state_revision=before + 1,
                    permit_id=None, permit_hash=None)
        db.execute("INSERT INTO holds VALUES(?,?,'reserved')", (hold["reservation_id"], canonical(hold)))
        return hold

    @staticmethod
    def _release(db, hold, now):
        key = tuple(hold[k] for k in ("policy_id", "policy_revision", "scope_key", "resource"))
        row = db.execute("SELECT status FROM holds WHERE id=?", (hold["reservation_id"],)).fetchone()
        require(row is not None and row["status"] == "reserved", "cannot release nonreserved hold")
        changed = db.execute("UPDATE budgets SET held=held-?,state_revision=state_revision+1 WHERE policy_id=? AND policy_revision=? AND scope_key=? AND resource=? AND held>=?",
                             (hold["amount"], *key, hold["amount"]))
        require(changed.rowcount == 1, "release cannot find held budget")
        hold.update(status="released", updated_at=now)
        db.execute("UPDATE holds SET status='released',document=? WHERE id=?", (canonical(hold), hold["reservation_id"]))

    def issue(self, decision_id, at, hook=None):
        now = _time(at)
        checkpoint = hook if hook is not None else lambda name: None
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute("SELECT * FROM requests WHERE decision_id=?", (decision_id,)).fetchone()
            require(saved is not None, "request was not durably ingested")
            if saved["state"] == "cancelled":
                db.commit()
                return None
            if saved["state"] in ("issued", "nonaction"):
                require(saved["permit_json"] is not None, "issued request lost full permit")
                permit = json.loads(saved["permit_json"])
                registered = db.execute("SELECT * FROM permit_registry WHERE id=?", (permit["permit_id"],)).fetchone()
                require(registered is not None and registered["digest"] == digest(permit), "stored permit registry differs")
                db.commit()
                return permit
            request = json.loads(saved["request_json"])
            require(digest(request) == saved["request_hash"], "durable request hash differs")
            require(timestamp(saved["received_at"]) <= timestamp(now), "issuance precedes request ingestion")
            validate_request(request, now)
            policy, proposal, envelope = (request[k] for k in ("policy", "proposal", "evidence"))
            self._active(db, policy, now)
            scope = _scope(policy, proposal)
            request_hash = digest(dict(policy_hash=digest(policy), proposal_hash=digest(proposal),
                                       evidence_hash=digest(envelope), scope_key=scope))
            admitted, used, excluded, used_types = _evidence_sets(policy, proposal, envelope)
            hold = None
            if not used:
                route, reason = "abstain", "no_policy_admitted_evidence_for_use"
            elif proposal["uncertainty"] >= policy["uncertainty_threshold"]:
                route, reason = "abstain", "uncertainty_gate"
            else:
                distance = abs(proposal["score"] - policy["score_threshold"])
                if distance <= policy["review_band_width"]:
                    resource = "review"
                elif proposal["score"] > policy["score_threshold"] + policy["review_band_width"]:
                    resource = "alert"
                else:
                    resource = None
                if resource:
                    hold = self._reserve(db, policy, scope, resource, decision_id, request_hash, now)
                    if hold is not None:
                        checkpoint("after_reservation")
                        route = resource
                        reason = "score_within_review_band" if resource == "review" else "score_above_review_band"
                    else:
                        route = "abstain" if resource == "review" else "no_action"
                        reason = resource + "_capacity_exhausted"
                else:
                    route, reason = "no_action", "score_below_threshold"
            if route not in policy["allowed_routes"]:
                if hold is not None:
                    self._release(db, hold, now)
                    checkpoint("after_release")
                    hold = None
                require("no_action" in policy["allowed_routes"], "computed route and fail-closed no_action excluded")
                route, reason = "no_action", "route_not_authorized_by_policy"
            claims = _claims(policy, route, reason, used_types)
            if route in ACTIONS and not claims:
                self._release(db, hold, now)
                checkpoint("after_release")
                hold = None
                if "abstain" in policy["allowed_routes"]:
                    route = "abstain"
                else:
                    require("no_action" in policy["allowed_routes"], "unsupported action has no allowed fallback")
                    route = "no_action"
                reason = "no_claim_supported_by_used_evidence"
                claims = _claims(policy, route, reason, used_types)
            blocked = sorted(set(policy["blocked_claim_ids"]) |
                             ({r["claim_id"] for r in policy["claim_rules"]} - set(claims)))
            permit = dict(permit_id="ordinary-permit-" + digest({"decision_id": decision_id, "request_hash": request_hash})[:32],
                          decision_id=decision_id, policy_id=policy["policy_id"], policy_revision=policy["revision"],
                          policy_hash=digest(policy), proposal_hash=digest(proposal), evidence_hash=digest(envelope),
                          request_hash=request_hash, route=route, reason_code=reason, issued_at=now,
                          expires_at=_time(min(timestamp(now) + timedelta(seconds=3600), timestamp(policy["expires_at"])).isoformat()),
                          pre_state_revision=hold["pre_state_revision"] if hold else 0,
                          post_state_revision=hold["post_state_revision"] if hold else 0,
                          reservation_id=hold["reservation_id"] if hold else None,
                          reserved_resource=hold["resource"] if hold else None,
                          admitted_evidence_ids=admitted, used_evidence_ids=used, excluded_evidence_ids=excluded,
                          permitted_claim_ids=claims, blocked_claim_ids=blocked)
            hashed = digest(permit)
            if hold:
                hold.update(permit_id=permit["permit_id"], permit_hash=hashed)
                db.execute("UPDATE holds SET document=? WHERE id=?", (canonical(hold), hold["reservation_id"]))
            registration = {key: permit[key] for key in (
                "permit_id", "decision_id", "policy_id", "policy_revision", "policy_hash",
                "request_hash", "reservation_id", "route", "reason_code", "issued_at")}
            registration.update(permit_hash=hashed, registered_at=now)
            db.execute("INSERT INTO permit_registry VALUES(?,?,?,?)",
                       (permit["permit_id"], hashed, canonical(permit), canonical(registration)))
            state = "issued" if route in ACTIONS else "nonaction"
            db.execute("UPDATE requests SET state=?,permit_json=? WHERE decision_id=?",
                       (state, canonical(permit), decision_id))
            checkpoint("before_issue_commit")
            db.commit()
            checkpoint("after_issue_commit")
            return permit
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get_request(self, decision_id):
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM requests WHERE decision_id=?", (decision_id,)).fetchone()
            return dict(row) if row else None
        finally:
            db.close()

    def get_permit(self, decision_id):
        row = self.get_request(decision_id)
        return json.loads(row["permit_json"]) if row and row["permit_json"] is not None else None

    def cleanup(self, at):
        now = _time(at)
        result = {"cancelled_received": [], "cancelled_issued": [], "retained_armed": []}
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT * FROM requests ORDER BY decision_id").fetchall():
                if row["state"] == "received" and timestamp(row["received_at"]) + timedelta(seconds=60) <= timestamp(now):
                    db.execute("UPDATE requests SET state='cancelled',cancelled_at=? WHERE decision_id=?", (now, row["decision_id"]))
                    result["cancelled_received"].append(row["decision_id"])
                elif row["state"] == "issued":
                    permit = json.loads(row["permit_json"])
                    if timestamp(permit["expires_at"]) > timestamp(now):
                        continue
                    job = db.execute("SELECT * FROM delivery WHERE permit_id=?", (permit["permit_id"],)).fetchone()
                    if job is not None:
                        result["retained_armed"].append(row["decision_id"])
                        continue
                    hold_row = db.execute("SELECT * FROM holds WHERE id=?", (permit["reservation_id"],)).fetchone()
                    require(hold_row is not None, "expired permit lost hold")
                    hold = json.loads(hold_row["document"])
                    require(hold["permit_id"] == permit["permit_id"] and hold["permit_hash"] == digest(permit),
                            "cleanup hold does not bind issued permit")
                    self._release(db, hold, now)
                    db.execute("UPDATE requests SET state='cancelled',cancelled_at=? WHERE decision_id=?", (now, row["decision_id"]))
                    result["cancelled_issued"].append(row["decision_id"])
            db.commit()
            return result
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def snapshot(self):
        # One read transaction covers all normalized rows, avoiding a mixed
        # snapshot when an issuer and delivery worker run concurrently.
        db = self._connect()
        try:
            db.execute("BEGIN")
            budgets = [dict(r) for r in db.execute("SELECT * FROM budgets ORDER BY policy_id,policy_revision,scope_key,resource")]
            jobs = [dict(r) for r in db.execute("SELECT * FROM delivery ORDER BY permit_id")]
            result = dict(n_receipts=db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0],
                          n_armed=sum(j["state"] == "armed" for j in jobs),
                          n_receipted=sum(j["state"] == "receipted" for j in jobs),
                          n_jobs=len(jobs), reserved=sum(b["held"] for b in budgets),
                          committed=sum(b["spent"] for b in budgets),
                          capacity_limit=sum(b["ceiling"] for b in budgets), budgets=budgets, jobs=jobs)
            result["capacity_rows"] = [
                {**{k: row[k] for k in ("policy_id", "policy_revision", "scope_key", "resource", "state_revision")},
                 "reserved": row["held"], "committed": row["spent"], "capacity_limit": row["ceiling"]}
                for row in budgets]
            result["requests"] = [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY decision_id")]
            result["permits"] = [json.loads(r["document"]) for r in db.execute("SELECT * FROM permit_registry ORDER BY id")]
            result["reservations"] = [json.loads(r["document"]) for r in db.execute("SELECT * FROM holds ORDER BY id")]
            db.commit()
            return result
        finally:
            db.close()
