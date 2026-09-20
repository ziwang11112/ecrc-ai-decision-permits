"""Independent loopback HTTP sink with durable, payload-bound idempotency.

This sandbox service is separate from the ECRC client/runtime. See
PROTOCOL_SERVICE.md for the precise API and controlled response-loss behavior.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

SCHEMA_VERSION = 1
MAX_BODY_BYTES = 1024 * 1024
MAX_KEY_BYTES = 512


def canonical_payload(payload: dict) -> tuple[str, str]:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)
    encoded = text.encode("utf-8")
    return text, hashlib.sha256(encoded).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def reject_nonfinite(value):
    raise ValueError("nonfinite JSON number")


def valid_key(key):
    return isinstance(key, str) and 0 < len(key.encode("utf-8")) <= MAX_KEY_BYTES


class EffectLedger:
    def __init__(self, db_path: Path):
        self.db_path = db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode.lower() != "wal":
                raise RuntimeError("SQLite WAL mode could not be enabled")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS effects (
                    effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    committed_at TEXT NOT NULL
                )
            """)
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()
        finally:
            connection.close()

    def connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @staticmethod
    def as_effect(row):
        return dict(effect_id=row["effect_id"], idempotency_key=row["idempotency_key"],
                    payload_hash=row["payload_hash"], payload=json.loads(row["payload_json"]),
                    committed_at=row["committed_at"])

    def post(self, key: str, payload_text: str, payload_hash: str):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM effects WHERE idempotency_key=?", (key,)).fetchone()
            if row is not None:
                if row["payload_hash"] != payload_hash or row["payload_json"] != payload_text:
                    connection.rollback()
                    return 409, dict(error="idempotency_conflict", idempotency_key=key,
                                     existing_payload_hash=row["payload_hash"], requested_payload_hash=payload_hash)
                effect = self.as_effect(row)
                connection.commit()
                return 200, dict(effect, created=False)
            committed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            connection.execute("INSERT INTO effects (idempotency_key,payload_hash,payload_json,committed_at) VALUES (?,?,?,?)",
                               (key, payload_hash, payload_text, committed_at))
            row = connection.execute("SELECT * FROM effects WHERE idempotency_key=?", (key,)).fetchone()
            # No success response, or deliberate connection loss, is possible
            # until this transaction has committed successfully.
            connection.commit()
            return 201, dict(self.as_effect(row), created=True)
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
            return None if row is None else self.as_effect(row)
        finally:
            connection.close()


class EffectServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def __init__(self, address, ledger):
        self.ledger = ledger
        super().__init__(address, EffectHandler)


class EffectHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LocalEffectSink/1"

    def log_message(self, format, *args):
        # Stdout is reserved for the one machine-readable readiness message.
        pass

    def reply(self, code, value):
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # The ledger remains committed if the peer disappears after commit.
            pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            self.reply(200, dict(status="ok", schema_version=SCHEMA_VERSION))
            return
        if not path.startswith("/effects/"):
            self.reply(404, dict(error="not_found"))
            return
        try:
            key = unquote(path[len("/effects/"):], encoding="utf-8", errors="strict")
            if not valid_key(key):
                raise ValueError("invalid key")
        except (ValueError, UnicodeError):
            self.reply(400, dict(error="invalid_idempotency_key"))
            return
        try:
            effect = self.server.ledger.get(key)
        except sqlite3.Error:
            self.reply(503, dict(error="storage_error"))
            return
        self.reply(404, dict(error="not_found")) if effect is None else self.reply(200, effect)

    def do_POST(self):
        if urlsplit(self.path).path != "/effects":
            self.reply(404, dict(error="not_found"))
            return
        try:
            if self.headers.get("Transfer-Encoding") is not None:
                raise ValueError("transfer encoding unsupported")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isdigit():
                raise ValueError("one Content-Length is required")
            length = int(lengths[0])
            if not 0 < length <= MAX_BODY_BYTES:
                raise ValueError("invalid body length")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete body")
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                               parse_constant=reject_nonfinite)
            if not isinstance(value, dict) or set(value) != {"idempotency_key", "payload"}:
                raise ValueError("invalid request object")
            if not valid_key(value["idempotency_key"]) or not isinstance(value["payload"], dict):
                raise ValueError("invalid key or payload")
            text, payload_hash = canonical_payload(value["payload"])
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
            self.reply(400, dict(error="invalid_request"))
            return
        try:
            code, response = self.server.ledger.post(value["idempotency_key"], text, payload_hash)
        except sqlite3.Error:
            self.reply(503, dict(error="storage_error"))
            return
        if code in (200, 201) and self.headers.get("X-Test-Drop-Response", "").strip() == "1":
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
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    ledger = EffectLedger(args.db)
    server = EffectServer(("127.0.0.1", args.port), ledger)
    print(json.dumps(dict(event="ready", host="127.0.0.1", port=server.server_port,
                          pid=os.getpid(), db=str(ledger.db_path), schema_version=SCHEMA_VERSION)), flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
