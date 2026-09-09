from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..auth.deps import require_compliance
from ..database import get_db
from ..models import Draft, Incident, User
from ..schemas.incident import DraftGenerateIn, DraftUpdateIn
from ..services import draft_service, incident_service
from .deps import get_customer_config, get_incident_or_404
from .serializers import serialize_draft

router = APIRouter(prefix="/api/incidents/{incident_id}/drafts", tags=["drafts"])


def _get_draft_or_404(draft_id: str, incident: Incident, db: Session) -> Draft:
    draft = db.get(Draft, draft_id)
    if draft is None or draft.incident_id != incident.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return draft


@router.post("", status_code=status.HTTP_201_CREATED)
def generate_draft_endpoint(
    payload: DraftGenerateIn,
    incident: Incident = Depends(get_incident_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(require_compliance),
) -> dict:
    confirmed_run = incident_service.latest_confirmed_run(incident)
    customer = get_customer_config(db)
    try:
        draft = draft_service.generate_incident_draft(
            db, incident, confirmed_run, customer, framework=payload.framework, stage=payload.stage, actor=user
        )
    except draft_service.DraftNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return serialize_draft(draft)


@router.patch("/{draft_id}")
def edit_draft_endpoint(
    draft_id: str,
    payload: DraftUpdateIn,
    incident: Incident = Depends(get_incident_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(require_compliance),
) -> dict:
    draft = _get_draft_or_404(draft_id, incident, db)
    draft = draft_service.edit_draft(db, draft, content=payload.content, actor=user)
    return serialize_draft(draft)


@router.post("/{draft_id}/export")
def export_draft_endpoint(
    draft_id: str,
    fmt: str,
    incident: Incident = Depends(get_incident_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(require_compliance),
) -> Response:
    draft = _get_draft_or_404(draft_id, incident, db)
    confirmed_run = incident_service.latest_confirmed_run(incident)
    customer = get_customer_config(db)  # noqa: F841 -- ensures config row exists before export
    try:
        data = draft_service.export_draft(db, draft, incident, confirmed_run, fmt=fmt, actor=user)
    except draft_service.DraftNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if fmt == "docx"
        else "application/pdf"
    )
    filename = f"{incident.id}-{draft.stage.value}-v{draft.version}.{fmt}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
