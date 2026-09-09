from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AuditEventRecord:
    """A DB-independent view of one audit event, used for hashing/verification/export."""

    id: str
    seq: int
    event_type: str
    created_at: datetime
    incident_id: str | None
    actor_id: str | None
    actor_label: str
    summary: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str
