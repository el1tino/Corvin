from datetime import UTC, datetime, timedelta

from app.audit import GENESIS_HASH, AuditEventRecord, compute_event_hash, verify_chain

UTC = UTC


def _build_chain(n: int) -> list[AuditEventRecord]:
    events = []
    prev = GENESIS_HASH
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(n):
        created_at = base + timedelta(minutes=i)
        payload = {"index": i}
        h = compute_event_hash(
            prev_hash=prev,
            event_type="incident.updated",
            created_at=created_at,
            incident_id="incident-1",
            actor_id="user-1",
            summary=f"Event {i}",
            payload=payload,
        )
        events.append(
            AuditEventRecord(
                id=f"evt-{i}",
                seq=i,
                event_type="incident.updated",
                created_at=created_at,
                incident_id="incident-1",
                actor_id="user-1",
                actor_label="Alice (analyst)",
                summary=f"Event {i}",
                payload=payload,
                prev_hash=prev,
                hash=h,
            )
        )
        prev = h
    return events


def test_valid_chain_verifies_ok():
    events = _build_chain(5)
    result = verify_chain(events)
    assert result.ok
    assert result.events_checked == 5


def test_editing_a_past_event_breaks_verification():
    events = _build_chain(5)
    tampered = events[2]
    events[2] = AuditEventRecord(**{**tampered.__dict__, "summary": "Event 2 (edited by an attacker)"})
    result = verify_chain(events)
    assert not result.ok
    assert result.first_broken_seq == 2


def test_deleting_an_event_breaks_the_chain_for_everything_after_it():
    events = _build_chain(5)
    del events[2]
    result = verify_chain(events)
    assert not result.ok
    # The gap is detected at the event that now follows the deleted one.
    assert result.first_broken_seq == 3


def test_reordering_events_breaks_the_chain():
    events = _build_chain(4)
    events[1], events[2] = events[2], events[1]
    result = verify_chain(events)
    assert not result.ok


def test_empty_chain_is_trivially_valid():
    result = verify_chain([])
    assert result.ok
    assert result.events_checked == 0
