"""GDPR (Regulation 2016/679, Articles 33-34) notification clocks.

The Article 33 supervisory-authority deadline runs from awareness. Article
34's data-subject notification has no fixed statutory deadline ("without
undue delay"), so it is surfaced as a required action rather than a hard
due date; gating it on a fake deadline would misrepresent the law.
"""

from __future__ import annotations

from datetime import datetime

from .models import Deadline, GdprClock
from .utils import add_hours, ensure_utc


def compute_gdpr_clock(
    awareness_at: datetime,
    high_risk_to_individuals: bool = False,
) -> GdprClock:
    awareness_at = ensure_utc(awareness_at)
    deadlines = [
        Deadline(
            label="Supervisory authority notification",
            due_at=add_hours(awareness_at, 72),
            basis="72 hours from awareness (Article 33)",
        )
    ]
    return GdprClock(
        framework="gdpr",
        deadlines=deadlines,
        data_subject_notification_required=high_risk_to_individuals,
    )
