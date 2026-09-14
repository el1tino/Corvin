from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import IncidentSource
from ..schemas.webhook import WebhookIncidentIn
from ..services import incident_service
from .serializers import serialize_incident
from .webhook_auth import enforce_rate_limit, verify_webhook_token

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post(
    "/incidents",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_webhook_token), Depends(enforce_rate_limit)],
)
def receive_incident(payload: WebhookIncidentIn, db: Session = Depends(get_db)) -> dict:
    """Generic JSON webhook intake.

    Any SIEM, EDR, or custom scanner (see the phishing-scanner integration
    in scripts/) can POST here with a shared token in the `X-Webhook-Token`
    header. Only `title` and `source_system` are required; every other
    field, including every entry in `facts`, is optional, and a field
    the classification engine needs but doesn't get simply comes back as
    "needs human input" rather than rejecting the incident.
    """
    incident = incident_service.create_incident(
        db,
        title=payload.title,
        description=payload.description,
        source=IncidentSource.WEBHOOK,
        source_system=payload.source_system,
        source_reference=payload.source_reference,
        raw_payload=payload.model_dump(mode="json"),
        facts=payload.facts.to_engine_dict(),
        detected_at=payload.detected_at,
        awareness_at=payload.awareness_at,
        created_by=None,
    )
    return serialize_incident(incident)
