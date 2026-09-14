from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .base import Timestamped, UUIDPk


class AuditEvent(Base, UUIDPk, Timestamped):
    """One append-only, hash-chained entry in the tamper-evident audit trail.

    Rows here must never be updated or deleted; see
    migrations/versions for the Postgres rules that enforce this at the
    database level, not just by application convention. Use
    app.audit.service to append events; do not construct/insert this model
    directly from route handlers.
    """

    __tablename__ = "audit_events"

    # Assigned in Python by app.audit.service.append_event, under a row lock
    # on the chain's tail. Deliberately not a DB-native autoincrement/
    # sequence, so the same code path works identically on Postgres in
    # production and SQLite in tests.
    seq: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)

    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(200), default="system")

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
