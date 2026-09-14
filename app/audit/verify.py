from __future__ import annotations

from dataclasses import dataclass

from .hashing import GENESIS_HASH, compute_event_hash
from .models import AuditEventRecord


@dataclass
class VerificationResult:
    ok: bool
    events_checked: int
    first_broken_seq: int | None = None
    detail: str = ""


def verify_chain(events: list[AuditEventRecord]) -> VerificationResult:
    """Recompute every hash in sequence and confirm it matches what's stored.

    Any edit, deletion, reordering, or insertion in the middle of the chain
    changes a `prev_hash` or a `hash` and is caught here. This is the
    "machine-verifiable" half of the audit export the build spec asks for.
    """
    expected_prev = GENESIS_HASH
    for event in events:
        if event.prev_hash != expected_prev:
            return VerificationResult(
                ok=False,
                events_checked=event.seq,
                first_broken_seq=event.seq,
                detail=(
                    f"Event seq={event.seq} records prev_hash={event.prev_hash!r} but the "
                    f"preceding event's hash was {expected_prev!r}; chain is broken or reordered."
                ),
            )
        recomputed = compute_event_hash(
            prev_hash=event.prev_hash,
            event_type=event.event_type,
            created_at=event.created_at,
            incident_id=event.incident_id,
            actor_id=event.actor_id,
            summary=event.summary,
            payload=event.payload,
        )
        if recomputed != event.hash:
            return VerificationResult(
                ok=False,
                events_checked=event.seq,
                first_broken_seq=event.seq,
                detail=(
                    f"Event seq={event.seq} stored hash={event.hash!r} does not match "
                    f"recomputed hash={recomputed!r}; its contents were altered after logging."
                ),
            )
        expected_prev = event.hash

    return VerificationResult(ok=True, events_checked=len(events))
