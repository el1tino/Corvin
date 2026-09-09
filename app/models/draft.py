from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import Timestamped, UUIDPk
from .types import UTCDateTime


class DraftStage(str, enum.Enum):
    DORA_INITIAL = "dora_initial"
    DORA_INTERMEDIATE = "dora_intermediate"
    DORA_FINAL = "dora_final"
    NIS2_EARLY_WARNING = "nis2_early_warning"
    NIS2_NOTIFICATION = "nis2_notification"
    NIS2_FINAL = "nis2_final"
    GDPR_ARTICLE_33 = "gdpr_article_33"


class DraftStatus(str, enum.Enum):
    GENERATED = "generated"
    EDITED = "edited"
    EXPORTED = "exported"


class Draft(Base, UUIDPk, Timestamped):
    """One versioned draft notification document tied to an incident.

    Every regeneration creates a new row with an incremented `version`
    rather than mutating a previous draft, so the audit trail can point at
    exactly which text was exported and when.
    """

    __tablename__ = "drafts"

    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), nullable=False, index=True)
    framework: Mapped[str] = mapped_column(String(20), nullable=False)
    stage: Mapped[DraftStage] = mapped_column(Enum(DraftStage, native_enum=False, length=30), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    placeholders: Mapped[list] = mapped_column(JSON, default=list)

    prompt: Mapped[str] = mapped_column(Text, default="")
    model_used: Mapped[str] = mapped_column(String(100), default="")

    status: Mapped[DraftStatus] = mapped_column(
        Enum(DraftStatus, native_enum=False, length=20), default=DraftStatus.GENERATED, nullable=False
    )

    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    exported_format: Mapped[str | None] = mapped_column(String(10), nullable=True)

    incident: Mapped["Incident"] = relationship(back_populates="drafts")
    created_by: Mapped["User | None"] = relationship()
