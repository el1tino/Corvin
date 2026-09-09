from sqlalchemy import text

from app.audit import verify_chain
from app.audit.service import append_event, export_incident_trail, list_events_for_incident, verify_full_trail
from app.models import Incident, IncidentSource


def _make_incident(db_session) -> Incident:
    incident = Incident(title="Test incident", source=IncidentSource.MANUAL, facts={})
    db_session.add(incident)
    db_session.commit()
    return incident


def test_append_event_chains_correctly(db_session):
    incident = _make_incident(db_session)
    e1 = append_event(db_session, event_type="incident.created", summary="Incident created", incident_id=incident.id)
    e2 = append_event(db_session, event_type="incident.updated", summary="Facts edited", incident_id=incident.id)
    db_session.commit()

    assert e1.seq == 1
    assert e2.seq == 2
    assert e2.prev_hash == e1.hash

    result = verify_full_trail(db_session)
    assert result.ok
    assert result.events_checked == 2


def test_export_incident_trail_shape(db_session):
    incident = _make_incident(db_session)
    append_event(db_session, event_type="incident.created", summary="Incident created", incident_id=incident.id)
    db_session.commit()

    export = export_incident_trail(db_session, incident.id)
    assert export["chain_integrity"]["ok"] is True
    assert len(export["timeline"]) == 1
    assert len(export["events"]) == 1
    assert export["events"][0]["hash"]


def test_tampering_with_a_stored_event_is_detected(db_session):
    incident = _make_incident(db_session)
    append_event(db_session, event_type="incident.created", summary="Original summary", incident_id=incident.id)
    append_event(db_session, event_type="incident.updated", summary="Second event", incident_id=incident.id)
    db_session.commit()

    # Simulate an attacker editing a row directly in the database, bypassing
    # the ORM/service layer entirely.
    db_session.execute(text("UPDATE audit_events SET summary = 'tampered!' WHERE seq = 1"))
    db_session.commit()

    result = verify_full_trail(db_session)
    assert not result.ok
    assert result.first_broken_seq == 1


def test_events_scope_correctly_per_incident(db_session):
    incident_a = _make_incident(db_session)
    incident_b = _make_incident(db_session)
    append_event(db_session, event_type="incident.created", summary="A created", incident_id=incident_a.id)
    append_event(db_session, event_type="incident.created", summary="B created", incident_id=incident_b.id)
    db_session.commit()

    events_a = list_events_for_incident(db_session, incident_a.id)
    events_b = list_events_for_incident(db_session, incident_b.id)
    assert len(events_a) == 1
    assert len(events_b) == 1
    assert events_a[0].summary == "A created"
