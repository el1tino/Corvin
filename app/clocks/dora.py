"""DORA (Regulation 2022/2554) notification clocks.

- Initial notification: within 4 hours of classifying the incident as
  major, and no later than 24 hours from becoming aware of it. The 24-hour
  mark is a hard cap, not a target -- if classification happens more than
  20 hours after awareness, the 4-hour allowance would blow through the
  cap, so the cap wins.
- Intermediate report: within 72 hours of the *initial notification*
  (i.e. of it actually being sent), not of awareness.
- Final report: within one month of the *intermediate report* being sent.
"""

from __future__ import annotations

from datetime import datetime

from .models import Deadline, DoraClock
from .utils import add_calendar_month, add_hours, ensure_utc


def compute_dora_clock(
    awareness_at: datetime,
    classification_at: datetime,
    initial_notification_sent_at: datetime | None = None,
    intermediate_report_sent_at: datetime | None = None,
) -> DoraClock:
    awareness_at = ensure_utc(awareness_at)
    classification_at = ensure_utc(classification_at)

    nominal_initial = add_hours(classification_at, 4)
    hard_cap = add_hours(awareness_at, 24)
    capped = hard_cap < nominal_initial
    initial_due = min(nominal_initial, hard_cap)

    deadlines = [
        Deadline(
            label="Initial notification",
            due_at=initial_due,
            basis=(
                "24h-from-awareness cap (classification was too close to, or past, the cap)"
                if capped
                else "4 hours from classification as major"
            ),
        )
    ]

    if initial_notification_sent_at is not None:
        intermediate_basis_at = ensure_utc(initial_notification_sent_at)
        intermediate_basis = "72 hours from the initial notification actually sent"
        intermediate_provisional = False
    else:
        intermediate_basis_at = initial_due
        intermediate_basis = "72 hours from the initial notification's due date (provisional -- not yet sent)"
        intermediate_provisional = True
    intermediate_due = add_hours(intermediate_basis_at, 72)
    deadlines.append(
        Deadline(
            label="Intermediate report",
            due_at=intermediate_due,
            basis=intermediate_basis,
            provisional=intermediate_provisional,
        )
    )

    if intermediate_report_sent_at is not None:
        final_basis_at = ensure_utc(intermediate_report_sent_at)
        final_basis = "one month from the intermediate report actually sent"
        final_provisional = False
    else:
        final_basis_at = intermediate_due
        final_basis = "one month from the intermediate report's due date (provisional -- not yet sent)"
        final_provisional = True
    final_due = add_calendar_month(final_basis_at)
    deadlines.append(
        Deadline(
            label="Final report",
            due_at=final_due,
            basis=final_basis,
            provisional=final_provisional,
        )
    )

    return DoraClock(framework="dora", deadlines=deadlines, capped_by_24h_rule=capped)
