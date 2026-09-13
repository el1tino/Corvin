"""Orchestrates draft generation, editing, export and submission: gathers
the grounded context (incident facts, confirmed classification, customer
config, deadlines), calls app.drafting, and persists + audits the result.

Guard rule from the build spec: "before any draft can be exported" the
classification must be confirmed by a named human. This module is the
only place that constructs or mutates a Draft row, so the guard cannot be
skipped by a route forgetting to check.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..audit.service import append_event
from ..config import get_settings
from ..drafting import generate_draft
from ..drafting.export import export_to_docx, export_to_pdf
from ..drafting.generator import extract_placeholders
from ..drafting.llm_client import NonEuLlmBlocked, build_llm_client
from ..models import ClassificationRun, CustomerConfig, Draft, DraftStage, DraftStatus, Incident, User
from . import clock_service

FRAMEWORK_STAGES = {
    "dora": ["dora_initial", "dora_intermediate", "dora_final"],
    "nis2": ["nis2_early_warning", "nis2_notification", "nis2_final"],
    "gdpr": ["gdpr_article_33"],
}

STAGE_DEADLINE_LABEL = {
    "dora_initial": "Initial notification",
    "dora_intermediate": "Intermediate report",
    "dora_final": "Final report",
    "nis2_early_warning": "Early warning",
    "nis2_notification": "Incident notification",
    "nis2_final": "Final report",
    "gdpr_article_33": "Supervisory authority notification",
}

MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


class DraftNotAllowedError(Exception):
    """A draft action was requested before its precondition held: no
    confirmed classification, framework not reportable, unknown stage."""


def export_filename(draft: Draft, fmt: str) -> str:
    return f"{draft.incident_id}-{draft.stage.value}-v{draft.version}.{fmt}"


def _require_confirmed(confirmed_run: ClassificationRun | None) -> ClassificationRun:
    if confirmed_run is None:
        raise DraftNotAllowedError("Classification must be confirmed by a named human first")
    return confirmed_run


def _next_version(incident: Incident, stage: str) -> int:
    existing = [d.version for d in incident.drafts if d.stage.value == stage]
    return max(existing, default=0) + 1


def _build_context(
    incident: Incident,
    confirmed_run: ClassificationRun,
    customer: CustomerConfig,
    framework: str,
    stage: str,
) -> dict:
    clock = clock_service.compute_incident_clocks(incident, confirmed_run).get(framework)
    deadline = None
    if clock:
        deadline = next((d for d in clock.deadlines if d.label == STAGE_DEADLINE_LABEL[stage]), None)

    def iso(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    confirmed_by = confirmed_run.confirmed_by.display_label() if confirmed_run.confirmed_by else None
    return {
        "incident": {"id": incident.id, "title": incident.title, "description": incident.description},
        "facts": incident.facts,
        "customer": {
            "entity_name": customer.entity_name,
            "member_state": customer.member_state,
            "dora_authority_name": customer.dora_authority_name,
            "dora_authority_contact": customer.dora_authority_contact,
            "nis2_csirt_or_authority_name": customer.nis2_csirt_or_authority_name,
            "nis2_csirt_or_authority_contact": customer.nis2_csirt_or_authority_contact,
            "gdpr_supervisory_authority_name": customer.gdpr_supervisory_authority_name,
            "gdpr_supervisory_authority_contact": customer.gdpr_supervisory_authority_contact,
        },
        "timestamps": {
            "detected_at": iso(incident.detected_at),
            "awareness_at": iso(incident.awareness_at),
            "classification_confirmed_at": iso(incident.classification_confirmed_at),
        },
        "classification": confirmed_run.results.get(framework, {}),
        "deadline_due_at": deadline.due_at.isoformat() if deadline else None,
        "deadline_basis": deadline.basis if deadline else None,
        "data_subject_notification_required": bool(
            incident.facts.get("breach_likely_high_risk_to_individuals")
        ),
        "confirmed_by": confirmed_by,
    }


def generate_incident_draft(
    db: Session,
    incident: Incident,
    confirmed_run: ClassificationRun | None,
    customer: CustomerConfig,
    *,
    framework: str,
    stage: str,
    actor: User,
) -> Draft:
    confirmed_run = _require_confirmed(confirmed_run)
    if stage not in FRAMEWORK_STAGES.get(framework, ()):
        raise DraftNotAllowedError(f"Unknown framework/stage combination: {framework}/{stage}")
    if confirmed_run.results.get(framework, {}).get("result") != "reportable":
        raise DraftNotAllowedError(
            f"Incident is not confirmed as reportable under {framework.upper()}; nothing to notify"
        )

    llm_client = None
    llm_note = None
    try:
        llm_client = build_llm_client(get_settings())
    except NonEuLlmBlocked as exc:
        llm_note = f"LLM blocked by EU data-residency guard: {exc}"

    result = generate_draft(
        stage=stage,
        context=_build_context(incident, confirmed_run, customer, framework, stage),
        llm_client=llm_client,
        llm_note=llm_note,
    )

    draft = Draft(
        incident_id=incident.id,
        framework=framework,
        stage=DraftStage(stage),
        version=_next_version(incident, stage),
        content=result.content,
        placeholders=result.placeholders,
        prompt=result.prompt_used,
        model_used=result.model_used,
        status=DraftStatus.GENERATED,
        created_by_id=actor.id,
    )
    db.add(draft)
    db.flush()

    append_event(
        db,
        event_type="draft.generated",
        summary=f"{actor.display_label()} generated {stage} draft v{draft.version}",
        payload={
            "draft_id": draft.id,
            "framework": framework,
            "stage": stage,
            "version": draft.version,
            "model_used": result.model_used,
            "llm_note": result.llm_note,
            "placeholder_count": len(result.placeholders),
        },
        incident_id=incident.id,
        actor_id=actor.id,
        actor_label=actor.display_label(),
    )
    db.commit()
    db.refresh(draft)
    return draft


def edit_draft(db: Session, draft: Draft, *, content: str, actor: User) -> Draft:
    before = len(draft.placeholders)
    draft.content = content
    draft.placeholders = extract_placeholders(content)
    if draft.status is DraftStatus.GENERATED:
        draft.status = DraftStatus.EDITED
    db.flush()

    append_event(
        db,
        event_type="draft.edited",
        summary=f"{actor.display_label()} edited {draft.stage.value} draft v{draft.version}",
        payload={
            "draft_id": draft.id,
            "placeholder_count_before": before,
            "placeholder_count_after": len(draft.placeholders),
        },
        incident_id=draft.incident_id,
        actor_id=actor.id,
        actor_label=actor.display_label(),
    )
    db.commit()
    db.refresh(draft)
    return draft


def export_draft(
    db: Session,
    draft: Draft,
    incident: Incident,
    confirmed_run: ClassificationRun | None,
    *,
    fmt: str,
    actor: User,
) -> bytes:
    _require_confirmed(confirmed_run)
    if fmt not in MEDIA_TYPES:
        raise ValueError("Export format must be 'docx' or 'pdf'")

    title = f"{incident.title} - {draft.stage.value}"
    data = (
        export_to_docx(draft.content, title=title)
        if fmt == "docx"
        else export_to_pdf(draft.content, title=title)
    )

    if draft.status is not DraftStatus.SUBMITTED:
        draft.status = DraftStatus.EXPORTED
    draft.exported_at = datetime.now(UTC)
    draft.exported_format = fmt
    db.flush()

    append_event(
        db,
        event_type="draft.exported",
        summary=f"{actor.display_label()} exported {draft.stage.value} v{draft.version} as {fmt.upper()}",
        payload={"draft_id": draft.id, "format": fmt, "version": draft.version},
        incident_id=incident.id,
        actor_id=actor.id,
        actor_label=actor.display_label(),
    )
    db.commit()
    return data


def mark_draft_submitted(
    db: Session, draft: Draft, *, actor: User, submitted_at: datetime | None = None
) -> Draft:
    """Record that a human sent this draft to the authority.

    Corvin never submits anything itself (out of scope by design), but the
    moment of submission matters: DORA's intermediate and final clocks run
    from the previous report, so recording it is what turns those clocks
    from provisional projections into authoritative deadlines.
    """
    if draft.submitted_at is not None:
        raise DraftNotAllowedError("This draft is already recorded as submitted")
    incident = draft.incident
    confirmed = [r for r in incident.classification_runs if r.is_confirmed]
    _require_confirmed(confirmed[-1] if confirmed else None)

    draft.submitted_at = submitted_at or datetime.now(UTC)
    draft.status = DraftStatus.SUBMITTED
    db.flush()

    append_event(
        db,
        event_type="draft.submitted",
        summary=f"{actor.display_label()} recorded {draft.stage.value} v{draft.version} as submitted",
        payload={"draft_id": draft.id, "submitted_at": draft.submitted_at.isoformat()},
        incident_id=incident.id,
        actor_id=actor.id,
        actor_label=actor.display_label(),
    )
    db.commit()
    db.refresh(draft)
    return draft
