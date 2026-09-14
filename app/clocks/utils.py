"""Timestamp arithmetic shared by all framework clocks.

All deadline math happens in UTC. UTC has no daylight-saving transitions, so
"4 hours from now" is always exactly 4 hours of elapsed time. The DST edge
case the build spec calls out is a *display* concern (converting a UTC
instant to the customer's local timezone), never an arithmetic one. Doing
duration math on local wall-clock time is the classic bug this avoids: on a
spring-forward day, "add 4 hours" in naive local time would land 3 hours of
real time later than intended.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

UTC = UTC


def ensure_utc(dt: datetime) -> datetime:
    """Normalize a timestamp to UTC, requiring it to be timezone-aware.

    A naive datetime is refused rather than assumed-UTC: silently guessing
    a timezone on a regulatory deadline is worse than failing loudly.
    """
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp {dt!r} is naive; all incident timestamps must be timezone-aware")
    return dt.astimezone(UTC)


def add_hours(dt: datetime, hours: float) -> datetime:
    return ensure_utc(dt) + timedelta(hours=hours)


def add_calendar_month(dt: datetime) -> datetime:
    """Add one calendar month, handling month-length edge cases.

    E.g. 31 Jan + 1 month -> 28 Feb (or 29 Feb in a leap year), matching how
    "within one month" is understood in the regulatory texts, rather than a
    fixed 30-day offset that would silently drift.
    """
    return ensure_utc(dt) + relativedelta(months=1)


def to_local(dt: datetime, tz_name: str) -> datetime:
    """Convert a UTC instant to the customer's configured display timezone."""
    return ensure_utc(dt).astimezone(ZoneInfo(tz_name))


def is_overdue(due_at: datetime, now: datetime | None = None) -> bool:
    now = ensure_utc(now) if now is not None else datetime.now(UTC)
    return now > ensure_utc(due_at)


def remaining(due_at: datetime, now: datetime | None = None) -> timedelta:
    now = ensure_utc(now) if now is not None else datetime.now(UTC)
    return ensure_utc(due_at) - now
