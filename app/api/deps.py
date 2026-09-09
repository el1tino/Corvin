from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CustomerConfig, Incident
from ..models.customer_config import SINGLETON_ID


def get_incident_or_404(incident_id: str, db: Session = Depends(get_db)) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return incident


def get_customer_config(db: Session = Depends(get_db)) -> CustomerConfig:
    config = db.get(CustomerConfig, SINGLETON_ID)
    if config is None:
        config = CustomerConfig(id=SINGLETON_ID)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config
