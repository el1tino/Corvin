"""The generic webhook intake schema.

Deliberately minimal and documented (see build spec: "keep the webhook
schema simple and documented so Microsoft Sentinel, Wazuh, Splunk or a
custom Python scanner can feed it with minimal mapping"). Any source that
can POST this JSON shape, with whatever subset of `facts` it knows, works --
unknown fields are preserved in `raw_payload` for provenance, and unmapped
`facts` fields simply come back as "needs human input" from the engine
rather than causing a failure.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .facts import IncidentFacts


class WebhookIncidentIn(BaseModel):
    title: str
    description: str = ""
    source_system: str = Field(
        description="Free-text name of the sending system, e.g. 'wazuh', 'sentinel', 'phishing-scanner'"
    )
    source_reference: str | None = Field(
        default=None, description="The sending system's own event/alert ID, for correlation"
    )
    detected_at: datetime | None = None
    awareness_at: datetime | None = Field(
        default=None,
        description="When the organization became aware, if known/different from detection",
    )
    facts: IncidentFacts = IncidentFacts()
