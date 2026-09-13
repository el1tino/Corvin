from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Mapped, mapped_column

from .types import UTCDateTime


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDPk:
    id: Mapped[str] = mapped_column(primary_key=True, default=new_uuid)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
