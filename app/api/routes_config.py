from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..audit.service import append_event
from ..auth.deps import require_admin
from ..database import get_db
from ..models import CustomerConfig, User
from ..schemas.config import CustomerConfigIn
from .deps import get_customer_config

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def get_config(config: CustomerConfig = Depends(get_customer_config)) -> dict:
    return {
        "entity_name": config.entity_name,
        "member_state": config.member_state,
        "default_timezone": config.default_timezone,
        "dora_authority_name": config.dora_authority_name,
        "dora_authority_contact": config.dora_authority_contact,
        "nis2_csirt_or_authority_name": config.nis2_csirt_or_authority_name,
        "nis2_csirt_or_authority_contact": config.nis2_csirt_or_authority_contact,
        "gdpr_supervisory_authority_name": config.gdpr_supervisory_authority_name,
        "gdpr_supervisory_authority_contact": config.gdpr_supervisory_authority_contact,
        "hosting_region": config.hosting_region,
        "allow_non_eu_llm": config.allow_non_eu_llm,
    }


@router.put("")
def update_config(
    payload: CustomerConfigIn,
    config: CustomerConfig = Depends(get_customer_config),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    for field, value in payload.model_dump().items():
        setattr(config, field, value)
    db.flush()
    append_event(
        db,
        event_type="config.updated",
        summary=f"{user.display_label()} updated customer configuration",
        payload=payload.model_dump(),
        actor_id=user.id,
        actor_label=user.display_label(),
    )
    db.commit()
    return get_config(config)
