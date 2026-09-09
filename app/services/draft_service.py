"""Orchestrates draft generation and export: gathers the grounded context
(incident facts, confirmed classification, customer config, deadlines),
calls app.drafting, and persists + audits the result.

Guard rule from the build spec: "before any draft can be exported" the
classification must be confirmed by a named human. This module is the only
place that constructs a Draft row, so that guard can't be skipped by a
route forgetting to check.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..audit.service import append_event
from ..config import get_settings
from ..drafting import generate_draft
from ..drafting.export import export_to_docx, export_to_pdf
from ..drafting.generator import extract_placeholders
from ..drafting.llm_client import build_llm_client
from ..models import ClassificationRun, CustomerConfig, Draft, DraftStage, DraftStatus, Incident, User
from . import clock_service

FRAMEWORK_STAGES = {
    "dora": ["dora_initial", "dora_intermediate", "dora_final"],
    "nis2": ["nis2_early_warning", "nis2_notification", "nis2_final"],
    "gdpr": ["gdpr_article_33"],
}


class DraftNotAllowedError(Exception):
    """Raised when a draft is requested for a framework/stage that isn't
    confirmed as reportable, or before classification has been confirmed."""


def _next_version(db: Session, incident: Incident, stage: str) -> int:
    existing = [d.version for d in incident.drafts if d.stage.value == stage]
    return (max(existing) + 1) if existing else 1


def _build_context(
    incident: Incident,
    confirmed_run: ClassificationRun,
    customer: CustomerConfig,
    framework: str,
    stage: str,
    confirmed_by_label: str,
) -> dict:
    clocks = clock_service.compute_incident_clocks(incident, confirmed_run)
    clock = clocks.get(framework)

    stage_to_deadline_label = {
        "dora_initial": "Initial notification",
        "dora_intermediate": "Intermediate report",
        "dora_final": "Final report",
        "nis2_early_warning": "Early warning",
        "nis2_notification": "Incident notification",
        "nis2_final": "Final report",
        "gdpr_article_33": "Supervisory authority notification",
    }
    deadline_due_at = None
    deadline_basis = None
    if clock:
        wanted_label = stage_to_deadline_label[stage]
        match = next((d for d in clock.deadlines if d.label == wanted_label), None)
        if match:
            deadline_due_at = match.due_at.isoformat()
            deadline_basis = match.basis

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
            "detected_at": incident.detected_at.isoformat() if incident.detected_at else None,
            "awareness_at": incident.awareness_at.isoformat() if incident.awareness_at else None,
            "classification_confirmed_at": (
                incident.classification_confirmed_at.isoformat()
                if incident.classification_confirmed_at
                else None
            ),
        },
        "classification": confirmed_run.results.get(framework, {}),
        "deadline_due_at": deadline_due_at,
        "deadline_basis": deadline_basis,
        "data_subject_notification_required": bool(
            incident.facts.get("breach_likely_high_risk_to_individuals")
        ),
        "confirmed_by": confirmed_by_label,
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
    if confirmed_run is None:
        raise DraftNotAllowedError("Classification must be confirmed before a draft can be generated")
    if framework not in FRAMEWORK_STAGES or stage not in FRAMEWORK_STAGES[framework]:
        raise DraftNotAllowedError(f"Unknown framework/stage combination: {framework}/{stage}")
    if confirmed_run.results.get(framework, {}).get("result") != "reportable":
        raise DraftNotAllowedError(
            f"Incident is not confirmed as reportable under {framework.upper()}; cannot draft a notification"
        )

    confirmed_by_label = confirmed_run.confirmed_by.display_label() if confirmed_run.confirmed_by else "Unknown"
    context = _build_context(incident, confirmed_run, customer, framework, stage, confirmed_by_label)

    settings = get_settings()
    llm_client = None
    try:
        llm_client = build_llm_client(settings)
    except Exception:
        llm_client = None  # any LLM setup problem degrades to the deterministic template, never a 500

    result = generate_draft(stage=stage, context=context, llm_client=llm_client)

    draft = Draft(
        incident_id=incident.id,
        framework=framework,
        stage=DraftStage(stage),
        version=_next_version(db, incident, stage),
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
        summary=f"{actor.display_label()} generated a {stage} draft (v{draft.version})",
        payload={
            "framework": framework,
            "stage": stage,
            "version": draft.version,
            "model_used": result.model_used,
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
    before_placeholder_count = len(draft.placeholders)
    draft.content = content
    draft.status = DraftStatus.EDITED
    draft.placeholders = extract_placeholders(content)
    db.flush()

    append_event(
        db,
        event_type="draft.edited",
        summary=f"{actor.display_label()} edited draft {draft.stage.value} v{draft.version}",
        payload={
            "placeholder_count_before": before_placeholder_count,
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
    db: Session, draft: Draft, incident: Incident, confirmed_run: ClassificationRun | None, *, fmt: str, actor: User
) -> bytes:
    if confirmed_run is None:
        raise DraftNotAllowedError("Classification must be confirmed before a draft can be exported")
    if fmt not in ("docx", "pdf"):
        raise ValueError("fmt must be 'docx' or 'pdf'")

    title = f"{incident.title} - {draft.stage.value}"
    data = export_to_docx(draft.content, title=title) if fmt == "docx" else export_to_pdf(draft.content, title=title)

    draft.status = DraftStatus.EXPORTED
    draft.exported_at = datetime.now(timezone.utc)
    draft.exported_format = fmt
    db.flush()

    append_event(
        db,
        event_type="draft.exported",
        summary=f"{actor.display_label()} exported draft {draft.stage.value} v{draft.version} as {fmt.upper()}",
        payload={"format": fmt, "draft_id": draft.id, "version": draft.version},
        incident_id=incident.id,
        actor_id=actor.id,
        actor_label=actor.display_label(),
    )
    db.commit()
    return data
