"""Orchestrates incident intake and classification: wires the pure
rules_engine to the database and the audit trail. Route handlers (both the
JSON API and the dashboard's form posts) call into this module rather than
touching models or the rules engine directly, so webhook intake and manual
intake stay behavior-identical.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit.service import append_event
from ..models import ClassificationRun, Incident, IncidentSource, IncidentStatus, User
from ..rules_engine import evaluate_all, load_all_rulesets

_RULESETS = load_all_rulesets()


def create_incident(
    db: Session,
    *,
    title: str,
    description: str = "",
    source: IncidentSource,
    source_system: str = "",
    source_reference: str | None = None,
    raw_payload: dict | None = None,
    facts: dict[str, Any] | None = None,
    detected_at: datetime | None = None,
    awareness_at: datetime | None = None,
    created_by: User | None = None,
) -> Incident:
    incident = Incident(
        title=title,
        description=description,
        source=source,
        source_system=source_system,
        source_reference=source_reference,
        raw_payload=raw_payload,
        facts=facts or {},
        detected_at=detected_at,
        awareness_at=awareness_at,
        created_by_id=created_by.id if created_by else None,
    )
    db.add(incident)
    db.flush()

    append_event(
        db,
        event_type="incident.created",
        summary=f"Incident '{title}' created via {source.value}"
        + (f" ({source_system})" if source_system else ""),
        payload={
            "source": source.value,
            "source_system": source_system,
            "source_reference": source_reference,
        },
        incident_id=incident.id,
        actor_id=created_by.id if created_by else None,
        actor_label=created_by.display_label() if created_by else f"webhook:{source_system or 'unknown'}",
    )
    db.commit()
    db.refresh(incident)
    return incident


def update_facts(
    db: Session,
    incident: Incident,
    *,
    facts: dict[str, Any],
    detected_at: datetime | None = None,
    awareness_at: datetime | None = None,
    actor: User,
) -> Incident:
    before = dict(incident.facts)
    incident.facts = facts
    if detected_at is not None:
        incident.detected_at = detected_at
    if awareness_at is not None:
        incident.awareness_at = awareness_at

    append_event(
        db,
        event_type="incident.facts_updated",
        summary=f"{actor.display_label()} updated incident facts",
        payload={"before": before, "after": facts},
        incident_id=incident.id,
        actor_id=actor.id,
        actor_label=actor.display_label(),
    )
    db.commit()
    db.refresh(incident)
    return incident


def run_classification(db: Session, incident: Incident, actor: User) -> ClassificationRun:
    evaluations = evaluate_all(incident.facts, _RULESETS)

    results = {
        fw: {
            "result": ev.result.value,
            "label": ev.label,
            "fired_rules": ev.fired_rules,
            "not_fired_rules": ev.not_fired_rules,
            "indeterminate_rules": ev.indeterminate_rules,
            "missing_fields": ev.missing_fields,
            "explanations": ev.explanations,
        }
        for fw, ev in evaluations.items()
    }
    ruleset_versions = {fw: rs.version for fw, rs in _RULESETS.items()}

    run = ClassificationRun(
        incident_id=incident.id,
        ruleset_versions=ruleset_versions,
        results=results,
        facts_snapshot=dict(incident.facts),
    )
    db.add(run)
    incident.status = IncidentStatus.PENDING_CONFIRMATION
    db.flush()

    summary_bits = [f"{fw}={r['result']}" for fw, r in results.items()]
    append_event(
        db,
        event_type="classification.run",
        summary=f"{actor.display_label()} ran classification: " + ", ".join(summary_bits),
        payload={"ruleset_versions": ruleset_versions, "results": results},
        incident_id=incident.id,
        actor_id=actor.id,
        actor_label=actor.display_label(),
    )
    db.commit()
    db.refresh(run)
    return run


class StaleClassificationError(Exception):
    """Raised when confirming a run whose facts snapshot no longer matches
    the incident's current facts. The facts were edited after this run,
    so it must be re-run before it can be treated as authoritative."""


def confirm_classification(db: Session, incident: Incident, run_id: str, actor: User) -> ClassificationRun:
    run = db.execute(
        select(ClassificationRun).where(
            ClassificationRun.id == run_id, ClassificationRun.incident_id == incident.id
        )
    ).scalar_one_or_none()
    if run is None:
        raise ValueError("Classification run not found for this incident")
    if run.facts_snapshot != incident.facts:
        raise StaleClassificationError(
            "Incident facts have changed since this classification run; re-run classification first"
        )

    now = datetime.now(UTC)
    run.is_confirmed = True
    run.confirmed_by_id = actor.id
    run.confirmed_at = now
    incident.status = IncidentStatus.CONFIRMED
    incident.confirmed_by_id = actor.id
    # The first confirmation is the DORA "classified as major" moment that
    # starts its 4-hour clock; a later re-confirmation must not reset it.
    if incident.classification_confirmed_at is None:
        incident.classification_confirmed_at = now
    db.flush()

    append_event(
        db,
        event_type="classification.confirmed",
        summary=f"{actor.display_label()} confirmed the classification for this incident",
        payload={"classification_run_id": run.id, "results": run.results},
        incident_id=incident.id,
        actor_id=actor.id,
        actor_label=actor.display_label(),
    )
    db.commit()
    db.refresh(run)
    return run


def close_incident(db: Session, incident: Incident, *, actor: User, reason: str = "") -> Incident:
    if incident.status is IncidentStatus.CLOSED:
        return incident
    incident.status = IncidentStatus.CLOSED
    db.flush()
    append_event(
        db,
        event_type="incident.closed",
        summary=f"{actor.display_label()} closed the incident" + (f": {reason}" if reason else ""),
        payload={"reason": reason},
        incident_id=incident.id,
        actor_id=actor.id,
        actor_label=actor.display_label(),
    )
    db.commit()
    db.refresh(incident)
    return incident


def latest_classification_run(incident: Incident) -> ClassificationRun | None:
    if not incident.classification_runs:
        return None
    return incident.classification_runs[-1]


def latest_confirmed_run(incident: Incident) -> ClassificationRun | None:
    confirmed = [r for r in incident.classification_runs if r.is_confirmed]
    return confirmed[-1] if confirmed else None
