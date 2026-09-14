"""Custom column types shared across models.

`UTCDateTime` exists because SQLite (used in tests; production runs
Postgres per the build spec) does not round-trip a timezone-aware
datetime's tzinfo: a value written as UTC-aware can come back naive on
read. Postgres via psycopg does not have this problem, but relying on
that per-backend difference would mean the app behaves correctly only in
production and silently breaks in tests (or on SQLite ever used again in
some other tool/migration). Normalizing at the type-decorator layer means
every consumer (app.clocks included, which deliberately rejects naive
datetimes) can always assume a timezone-aware, UTC datetime coming out
of the database, on any backend.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"Naive datetime {value!r} written to a UTCDateTime column")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
