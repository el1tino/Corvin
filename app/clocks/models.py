from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Deadline:
    """One statutory due date, with the reasoning kept alongside it.

    `provisional=True` means the deadline was projected from an earlier
    stage's own deadline because that stage hasn't actually been filed yet
    (e.g. DORA's intermediate report is "72 hours from the initial
    notification": until the initial notification is actually sent, we
    show a provisional estimate and replace it once the real timestamp is
    recorded).
    """

    label: str
    due_at: datetime
    basis: str
    provisional: bool = False


@dataclass
class FrameworkClock:
    framework: str
    deadlines: list[Deadline] = field(default_factory=list)


@dataclass
class DoraClock(FrameworkClock):
    capped_by_24h_rule: bool = False


@dataclass
class Nis2Clock(FrameworkClock):
    pass


@dataclass
class GdprClock(FrameworkClock):
    data_subject_notification_required: bool = False
