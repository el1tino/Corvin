from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..audit.service import export_incident_trail
from ..auth.deps import get_current_user
from ..database import get_db
from ..models import Incident, User
from .deps import get_incident_or_404

router = APIRouter(prefix="/api/incidents/{incident_id}/audit", tags=["audit"])


@router.get("")
def get_audit_trail(
    incident: Incident = Depends(get_incident_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return export_incident_trail(db, incident.id)


@router.get("/export")
def download_audit_trail(
    incident: Incident = Depends(get_incident_or_404),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """A single machine-verifiable JSON file for this incident's full audit
    trail (build spec: export as human-readable timeline plus a
    machine-verifiable file. This endpoint serves both in one document,
    since the timeline is itself derived from the verifiable event list).
    """
    export = export_incident_trail(db, incident.id)
    body = json.dumps(export, indent=2, sort_keys=True)
    filename = f"{incident.id}-audit-trail.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
