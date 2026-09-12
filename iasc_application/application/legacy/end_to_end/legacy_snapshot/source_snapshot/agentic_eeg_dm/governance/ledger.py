"""SQLite-backed transactional policy and capacity state for ECRC permits."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from .canonical import canonical_json, normalize_timestamp, parse_timestamp, stable_id
from .exceptions import (
    CapacityExceededError,
    IdempotencyConflictError,
    InvalidPermitError,
    PermitReplayError,
    PolicyExpiredError,
    PolicyNotRegisteredError,
    PolicyNotYetEffectiveError,
    ReservationStateError,
    RevokedPolicyError,
    StalePolicyError,
)
from .models import (
    ACTION_ROUTES,
    GENESIS_RECEIPT_HASH,
    DecisionPermit,
    ExecutionReceipt,
    PolicyManifest,
)


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    idempotency_key: str
    request_hash: str
    policy_id: str
    policy_revision: int
    policy_hash: str
    scope_key: str
    resource: str
    amount: int
    status: str
    pre_state_revision: int
    post_state_revision: int
    created_at: str
    updated_at: str
    lease_expires_at: str
    permit_id: str | None = None
    permit_hash: str | None = None


@dataclass(frozen=True)
class CapacitySnapshot:
    policy_id: str
    policy_revision: int
    scope_key: str
    resource: str
    capacity_limit: int
    reserved: int
    committed: int
    state_revision: int

    @property
    def available(self) -> int:
        return self.capacity_limit - self.reserved - self.committed


@dataclass(frozen=True)
class LedgerCounts:
    issued_permits: int
    reservations_reserved: int
    reservations_committed: int
    reservations_released: int
    executions: int
    receipts: int


class SQLiteCapacityLedger:
    """Transactional resource ledger with policy and idempotency checks.

    A fresh SQLite connection is used per operation so one ledger instance can
    safely be shared by worker threads. ``BEGIN IMMEDIATE`` serializes competing
    reservations at the capacity boundary.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        timeout_seconds: float = 30.0,
        reservation_lease_seconds: int = 30,
    ) -> None:
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError(
                "SQLiteCapacityLedger requires a file-backed database so its "
                "per-operation connections share transactional state"
            )
        self.timeout_seconds = float(timeout_seconds)
        if (
            not isinstance(reservation_lease_seconds, int)
            or isinstance(reservation_lease_seconds, bool)
            or reservation_lease_seconds <= 0
        ):
            raise ValueError("reservation_lease_seconds must be a positive integer")
        self.reservation_lease_seconds = reservation_lease_seconds
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.timeout_seconds,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(self.timeout_seconds * 1000)}")
        return connection

    def _initialize(self) -> None:
        path = Path(self.path)
        if self.path != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            if self.path != ":memory:":
                connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS active_policies (
                    policy_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    policy_hash TEXT NOT NULL,
                    effective_from TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    manifest_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS capacity_state (
                    policy_id TEXT NOT NULL,
                    policy_revision INTEGER NOT NULL,
                    scope_key TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    capacity_limit INTEGER NOT NULL,
                    reserved INTEGER NOT NULL DEFAULT 0,
                    committed INTEGER NOT NULL DEFAULT 0,
                    state_revision INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (policy_id, policy_revision, scope_key, resource)
                );

                CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_hash TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    policy_revision INTEGER NOT NULL,
                    policy_hash TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    pre_state_revision INTEGER NOT NULL,
                    post_state_revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lease_expires_at TEXT,
                    permit_id TEXT,
                    permit_hash TEXT
                );

                CREATE TABLE IF NOT EXISTS executions (
                    permit_id TEXT PRIMARY KEY,
                    permit_hash TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    receipt_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS issued_permits (
                    permit_id TEXT PRIMARY KEY,
                    permit_hash TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    policy_revision INTEGER NOT NULL,
                    policy_hash TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    reservation_id TEXT,
                    route TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    UNIQUE (policy_id, policy_revision, decision_id)
                );

                CREATE TABLE IF NOT EXISTS receipt_log (
                    sequence_no INTEGER PRIMARY KEY,
                    receipt_id TEXT NOT NULL UNIQUE,
                    permit_id TEXT NOT NULL UNIQUE,
                    previous_receipt_hash TEXT NOT NULL,
                    receipt_hash TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                );
                """
            )
            reservation_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(reservations)")
            }
            if "lease_expires_at" not in reservation_columns:
                connection.execute(
                    "ALTER TABLE reservations ADD COLUMN lease_expires_at TEXT"
                )
            connection.execute(
                """
                UPDATE reservations
                SET lease_expires_at = updated_at
                WHERE lease_expires_at IS NULL
                """
            )

    def register_issued_permit(self, permit: DecisionPermit, *, at: str) -> None:
        """Bind an adjudicator-produced permit hash to trusted SQLite state."""

        now = normalize_timestamp(at)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM issued_permits WHERE permit_id = ?", (permit.permit_id,)
            ).fetchone()
            if existing is not None:
                if str(existing["permit_hash"]) != permit.content_hash:
                    raise InvalidPermitError(
                        "permit ID is already bound to different content"
                    )
                connection.commit()
                return

            if permit.reservation_id is not None:
                reservation = connection.execute(
                    "SELECT * FROM reservations WHERE reservation_id = ?",
                    (permit.reservation_id,),
                ).fetchone()
                if reservation is None:
                    raise InvalidPermitError("permit references an unknown reservation")
                if str(reservation["status"]) != "reserved":
                    raise InvalidPermitError("permit reservation is not pending")
                if parse_timestamp(now) >= parse_timestamp(
                    str(reservation["lease_expires_at"])
                ):
                    raise InvalidPermitError("permit reservation lease has expired")
                if (
                    str(reservation["request_hash"]) != permit.request_hash
                    or str(reservation["policy_id"]) != permit.policy_id
                    or int(reservation["policy_revision"]) != permit.policy_revision
                    or str(reservation["policy_hash"]) != permit.policy_hash
                    or str(reservation["resource"]) != permit.route
                    or int(reservation["pre_state_revision"])
                    != permit.pre_state_revision
                    or int(reservation["post_state_revision"])
                    != permit.post_state_revision
                ):
                    raise InvalidPermitError(
                        "issued permit does not match its reservation binding"
                    )
                bound_id = reservation["permit_id"]
                bound_hash = reservation["permit_hash"]
                if bound_id is not None and (
                    str(bound_id) != permit.permit_id
                    or str(bound_hash) != permit.content_hash
                ):
                    raise InvalidPermitError(
                        "reservation is already bound to a different permit"
                    )
                connection.execute(
                    """
                    UPDATE reservations SET permit_id = ?, permit_hash = ?
                    WHERE reservation_id = ?
                    """,
                    (permit.permit_id, permit.content_hash, permit.reservation_id),
                )

            try:
                connection.execute(
                    """
                    INSERT INTO issued_permits (
                        permit_id, permit_hash, decision_id, policy_id,
                        policy_revision, policy_hash, request_hash,
                        reservation_id, route, reason_code, issued_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        permit.permit_id,
                        permit.content_hash,
                        permit.decision_id,
                        permit.policy_id,
                        permit.policy_revision,
                        permit.policy_hash,
                        permit.request_hash,
                        permit.reservation_id,
                        permit.route,
                        permit.reason_code,
                        permit.issued_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise InvalidPermitError(
                    "a different permit is already issued for this policy decision"
                ) from exc
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def assert_issued_permit(self, permit: DecisionPermit) -> None:
        with closing(self._connect()) as connection:
            self._assert_issued_permit_conn(connection, permit)

    @staticmethod
    def _assert_issued_permit_conn(
        connection: sqlite3.Connection, permit: DecisionPermit
    ) -> None:
        issued = connection.execute(
            "SELECT * FROM issued_permits WHERE permit_id = ?", (permit.permit_id,)
        ).fetchone()
        if issued is None:
            raise InvalidPermitError("permit was not issued by the trusted registry")
        expected = {
            "permit_hash": permit.content_hash,
            "decision_id": permit.decision_id,
            "policy_id": permit.policy_id,
            "policy_revision": permit.policy_revision,
            "policy_hash": permit.policy_hash,
            "request_hash": permit.request_hash,
            "reservation_id": permit.reservation_id,
            "route": permit.route,
            "reason_code": permit.reason_code,
            "issued_at": permit.issued_at,
        }
        for field, value in expected.items():
            stored = issued[field]
            if stored is None and value is None:
                continue
            if str(stored) != str(value):
                raise InvalidPermitError(
                    f"permit {field} does not match the trusted issued-permit registry"
                )

    def register_policy(self, manifest: PolicyManifest) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision, policy_hash FROM active_policies WHERE policy_id = ?",
                (manifest.policy_id,),
            ).fetchone()
            if current is None:
                connection.execute(
                    """
                    INSERT INTO active_policies (
                        policy_id, revision, policy_hash, effective_from,
                        expires_at, revoked, manifest_json
                    ) VALUES (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        manifest.policy_id,
                        manifest.revision,
                        manifest.policy_hash,
                        manifest.effective_from,
                        manifest.expires_at,
                        canonical_json(manifest),
                    ),
                )
            elif (
                int(current["revision"]) == manifest.revision
                and str(current["policy_hash"]) == manifest.policy_hash
            ):
                connection.commit()
                return
            elif manifest.revision <= int(current["revision"]):
                raise StalePolicyError(
                    f"policy {manifest.policy_id!r} revision {manifest.revision} is not newer "
                    f"than active revision {current['revision']}"
                )
            else:
                connection.execute(
                    """
                    UPDATE active_policies
                    SET revision = ?, policy_hash = ?, effective_from = ?,
                        expires_at = ?, revoked = 0, manifest_json = ?
                    WHERE policy_id = ?
                    """,
                    (
                        manifest.revision,
                        manifest.policy_hash,
                        manifest.effective_from,
                        manifest.expires_at,
                        canonical_json(manifest),
                        manifest.policy_id,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def revoke_policy(self, policy_id: str, *, expected_revision: int) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision FROM active_policies WHERE policy_id = ?", (policy_id,)
            ).fetchone()
            if current is None:
                raise PolicyNotRegisteredError(
                    f"policy {policy_id!r} is not registered"
                )
            if int(current["revision"]) != expected_revision:
                raise StalePolicyError(
                    f"cannot revoke revision {expected_revision}; active revision is "
                    f"{current['revision']}"
                )
            connection.execute(
                "UPDATE active_policies SET revoked = 1 WHERE policy_id = ?",
                (policy_id,),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def assert_policy_usable(self, manifest: PolicyManifest, *, at: str) -> None:
        with closing(self._connect()) as connection:
            self._assert_policy_usable_conn(
                connection, manifest, normalize_timestamp(at)
            )

    @staticmethod
    def _assert_policy_usable_conn(
        connection: sqlite3.Connection,
        manifest: PolicyManifest,
        at: str,
    ) -> None:
        current = connection.execute(
            """
            SELECT revision, policy_hash, effective_from, expires_at, revoked
            FROM active_policies WHERE policy_id = ?
            """,
            (manifest.policy_id,),
        ).fetchone()
        if current is None:
            raise PolicyNotRegisteredError(
                f"policy {manifest.policy_id!r} is not registered"
            )
        if (
            int(current["revision"]) != manifest.revision
            or str(current["policy_hash"]) != manifest.policy_hash
        ):
            raise StalePolicyError(
                f"policy {manifest.policy_id!r} revision/hash is not the active revision"
            )
        if bool(current["revoked"]):
            raise RevokedPolicyError(f"policy {manifest.policy_id!r} is revoked")
        instant = parse_timestamp(at)
        if instant < parse_timestamp(str(current["effective_from"])):
            raise PolicyNotYetEffectiveError(
                f"policy {manifest.policy_id!r} is not yet effective"
            )
        if instant >= parse_timestamp(str(current["expires_at"])):
            raise PolicyExpiredError(f"policy {manifest.policy_id!r} has expired")

    @staticmethod
    def _capacity_limit(manifest: PolicyManifest, resource: str) -> int:
        if resource == "alert":
            return manifest.alert_capacity
        if resource == "review":
            return manifest.review_capacity
        raise ValueError("resource must be 'alert' or 'review'")

    def reserve(
        self,
        manifest: PolicyManifest,
        *,
        scope_key: str,
        resource: str,
        idempotency_key: str,
        request_hash: str,
        at: str,
    ) -> Reservation:
        now = normalize_timestamp(at)
        capacity_limit = self._capacity_limit(manifest, resource)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_policy_usable_conn(connection, manifest, now)
            existing = connection.execute(
                "SELECT * FROM reservations WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                comparable = (
                    str(existing["request_hash"]) == request_hash
                    and str(existing["policy_id"]) == manifest.policy_id
                    and int(existing["policy_revision"]) == manifest.revision
                    and str(existing["policy_hash"]) == manifest.policy_hash
                    and str(existing["scope_key"]) == scope_key
                    and str(existing["resource"]) == resource
                    and int(existing["amount"]) == 1
                )
                if not comparable:
                    raise IdempotencyConflictError(
                        "idempotency key was already used for a different request"
                    )
                connection.commit()
                return self._reservation_from_row(existing)

            connection.execute(
                """
                INSERT OR IGNORE INTO capacity_state (
                    policy_id, policy_revision, scope_key, resource,
                    capacity_limit, reserved, committed, state_revision
                ) VALUES (?, ?, ?, ?, ?, 0, 0, 0)
                """,
                (
                    manifest.policy_id,
                    manifest.revision,
                    scope_key,
                    resource,
                    capacity_limit,
                ),
            )
            state = connection.execute(
                """
                SELECT * FROM capacity_state
                WHERE policy_id = ? AND policy_revision = ?
                  AND scope_key = ? AND resource = ?
                """,
                (manifest.policy_id, manifest.revision, scope_key, resource),
            ).fetchone()
            if state is None:
                raise RuntimeError("capacity state initialization failed")
            if int(state["capacity_limit"]) != capacity_limit:
                raise StalePolicyError(
                    "capacity state does not match the active manifest"
                )
            available = (
                int(state["capacity_limit"])
                - int(state["reserved"])
                - int(state["committed"])
            )
            if available < 1:
                raise CapacityExceededError(
                    f"{resource} capacity exhausted for scope {scope_key!r}"
                )

            pre_revision = int(state["state_revision"])
            post_revision = pre_revision + 1
            lease_expires_at = normalize_timestamp(
                (
                    parse_timestamp(now)
                    + timedelta(seconds=self.reservation_lease_seconds)
                ).isoformat()
            )
            connection.execute(
                """
                UPDATE capacity_state
                SET reserved = reserved + 1, state_revision = ?
                WHERE policy_id = ? AND policy_revision = ?
                  AND scope_key = ? AND resource = ?
                """,
                (
                    post_revision,
                    manifest.policy_id,
                    manifest.revision,
                    scope_key,
                    resource,
                ),
            )
            reservation_id = stable_id(
                "res",
                {
                    "idempotency_key": idempotency_key,
                    "request_hash": request_hash,
                    "policy_hash": manifest.policy_hash,
                    "resource": resource,
                },
            )
            connection.execute(
                """
                INSERT INTO reservations (
                    reservation_id, idempotency_key, request_hash, policy_id,
                    policy_revision, policy_hash, scope_key, resource, amount,
                    status, pre_state_revision, post_state_revision,
                    created_at, updated_at, lease_expires_at, permit_id, permit_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'reserved', ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    reservation_id,
                    idempotency_key,
                    request_hash,
                    manifest.policy_id,
                    manifest.revision,
                    manifest.policy_hash,
                    scope_key,
                    resource,
                    pre_revision,
                    post_revision,
                    now,
                    now,
                    lease_expires_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM reservations WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            connection.commit()
            if row is None:
                raise RuntimeError("reservation insert failed")
            return self._reservation_from_row(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reap_expired_reservations(self, *, at: str) -> tuple[Reservation, ...]:
        """Release expired, still-unissued reservations in one transaction.

        Issued or committed reservations are never reaped. The original
        idempotency key remains closed after recovery so an ambiguous crashed
        request cannot be silently resurrected; a new decision may use the
        recovered capacity.
        """

        now = normalize_timestamp(at)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            expired = connection.execute(
                """
                SELECT reservations.*
                FROM reservations
                WHERE reservations.status = 'reserved'
                  AND reservations.permit_id IS NULL
                  AND reservations.lease_expires_at <= ?
                  AND NOT EXISTS (
                      SELECT 1 FROM issued_permits
                      WHERE issued_permits.reservation_id = reservations.reservation_id
                  )
                ORDER BY reservations.reservation_id
                """,
                (now,),
            ).fetchall()
            released = tuple(
                self._release_reservation_conn(
                    connection, str(row["reservation_id"]), at=now
                )
                for row in expired
            )
            connection.commit()
            return released
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit(
        self,
        reservation_id: str,
        *,
        permit_id: str,
        permit_hash: str,
        at: str,
    ) -> Reservation:
        """Low-level idempotent reservation commit.

        Normal simulated execution should use :class:`PEPSimulator`, which
        commits the reservation and appends its execution receipt atomically.
        """

        now = normalize_timestamp(at)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            reservation = self._commit_reservation_conn(
                connection,
                reservation_id,
                permit_id=permit_id,
                permit_hash=permit_hash,
                at=now,
            )
            connection.commit()
            return reservation
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _commit_reservation_conn(
        self,
        connection: sqlite3.Connection,
        reservation_id: str,
        *,
        permit_id: str,
        permit_hash: str,
        at: str,
    ) -> Reservation:
        row = connection.execute(
            "SELECT * FROM reservations WHERE reservation_id = ?", (reservation_id,)
        ).fetchone()
        if row is None:
            raise ReservationStateError(f"unknown reservation {reservation_id!r}")
        if str(row["status"]) == "committed":
            if (
                str(row["permit_id"]) == permit_id
                and str(row["permit_hash"]) == permit_hash
            ):
                return self._reservation_from_row(row)
            raise ReservationStateError(
                "reservation was committed to a different permit"
            )
        if str(row["status"]) != "reserved":
            raise ReservationStateError(
                f"reservation cannot be committed from status {row['status']!r}"
            )
        if (
            row["permit_id"] is None
            or str(row["permit_id"]) != permit_id
            or str(row["permit_hash"]) != permit_hash
        ):
            raise InvalidPermitError(
                "reservation is not bound to this trusted issued permit"
            )
        cursor = connection.execute(
            """
            UPDATE capacity_state
            SET reserved = reserved - ?, committed = committed + ?,
                state_revision = state_revision + 1
            WHERE policy_id = ? AND policy_revision = ?
              AND scope_key = ? AND resource = ? AND reserved >= ?
            """,
            (
                int(row["amount"]),
                int(row["amount"]),
                row["policy_id"],
                row["policy_revision"],
                row["scope_key"],
                row["resource"],
                int(row["amount"]),
            ),
        )
        if cursor.rowcount != 1:
            raise ReservationStateError("capacity state cannot commit reservation")
        connection.execute(
            """
            UPDATE reservations
            SET status = 'committed', updated_at = ?, permit_id = ?, permit_hash = ?
            WHERE reservation_id = ?
            """,
            (at, permit_id, permit_hash, reservation_id),
        )
        updated = connection.execute(
            "SELECT * FROM reservations WHERE reservation_id = ?", (reservation_id,)
        ).fetchone()
        if updated is None:
            raise RuntimeError("reservation disappeared during commit")
        return self._reservation_from_row(updated)

    def release(self, reservation_id: str, *, at: str) -> Reservation:
        now = normalize_timestamp(at)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            reservation = self._release_reservation_conn(
                connection, reservation_id, at=now
            )
            connection.commit()
            return reservation
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _release_reservation_conn(
        self,
        connection: sqlite3.Connection,
        reservation_id: str,
        *,
        at: str,
    ) -> Reservation:
        row = connection.execute(
            "SELECT * FROM reservations WHERE reservation_id = ?", (reservation_id,)
        ).fetchone()
        if row is None:
            raise ReservationStateError(f"unknown reservation {reservation_id!r}")
        if str(row["status"]) == "released":
            return self._reservation_from_row(row)
        if str(row["status"]) != "reserved":
            raise ReservationStateError(
                f"reservation cannot be released from status {row['status']!r}"
            )
        cursor = connection.execute(
            """
            UPDATE capacity_state
            SET reserved = reserved - ?, state_revision = state_revision + 1
            WHERE policy_id = ? AND policy_revision = ?
              AND scope_key = ? AND resource = ? AND reserved >= ?
            """,
            (
                int(row["amount"]),
                row["policy_id"],
                row["policy_revision"],
                row["scope_key"],
                row["resource"],
                int(row["amount"]),
            ),
        )
        if cursor.rowcount != 1:
            raise ReservationStateError("capacity state cannot release reservation")
        connection.execute(
            """
            UPDATE reservations SET status = 'released', updated_at = ?
            WHERE reservation_id = ?
            """,
            (at, reservation_id),
        )
        updated = connection.execute(
            "SELECT * FROM reservations WHERE reservation_id = ?", (reservation_id,)
        ).fetchone()
        if updated is None:
            raise RuntimeError("reservation disappeared during release")
        return self._reservation_from_row(updated)

    def complete_execution(
        self,
        manifest: PolicyManifest,
        permit: DecisionPermit,
        *,
        at: str,
        enforcement_point_id: str,
        failure_reason: str | None = None,
    ) -> ExecutionReceipt:
        """Atomically consume a permit, transition capacity, and append a receipt."""

        now = normalize_timestamp(at)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_policy_usable_conn(connection, manifest, now)
            self._assert_issued_permit_conn(connection, permit)
            if connection.execute(
                "SELECT 1 FROM executions WHERE permit_id = ?", (permit.permit_id,)
            ).fetchone():
                raise PermitReplayError(
                    f"permit {permit.permit_id!r} was already consumed"
                )

            if failure_reason is not None:
                if permit.reservation_id is not None:
                    self._release_reservation_conn(
                        connection, permit.reservation_id, at=now
                    )
                execution_status = "failed"
                side_effect_id = None
            elif permit.route in ACTION_ROUTES:
                if permit.reservation_id is None:
                    raise InvalidPermitError("action permit is missing its reservation")
                reservation_row = connection.execute(
                    "SELECT * FROM reservations WHERE reservation_id = ?",
                    (permit.reservation_id,),
                ).fetchone()
                if reservation_row is None:
                    raise InvalidPermitError(
                        "action permit references an unknown reservation"
                    )
                if (
                    str(reservation_row["request_hash"]) != permit.request_hash
                    or str(reservation_row["policy_hash"]) != permit.policy_hash
                    or str(reservation_row["resource"]) != permit.route
                ):
                    raise InvalidPermitError(
                        "permit does not match its capacity reservation"
                    )
                self._commit_reservation_conn(
                    connection,
                    permit.reservation_id,
                    permit_id=permit.permit_id,
                    permit_hash=permit.content_hash,
                    at=now,
                )
                execution_status = "executed"
                side_effect_id = stable_id(
                    "effect",
                    {
                        "permit_id": permit.permit_id,
                        "permit_hash": permit.content_hash,
                        "enforcement_point_id": enforcement_point_id,
                    },
                )
            else:
                if permit.reservation_id is not None:
                    raise InvalidPermitError(
                        "non-action permit must not reserve capacity"
                    )
                execution_status = "not_executed"
                side_effect_id = None

            tail = connection.execute(
                """
                SELECT sequence_no, receipt_hash FROM receipt_log
                ORDER BY sequence_no DESC LIMIT 1
                """
            ).fetchone()
            sequence_no = 1 if tail is None else int(tail["sequence_no"]) + 1
            previous_hash = (
                GENESIS_RECEIPT_HASH if tail is None else str(tail["receipt_hash"])
            )
            receipt_id = stable_id(
                "receipt",
                {
                    "sequence_no": sequence_no,
                    "permit_id": permit.permit_id,
                    "permit_hash": permit.content_hash,
                    "execution_status": execution_status,
                },
            )
            receipt = ExecutionReceipt(
                receipt_id=receipt_id,
                sequence_no=sequence_no,
                permit_id=permit.permit_id,
                permit_hash=permit.content_hash,
                policy_id=permit.policy_id,
                policy_revision=permit.policy_revision,
                route=permit.route,
                execution_status=execution_status,
                side_effect_id=side_effect_id,
                reservation_id=permit.reservation_id,
                executed_at=now,
                enforcement_point_id=enforcement_point_id,
                previous_receipt_hash=previous_hash,
                failure_reason=failure_reason,
            )
            connection.execute(
                """
                INSERT INTO receipt_log (
                    sequence_no, receipt_id, permit_id, previous_receipt_hash,
                    receipt_hash, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.sequence_no,
                    receipt.receipt_id,
                    receipt.permit_id,
                    receipt.previous_receipt_hash,
                    receipt.content_hash,
                    canonical_json(receipt),
                ),
            )
            connection.execute(
                """
                INSERT INTO executions (
                    permit_id, permit_hash, execution_status, receipt_id, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    permit.permit_id,
                    permit.content_hash,
                    execution_status,
                    receipt.receipt_id,
                    now,
                ),
            )
            connection.commit()
            return receipt
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def capacity_snapshot(
        self,
        manifest: PolicyManifest,
        *,
        scope_key: str,
        resource: str,
    ) -> CapacitySnapshot:
        capacity_limit = self._capacity_limit(manifest, resource)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT OR IGNORE INTO capacity_state (
                    policy_id, policy_revision, scope_key, resource,
                    capacity_limit, reserved, committed, state_revision
                ) VALUES (?, ?, ?, ?, ?, 0, 0, 0)
                """,
                (
                    manifest.policy_id,
                    manifest.revision,
                    scope_key,
                    resource,
                    capacity_limit,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM capacity_state
                WHERE policy_id = ? AND policy_revision = ?
                  AND scope_key = ? AND resource = ?
                """,
                (manifest.policy_id, manifest.revision, scope_key, resource),
            ).fetchone()
            connection.commit()
            if row is None:
                raise RuntimeError("capacity state query failed")
            return CapacitySnapshot(
                policy_id=str(row["policy_id"]),
                policy_revision=int(row["policy_revision"]),
                scope_key=str(row["scope_key"]),
                resource=str(row["resource"]),
                capacity_limit=int(row["capacity_limit"]),
                reserved=int(row["reserved"]),
                committed=int(row["committed"]),
                state_revision=int(row["state_revision"]),
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_reservation(self, reservation_id: str) -> Reservation:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM reservations WHERE reservation_id = ?", (reservation_id,)
            ).fetchone()
        if row is None:
            raise ReservationStateError(f"unknown reservation {reservation_id!r}")
        return self._reservation_from_row(row)

    def list_receipts(self) -> tuple[ExecutionReceipt, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT receipt_json FROM receipt_log ORDER BY sequence_no"
            ).fetchall()
        return tuple(
            ExecutionReceipt.from_dict(json.loads(str(row["receipt_json"])))
            for row in rows
        )

    def tail_receipt_hash(self) -> str:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT receipt_hash FROM receipt_log ORDER BY sequence_no DESC LIMIT 1"
            ).fetchone()
        return GENESIS_RECEIPT_HASH if row is None else str(row["receipt_hash"])

    def counts(self) -> LedgerCounts:
        with closing(self._connect()) as connection:
            issued = int(
                connection.execute("SELECT COUNT(*) FROM issued_permits").fetchone()[0]
            )
            status_rows = connection.execute(
                "SELECT status, COUNT(*) AS n FROM reservations GROUP BY status"
            ).fetchall()
            by_status = {str(row["status"]): int(row["n"]) for row in status_rows}
            executions = int(
                connection.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
            )
            receipts = int(
                connection.execute("SELECT COUNT(*) FROM receipt_log").fetchone()[0]
            )
        return LedgerCounts(
            issued_permits=issued,
            reservations_reserved=by_status.get("reserved", 0),
            reservations_committed=by_status.get("committed", 0),
            reservations_released=by_status.get("released", 0),
            executions=executions,
            receipts=receipts,
        )

    @staticmethod
    def _reservation_from_row(row: sqlite3.Row) -> Reservation:
        return Reservation(
            reservation_id=str(row["reservation_id"]),
            idempotency_key=str(row["idempotency_key"]),
            request_hash=str(row["request_hash"]),
            policy_id=str(row["policy_id"]),
            policy_revision=int(row["policy_revision"]),
            policy_hash=str(row["policy_hash"]),
            scope_key=str(row["scope_key"]),
            resource=str(row["resource"]),
            amount=int(row["amount"]),
            status=str(row["status"]),
            pre_state_revision=int(row["pre_state_revision"]),
            post_state_revision=int(row["post_state_revision"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            lease_expires_at=str(row["lease_expires_at"]),
            permit_id=None if row["permit_id"] is None else str(row["permit_id"]),
            permit_hash=None if row["permit_hash"] is None else str(row["permit_hash"]),
        )
