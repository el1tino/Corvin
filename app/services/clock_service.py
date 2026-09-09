"""Bridges a confirmed ClassificationRun to the pure app.clocks functions.

Deadlines are only ever computed -- and only ever shown as authoritative --
for a framework whose *confirmed* classification result is "reportable".
An unconfirmed engine recommendation must never start a statutory clock
(build spec: "before any clock is treated as authoritative").
"""
from __future__ import annotations

from ..clocks import DoraClock, GdprClock, Nis2Clock, compute_dora_clock, compute_gdpr_clock, compute_nis2_clock
from ..models import ClassificationRun, Incident


def compute_incident_clocks(
    incident: Incident, confirmed_run: ClassificationRun | None
) -> dict[str, DoraClock | Nis2Clock | GdprClock]:
    if confirmed_run is None or incident.awareness_at is None:
        return {}

    clocks: dict[str, DoraClock | Nis2Clock | GdprClock] = {}
    results = confirmed_run.results

    if results.get("dora", {}).get("result") == "reportable" and incident.classification_confirmed_at:
        clocks["dora"] = compute_dora_clock(
            awareness_at=incident.awareness_at,
            classification_at=incident.classification_confirmed_at,
        )

    if results.get("nis2", {}).get("result") == "reportable":
        clocks["nis2"] = compute_nis2_clock(awareness_at=incident.awareness_at)

    if results.get("gdpr", {}).get("result") == "reportable":
        clocks["gdpr"] = compute_gdpr_clock(
            awareness_at=incident.awareness_at,
            high_risk_to_individuals=bool(incident.facts.get("breach_likely_high_risk_to_individuals")),
        )

    return clocks


def nearest_deadline(clocks: dict[str, DoraClock | Nis2Clock | GdprClock]):
    """The single soonest due date across all applicable frameworks, for the
    dashboard's "nearest deadline" column."""
    all_deadlines = [d for clock in clocks.values() for d in clock.deadlines]
    if not all_deadlines:
        return None
    return min(all_deadlines, key=lambda d: d.due_at)
