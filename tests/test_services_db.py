"""Service-layer behaviour that needs a database: submitted drafts anchoring
DORA's follow-up clocks, and closing an incident."""

from datetime import UTC, datetime, timedelta

from app.auth.security import hash_password
from app.models import CustomerConfig, IncidentSource, IncidentStatus, Role, User
from app.models.customer_config import SINGLETON_ID
from app.services import clock_service, draft_service, incident_service

DORA_FACTS = {
    "affected_clients_pct": 20,
    "critical_services_affected": True,
    "downtime_minutes": 300,
    "member_states_affected_count": 1,
    "data_loss_confidentiality": False,
    "data_loss_integrity": False,
    "data_loss_availability": False,
    "data_loss_authenticity": False,
    "economic_impact_amount_eur": 1000,
    "severe_operational_disruption": False,
    "significant_financial_loss": False,
    "affects_other_persons_considerable_damage": False,
    "personal_data_involved": False,
    "breach_likely_risk_to_individuals": False,
}


def _setup(db):
    user = User(email="c@x.io", full_name="Cara", hashed_password=hash_password("pw"), role=Role.COMPLIANCE)
    config = CustomerConfig(id=SINGLETON_ID, entity_name="Acme")
    db.add_all([user, config])
    db.commit()
    incident = incident_service.create_incident(
        db,
        title="Outage",
        source=IncidentSource.MANUAL,
        facts=DORA_FACTS,
        awareness_at=datetime(2026, 2, 1, 8, 0, tzinfo=UTC),
        created_by=user,
    )
    run = incident_service.run_classification(db, incident, user)
    incident_service.confirm_classification(db, incident, run.id, user)
    return user, config, incident, run


def test_recording_submission_replaces_provisional_dora_clock(db_session):
    user, config, incident, run = _setup(db_session)

    before = clock_service.compute_incident_clocks(incident, run)["dora"]
    intermediate_before = next(d for d in before.deadlines if d.label == "Intermediate report")
    assert intermediate_before.provisional

    draft = draft_service.generate_incident_draft(
        db_session, incident, run, config, framework="dora", stage="dora_initial", actor=user
    )
    sent_at = datetime(2026, 2, 1, 11, 30, tzinfo=UTC)
    draft_service.mark_draft_submitted(db_session, draft, actor=user, submitted_at=sent_at)
    db_session.refresh(incident)

    after = clock_service.compute_incident_clocks(incident, run)["dora"]
    intermediate_after = next(d for d in after.deadlines if d.label == "Intermediate report")
    assert not intermediate_after.provisional
    assert intermediate_after.due_at == sent_at + timedelta(hours=72)
    assert draft.submitted_at == sent_at


def test_submission_cannot_be_recorded_twice(db_session):
    user, config, incident, run = _setup(db_session)
    draft = draft_service.generate_incident_draft(
        db_session, incident, run, config, framework="dora", stage="dora_initial", actor=user
    )
    draft_service.mark_draft_submitted(db_session, draft, actor=user)
    try:
        draft_service.mark_draft_submitted(db_session, draft, actor=user)
    except draft_service.DraftNotAllowedError:
        pass
    else:
        raise AssertionError("second submission should be refused")


def test_confirmation_records_who_confirmed_on_the_incident(db_session):
    user, _, incident, _ = _setup(db_session)
    assert incident.confirmed_by_id == user.id
    assert incident.classification_confirmed_at is not None


def test_close_incident_is_audited_and_idempotent(db_session):
    user, _, incident, _ = _setup(db_session)
    incident_service.close_incident(db_session, incident, actor=user, reason="resolved")
    incident_service.close_incident(db_session, incident, actor=user)
    assert incident.status is IncidentStatus.CLOSED

    from app.audit.service import list_events_for_incident

    closes = [
        e for e in list_events_for_incident(db_session, incident.id) if e.event_type == "incident.closed"
    ]
    assert len(closes) == 1
    assert "resolved" in closes[0].summary
