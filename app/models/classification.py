from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import Timestamped, UUIDPk
from .types import UTCDateTime

if TYPE_CHECKING:
    from .incident import Incident
    from .user import User


class ClassificationRun(Base, UUIDPk, Timestamped):
    """One execution of the rules engine against an incident's facts.

    Everything the engine decides is a recommendation (per build spec) --
    `is_confirmed` / `confirmed_by_id` / `confirmed_at` record the mandatory
    human sign-off that makes a run's clocks and drafts authoritative.
    Re-running classification (e.g. after facts are edited) creates a new
    row rather than overwriting this one, preserving history.
    """

    __tablename__ = "classification_runs"

    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), nullable=False, index=True)

    # {"dora": 1, "nis2": 1, "gdpr": 1}: which editable ruleset version
    # produced this run's results, per framework.
    ruleset_versions: Mapped[dict] = mapped_column(JSON, nullable=False)

    # {"dora": {"result": "reportable", "fired_rules": [...], "not_fired_rules": [...],
    #           "indeterminate_rules": [...], "missing_fields": [...], "explanations": [...],
    #           "label": "..."}, "nis2": {...}, "gdpr": {...}}
    results: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Snapshot of the facts the engine actually saw, so a later fact edit
    # can never retroactively change what a past run is shown to have decided.
    facts_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)

    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="classification_runs")
    confirmed_by: Mapped[User | None] = relationship()
