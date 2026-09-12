# Independent local effect service protocol

Fixed on 2026-09-11 before service tests. This is an explicitly controlled local systems experiment. It creates durable sandbox effects in a service-owned SQLite database; no real external account, message or financial effect is involved. The service and client/harness run in distinct processes. The manuscript and original ECRC runtime are not modified.

## Stable CLI and startup

`python service.py --db PATH --port 0`

`--db` is required; `--port` defaults to zero. The server binds only `127.0.0.1`. Port zero requests an operating-system-selected free port. After database initialization and socket binding, stdout emits exactly one flushed JSON readiness line:

```json
{"event":"ready","host":"127.0.0.1","port":12345,"pid":1234,"db":"absolute path","schema_version":1}
```

Routine HTTP access logs do not go to stdout. No GUI, external network listener, or outbound network request is used. Process termination is controlled by the harness; there is no remotely callable shutdown endpoint.

## Stable HTTP schema

`POST /effects` accepts a UTF-8 JSON object with exactly two fields: `idempotency_key`, a nonempty string of at most 512 UTF-8 bytes, and `payload`, a JSON object. The request must have a Content-Length and no transfer encoding; its body may be at most 1 MiB. Invalid JSON, duplicate object keys, nonfinite numeric constants and unsupported values receive 400. This is a narrow test API, not a general JSON canonicalization standard.

The payload's canonical bytes are Python's `json.dumps(payload, sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False).encode("utf-8")`. Its SHA-256 is stored and returned. Consequently key order and whitespace do not change the canonical payload; JSON numbers represented as `1` and `1.0` are distinct under this declared encoding.

First creation returns HTTP 201; replay of the same key and canonical payload returns HTTP 200. Both return:

```json
{"effect_id":1,"idempotency_key":"key","payload_hash":"hex SHA-256","payload":{},"committed_at":"UTC ISO-8601","created":true}
```

For a replay, `created` is false and every durable effect field remains identical. A reused key with different canonical payload returns HTTP 409 with `error="idempotency_conflict"`, the key and the existing/requested payload hashes; it creates no additional effect. Both canonical text and its hash must match for a replay.

`GET /effects/<URL-encoded-key>` returns HTTP 200 and the five durable fields above, without `created`. A missing effect returns 404 with `error="not_found"`. `GET /health` returns HTTP 200 with `{"status":"ok","schema_version":1}`. Every ordinary reply is UTF-8 JSON with an explicit Content-Length and connection close.

## Persistence and concurrency

The independent service database contains table `effects` with `effect_id INTEGER PRIMARY KEY AUTOINCREMENT`, `idempotency_key TEXT UNIQUE NOT NULL`, `payload_hash TEXT NOT NULL`, `payload_json TEXT NOT NULL`, and `committed_at TEXT NOT NULL`. `payload_json` contains the declared canonical JSON text. Every HTTP worker opens its own SQLite connection. WAL, synchronous FULL and a 30-second busy timeout are used.

The complete key lookup, conflict decision and possible insertion run inside one `BEGIN IMMEDIATE` transaction. The transaction commits before a successful HTTP reply or deliberate response loss. The service never reports an effect as committed before the database commit returns. The idempotency uniqueness constraint is enforced in SQLite in addition to the serialized lookup. An unavailable/failed database operation returns 503 without claiming success. Tests exercise process death and restart with the same database, not arbitrary hardware/storage corruption.

Timestamp clarification added during the adapter review, without changing service code: `committed_at` is actual UTC wall-clock time sampled immediately before the effect INSERT and persisted with that effect in the same transaction. It is returned only after successful commit and is stable across replay. It is the sink's durable effect record time, not an instrumentation measurement of the exact instant SQLite commit finishes. Authorization and expiry tests use their separately declared logical clock.

## Controlled unknown-outcome injection

For an otherwise successful `POST /effects`, header `X-Test-Drop-Response: 1` makes the service commit and then shut down and close that TCP connection without sending any HTTP response. The effect remains durable. The same behavior applies to a successful idempotent replay if the header is repeated. Errors/conflicts return their ordinary HTTP responses. This is a deliberately injected response loss; it must not be described as an observed natural failure rate.

No service-kill injection is built into this component. The harness may kill the actual server process and inspect/reopen the service ledger. The response-drop header creates a known commit-before-response window, while the client has no returned outcome. No undocumented timing barrier or delay is needed for the component tests.

## Independent component tests

Tests use Python 3.12 standard-library HTTP clients against real server subprocesses with fresh databases. They preserve their databases and a JSON report under the selected test output directory.

1. Send 20 concurrently released requests with one key and semantically identical object payloads serialized with varied whitespace/key order. Require one 201/created result, 19 200/replay results, identical durable fields, and exactly one SQLite row. Query that effect by URL-encoded key.
2. Reuse one key with a different payload. Require 409, unchanged original payload/hash/effect ID, and one durable row. Retrying the original payload must return the original effect.
3. Inject commit-then-drop-response. Require a client transport failure, independently confirm one committed row, kill the actual service subprocess, restart it using the same database, then query and retry. Require the same effect ID/hash/time and still exactly one row.
4. Check initial health, absent-key 404, and rejection of malformed/non-object payloads, duplicate JSON fields and nonfinite numbers without creating effects.

Record each test outcome, service/test/protocol hashes, Python and SQLite versions, actual durable row counts and subprocess restart behavior. The root harness will separately test end-to-end ECRC/client failure windows and comparison policies.
