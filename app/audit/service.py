"""Database-facing half of the audit trail: appends and reads AuditEvent
rows, delegating the actual hashing/verification to the pure functions in
hashing.py / verify.py.

Route handlers must always go through `append_event` rather than
constructing `AuditEvent` rows themselves, so the hash chain can never be
built incorrectly by an ad-hoc insert.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.audit_event import AuditEvent
from .hashing import GENESIS_HASH, compute_event_hash
from .models import AuditEventRecord
from .verify import VerificationResult, verify_chain


def append_event(
    db: Session,
    *,
    event_type: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    incident_id: str | None = None,
    actor_id: str | None = None,
    actor_label: str = "system",
) -> AuditEvent:
    payload = payload or {}
    # Lock the current tail row so two concurrent appends can't both read the
    # same prev_hash and race to insert -- the chain must stay strictly
    # linear even under concurrent requests.
    last = db.execute(
        select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1).with_for_update()
    ).scalar_one_or_none()
    prev_hash = last.hash if last else GENESIS_HASH
    next_seq = (last.seq + 1) if last else 1
    created_at = datetime.now(UTC)

    event_hash = compute_event_hash(
        prev_hash=prev_hash,
        event_type=event_type,
        created_at=created_at,
        incident_id=incident_id,
        actor_id=actor_id,
        summary=summary,
        payload=payload,
    )

    event = AuditEvent(
        seq=next_seq,
        incident_id=incident_id,
        actor_id=actor_id,
        actor_label=actor_label,
        event_type=event_type,
        summary=summary,
        payload=payload,
        prev_hash=prev_hash,
        hash=event_hash,
        created_at=created_at,
    )
    db.add(event)
    db.flush()
    return event


def _to_record(event: AuditEvent) -> AuditEventRecord:
    return AuditEventRecord(
        id=event.id,
        seq=event.seq,
        event_type=event.event_type,
        created_at=event.created_at,
        incident_id=event.incident_id,
        actor_id=event.actor_id,
        actor_label=event.actor_label,
        summary=event.summary,
        payload=event.payload,
        prev_hash=event.prev_hash,
        hash=event.hash,
    )


def list_events_for_incident(db: Session, incident_id: str) -> list[AuditEvent]:
    return list(
        db.execute(
            select(AuditEvent).where(AuditEvent.incident_id == incident_id).order_by(AuditEvent.seq)
        ).scalars()
    )


def list_all_events(db: Session) -> list[AuditEvent]:
    return list(db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars())


def verify_full_trail(db: Session) -> VerificationResult:
    """Verify the *entire* chain -- an incident-scoped subsequence can look
    internally consistent even if a different incident's event was tampered
    with, since the chain links across incidents by design (one global,
    strictly ordered ledger).
    """
    return verify_chain([_to_record(e) for e in list_all_events(db)])


def export_incident_trail(db: Session, incident_id: str) -> dict[str, Any]:
    """A human-readable timeline plus the raw records needed for independent
    hash verification, for one incident's full export (build spec: "provide
    an export of the full trail for a single incident as a human-readable
    timeline plus a machine-verifiable file").
    """
    full_verification = verify_full_trail(db)
    incident_events = list_events_for_incident(db, incident_id)
    timeline = [
        {
            "seq": e.seq,
            "timestamp": e.created_at.isoformat(),
            "actor": e.actor_label,
            "event_type": e.event_type,
            "summary": e.summary,
        }
        for e in incident_events
    ]
    machine_verifiable = [
        {
            "id": e.id,
            "seq": e.seq,
            "event_type": e.event_type,
            "created_at": e.created_at.isoformat(),
            "incident_id": e.incident_id,
            "actor_id": e.actor_id,
            "summary": e.summary,
            "payload": e.payload,
            "prev_hash": e.prev_hash,
            "hash": e.hash,
        }
        for e in incident_events
    ]
    return {
        "incident_id": incident_id,
        "chain_integrity": {
            "verified_against": "full system-wide chain",
            "ok": full_verification.ok,
            "events_checked": full_verification.events_checked,
            "detail": full_verification.detail,
        },
        "timeline": timeline,
        "events": machine_verifiable,
    }
