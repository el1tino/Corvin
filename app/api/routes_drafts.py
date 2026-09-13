from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..auth.deps import require_compliance
from ..database import get_db
from ..models import CustomerConfig, Draft, Incident, User
from ..schemas.incident import DraftGenerateIn, DraftUpdateIn
from ..services import draft_service, incident_service
from .deps import get_customer_config, get_incident_or_404
from .serializers import serialize_draft

router = APIRouter(prefix="/api/incidents/{incident_id}/drafts", tags=["drafts"])


def get_draft_or_404(
    draft_id: str, incident: Incident = Depends(get_incident_or_404), db: Session = Depends(get_db)
) -> Draft:
    draft = db.get(Draft, draft_id)
    if draft is None or draft.incident_id != incident.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return draft


@router.post("", status_code=status.HTTP_201_CREATED)
def generate_draft_endpoint(
    payload: DraftGenerateIn,
    incident: Incident = Depends(get_incident_or_404),
    customer: CustomerConfig = Depends(get_customer_config),
    db: Session = Depends(get_db),
    user: User = Depends(require_compliance),
) -> dict:
    try:
        draft = draft_service.generate_incident_draft(
            db,
            incident,
            incident_service.latest_confirmed_run(incident),
            customer,
            framework=payload.framework,
            stage=payload.stage,
            actor=user,
        )
    except draft_service.DraftNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return serialize_draft(draft)


@router.patch("/{draft_id}")
def edit_draft_endpoint(
    payload: DraftUpdateIn,
    draft: Draft = Depends(get_draft_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(require_compliance),
) -> dict:
    return serialize_draft(draft_service.edit_draft(db, draft, content=payload.content, actor=user))


@router.post("/{draft_id}/submitted")
def mark_submitted_endpoint(
    draft: Draft = Depends(get_draft_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(require_compliance),
) -> dict:
    """Record that a human submitted this draft to the authority. DORA's
    intermediate/final clocks are anchored on this timestamp."""
    try:
        draft = draft_service.mark_draft_submitted(db, draft, actor=user)
    except draft_service.DraftNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return serialize_draft(draft)


@router.post("/{draft_id}/export")
def export_draft_endpoint(
    fmt: str,
    draft: Draft = Depends(get_draft_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(require_compliance),
) -> Response:
    incident = draft.incident
    try:
        data = draft_service.export_draft(
            db, draft, incident, incident_service.latest_confirmed_run(incident), fmt=fmt, actor=user
        )
    except draft_service.DraftNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return Response(
        content=data,
        media_type=draft_service.MEDIA_TYPES[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{draft_service.export_filename(draft, fmt)}"'
        },
    )
