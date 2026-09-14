"""The canonical incident-facts schema.

This is the single source of truth for which fields the classification
rules engine (app/rules_engine/rules/*.yaml) can reference. Both the manual
intake form and the webhook endpoint validate against this model before the
data reaches the engine, so a typo'd field name fails loudly at intake
rather than silently reading as "missing" forever.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class IncidentFacts(BaseModel):
    # --- DORA ---
    affected_clients_pct: float | None = Field(default=None, ge=0, le=100)
    affected_financial_counterparts_pct: float | None = Field(default=None, ge=0, le=100)
    downtime_minutes: int | None = Field(default=None, ge=0)
    critical_services_affected: bool | None = None
    member_states_affected_count: int | None = Field(default=None, ge=0)
    # Scoped to DORA's criterion specifically: loss of confidentiality/integrity/
    # availability/authenticity of data *supporting a critical or important
    # function*. A personal-data-only exposure that doesn't touch such a
    # function (e.g. a static document store) should leave these false even
    # if `personal_data_involved` is true; the two are not the same fact.
    data_loss_confidentiality: bool | None = None
    data_loss_integrity: bool | None = None
    data_loss_availability: bool | None = None
    data_loss_authenticity: bool | None = None
    economic_impact_amount_eur: float | None = Field(default=None, ge=0)

    # --- NIS2 ---
    severe_operational_disruption: bool | None = None
    significant_financial_loss: bool | None = None
    affects_other_persons_considerable_damage: bool | None = None

    # --- GDPR ---
    personal_data_involved: bool | None = None
    data_subjects_affected_count: int | None = Field(default=None, ge=0)
    breach_likely_risk_to_individuals: bool | None = None
    breach_likely_high_risk_to_individuals: bool | None = None

    model_config = {"extra": "allow"}  # rule authors may add fields without a schema change

    def to_engine_dict(self) -> dict:
        return self.model_dump(exclude_none=True)
