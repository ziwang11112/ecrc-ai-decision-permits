"""Canonical serialization helpers for ECRC governance artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def parse_timestamp(value: str) -> datetime:
    """Parse an RFC 3339/ISO-8601 timestamp and require an explicit timezone."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty string")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def normalize_timestamp(value: str) -> str:
    """Return a stable UTC timestamp representation used in hashes."""

    parsed = parse_timestamp(value)
    rendered = parsed.isoformat(timespec="microseconds")
    return rendered.replace("+00:00", "Z")


def utc_now() -> str:
    return normalize_timestamp(datetime.now(timezone.utc).isoformat())


def to_primitive(value: Any) -> Any:
    """Convert supported values to a deterministic JSON-compatible structure."""

    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_primitive(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Enum):
        return to_primitive(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("datetime values must include a timezone")
        return normalize_timestamp(value.isoformat())
    if isinstance(value, Mapping):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_primitive(item) for item in value]
    if isinstance(value, (set, frozenset)):
        converted = [to_primitive(item) for item in value]
        return sorted(converted, key=lambda item: canonical_json(item))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"Unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize with stable keys, separators, Unicode, and finite numbers only."""

    return json.dumps(
        to_primitive(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: Any, *, length: int = 32) -> str:
    if not prefix or not prefix.replace("_", "").isalnum():
        raise ValueError("stable ID prefix must be alphanumeric/underscore")
    if not 8 <= length <= 64:
        raise ValueError("stable ID hash length must be between 8 and 64")
    return f"{prefix}_{canonical_hash(value)[:length]}"
