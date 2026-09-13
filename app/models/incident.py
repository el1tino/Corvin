from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import Timestamped, UUIDPk
from .types import UTCDateTime

if TYPE_CHECKING:
    from .classification import ClassificationRun
    from .draft import Draft
    from .user import User


class IncidentSource(enum.StrEnum):
    MANUAL = "manual"
    WEBHOOK = "webhook"


class IncidentStatus(enum.StrEnum):
    NEW = "new"  # just landed, not yet classified
    PENDING_CONFIRMATION = "pending_confirmation"  # engine has run, awaiting human sign-off
    CONFIRMED = "confirmed"  # a named human confirmed the classification
    CLOSED = "closed"


class Incident(Base, UUIDPk, Timestamped):
    __tablename__ = "incidents"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    source: Mapped[IncidentSource] = mapped_column(
        Enum(IncidentSource, native_enum=False, length=20), nullable=False
    )
    source_system: Mapped[str] = mapped_column(String(100), default="")
    source_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # The classification-engine input. See app.rules_engine.IncidentFacts for
    # the conventional field names; kept as a flexible JSON blob because rule
    # authors add fields over time without a schema migration.
    facts: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, native_enum=False, length=30), default=IncidentStatus.NEW, nullable=False
    )

    # Three distinct timestamps, deliberately not collapsed into one: DORA,
    # NIS2 and GDPR disagree on which one starts their clocks.
    detected_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    awareness_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    classification_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    confirmed_by: Mapped[User | None] = relationship(foreign_keys=[confirmed_by_id])

    classification_runs: Mapped[list[ClassificationRun]] = relationship(
        back_populates="incident", order_by="ClassificationRun.created_at", cascade="all, delete-orphan"
    )
    drafts: Mapped[list[Draft]] = relationship(
        back_populates="incident", order_by="Draft.created_at", cascade="all, delete-orphan"
    )
