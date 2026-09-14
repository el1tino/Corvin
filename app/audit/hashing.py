"""Hash-chaining primitives for the tamper-evident audit trail.

Pure functions, no database or web dependencies: each event's hash is a
deterministic digest of its own fields plus the previous event's hash, so
altering or removing any past event breaks every hash after it. This module
only computes and checks digests; `service.py` wires it to the database.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

GENESIS_HASH = "0" * 64


def canonical_json(data: dict[str, Any]) -> str:
    """Stable serialization so the same logical event always hashes the same way."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _canonical_timestamp(dt: datetime) -> str:
    """Canonicalize to a UTC ISO-8601 string before hashing.

    Some storage backends (notably SQLite, used in tests; production
    runs Postgres) don't round-trip a timezone-aware datetime's tzinfo, so
    a value read back from the database can come back naive even though it
    was written as UTC. Rather than let the hash depend on a Python
    tzinfo object's identity, every timestamp is normalized the same way
    before hashing: naive is assumed to already be UTC (true for every
    timestamp this app writes), aware is converted to UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def compute_event_hash(
    *,
    prev_hash: str,
    event_type: str,
    created_at: datetime,
    incident_id: str | None,
    actor_id: str | None,
    summary: str,
    payload: dict[str, Any],
) -> str:
    body = canonical_json(
        {
            "prev_hash": prev_hash,
            "event_type": event_type,
            "created_at": _canonical_timestamp(created_at),
            "incident_id": incident_id,
            "actor_id": actor_id,
            "summary": summary,
            "payload": payload,
        }
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
