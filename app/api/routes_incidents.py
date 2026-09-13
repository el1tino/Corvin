from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import get_current_user, require_analyst
from ..database import get_db
from ..models import Incident, IncidentSource, User
from ..schemas.incident import ClassificationConfirmIn, IncidentCreateManual, IncidentFactsUpdate
from ..services import incident_service
from .deps import get_incident_or_404
from .serializers import serialize_incident

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("")
def list_incidents(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    incidents = list(db.execute(select(Incident).order_by(Incident.created_at.desc())).scalars())
    return [serialize_incident(i) for i in incidents]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_incident_manual(
    payload: IncidentCreateManual,
    db: Session = Depends(get_db),
    user: User = Depends(require_analyst),
) -> dict:
    incident = incident_service.create_incident(
        db,
        title=payload.title,
        description=payload.description,
        source=IncidentSource.MANUAL,
        facts=payload.facts.to_engine_dict(),
        detected_at=payload.detected_at,
        awareness_at=payload.awareness_at,
        created_by=user,
    )
    return serialize_incident(incident)


@router.get("/{incident_id}")
def get_incident(
    incident: Incident = Depends(get_incident_or_404), user: User = Depends(get_current_user)
) -> dict:
    return serialize_incident(incident)


@router.patch("/{incident_id}/facts")
def update_incident_facts(
    payload: IncidentFactsUpdate,
    incident: Incident = Depends(get_incident_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(require_analyst),
) -> dict:
    incident_service.update_facts(
        db,
        incident,
        facts=payload.facts.to_engine_dict(),
        detected_at=payload.detected_at,
        awareness_at=payload.awareness_at,
        actor=user,
    )
    return serialize_incident(incident)


@router.post("/{incident_id}/classify")
def classify_incident(
    incident: Incident = Depends(get_incident_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(require_analyst),
) -> dict:
    incident_service.run_classification(db, incident, user)
    return serialize_incident(incident)


@router.post("/{incident_id}/classify/confirm")
def confirm_incident_classification(
    payload: ClassificationConfirmIn,
    incident: Incident = Depends(get_incident_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(require_analyst),
) -> dict:
    try:
        incident_service.confirm_classification(db, incident, payload.classification_run_id, user)
    except incident_service.StaleClassificationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return serialize_incident(incident)


@router.post("/{incident_id}/close")
def close_incident(
    incident: Incident = Depends(get_incident_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(require_analyst),
) -> dict:
    incident_service.close_incident(db, incident, actor=user)
    return serialize_incident(incident)
