"""Bridges a confirmed ClassificationRun to the pure app.clocks functions.

Deadlines are only computed, and only shown as authoritative, for a
framework whose *confirmed* classification result is "reportable". An
unconfirmed engine recommendation must never start a statutory clock.

DORA's intermediate and final clocks run from the previous report actually
being sent, so they are anchored on the moment a human recorded a draft as
submitted (Draft.submitted_at). Until that happens they are projected off
the previous stage's due date and flagged as provisional.
"""

from __future__ import annotations

from datetime import datetime

from ..clocks import (
    Deadline,
    DoraClock,
    GdprClock,
    Nis2Clock,
    compute_dora_clock,
    compute_gdpr_clock,
    compute_nis2_clock,
)
from ..models import ClassificationRun, Incident

FrameworkClock = DoraClock | Nis2Clock | GdprClock


def _earliest_submission(incident: Incident, stage: str) -> datetime | None:
    times = [d.submitted_at for d in incident.drafts if d.stage.value == stage and d.submitted_at is not None]
    return min(times) if times else None


def compute_incident_clocks(
    incident: Incident, confirmed_run: ClassificationRun | None
) -> dict[str, FrameworkClock]:
    if confirmed_run is None or incident.awareness_at is None:
        return {}

    def reportable(framework: str) -> bool:
        return confirmed_run.results.get(framework, {}).get("result") == "reportable"

    clocks: dict[str, FrameworkClock] = {}

    if reportable("dora") and incident.classification_confirmed_at:
        clocks["dora"] = compute_dora_clock(
            awareness_at=incident.awareness_at,
            classification_at=incident.classification_confirmed_at,
            initial_notification_sent_at=_earliest_submission(incident, "dora_initial"),
            intermediate_report_sent_at=_earliest_submission(incident, "dora_intermediate"),
        )
    if reportable("nis2"):
        clocks["nis2"] = compute_nis2_clock(awareness_at=incident.awareness_at)
    if reportable("gdpr"):
        clocks["gdpr"] = compute_gdpr_clock(
            awareness_at=incident.awareness_at,
            high_risk_to_individuals=bool(incident.facts.get("breach_likely_high_risk_to_individuals")),
        )
    return clocks


def nearest_deadline(clocks: dict[str, FrameworkClock]) -> Deadline | None:
    """The soonest due date across all applicable frameworks."""
    deadlines = [d for clock in clocks.values() for d in clock.deadlines]
    return min(deadlines, key=lambda d: d.due_at) if deadlines else None
