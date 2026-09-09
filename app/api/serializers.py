from __future__ import annotations

from typing import Any

from ..clocks import Deadline
from ..models import ClassificationRun, Draft, Incident
from ..services import clock_service, incident_service


def serialize_deadline(d: Deadline) -> dict[str, Any]:
    return {"label": d.label, "due_at": d.due_at.isoformat(), "basis": d.basis, "provisional": d.provisional}


def serialize_clocks(clocks: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for framework, clock in clocks.items():
        entry: dict[str, Any] = {"deadlines": [serialize_deadline(d) for d in clock.deadlines]}
        if hasattr(clock, "capped_by_24h_rule"):
            entry["capped_by_24h_rule"] = clock.capped_by_24h_rule
        if hasattr(clock, "data_subject_notification_required"):
            entry["data_subject_notification_required"] = clock.data_subject_notification_required
        out[framework] = entry
    nearest = clock_service.nearest_deadline(clocks)
    return {"frameworks": out, "nearest_deadline": serialize_deadline(nearest) if nearest else None}


def serialize_classification_run(run: ClassificationRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "created_at": run.created_at.isoformat(),
        "ruleset_versions": run.ruleset_versions,
        "results": run.results,
        "is_confirmed": run.is_confirmed,
        "confirmed_by": run.confirmed_by.display_label() if run.confirmed_by else None,
        "confirmed_at": run.confirmed_at.isoformat() if run.confirmed_at else None,
    }


def serialize_draft(draft: Draft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "framework": draft.framework,
        "stage": draft.stage.value,
        "version": draft.version,
        "status": draft.status.value,
        "content": draft.content,
        "placeholders": draft.placeholders,
        "model_used": draft.model_used,
        "created_at": draft.created_at.isoformat(),
        "exported_at": draft.exported_at.isoformat() if draft.exported_at else None,
        "exported_format": draft.exported_format,
    }


def serialize_incident(incident: Incident, *, include_clocks: bool = True) -> dict[str, Any]:
    latest_run = incident_service.latest_classification_run(incident)
    confirmed_run = incident_service.latest_confirmed_run(incident)
    data: dict[str, Any] = {
        "id": incident.id,
        "title": incident.title,
        "description": incident.description,
        "source": incident.source.value,
        "source_system": incident.source_system,
        "source_reference": incident.source_reference,
        "status": incident.status.value,
        "facts": incident.facts,
        "detected_at": incident.detected_at.isoformat() if incident.detected_at else None,
        "awareness_at": incident.awareness_at.isoformat() if incident.awareness_at else None,
        "classification_confirmed_at": (
            incident.classification_confirmed_at.isoformat() if incident.classification_confirmed_at else None
        ),
        "created_at": incident.created_at.isoformat(),
        "latest_classification": serialize_classification_run(latest_run) if latest_run else None,
        "confirmed_classification": serialize_classification_run(confirmed_run) if confirmed_run else None,
        "drafts": [serialize_draft(d) for d in incident.drafts],
    }
    if include_clocks:
        clocks = clock_service.compute_incident_clocks(incident, confirmed_run)
        data["clocks"] = serialize_clocks(clocks)
    return data
