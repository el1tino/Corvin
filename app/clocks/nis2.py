"""NIS2 (Directive 2022/2555) notification clocks.

All three deadlines run from the awareness timestamp -- unlike DORA, there
is no separate "classification" moment that starts the clock.
"""

from __future__ import annotations

from datetime import datetime

from .models import Deadline, Nis2Clock
from .utils import add_calendar_month, add_hours, ensure_utc


def compute_nis2_clock(awareness_at: datetime) -> Nis2Clock:
    awareness_at = ensure_utc(awareness_at)
    deadlines = [
        Deadline(
            label="Early warning",
            due_at=add_hours(awareness_at, 24),
            basis="24 hours from awareness",
        ),
        Deadline(
            label="Incident notification",
            due_at=add_hours(awareness_at, 72),
            basis="72 hours from awareness",
        ),
        Deadline(
            label="Final report",
            due_at=add_calendar_month(awareness_at),
            basis="one month from awareness",
        ),
    ]
    return Nis2Clock(framework="nis2", deadlines=deadlines)
