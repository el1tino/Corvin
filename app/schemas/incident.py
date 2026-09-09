from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .facts import IncidentFacts


class IncidentCreateManual(BaseModel):
    title: str
    description: str = ""
    detected_at: datetime | None = None
    awareness_at: datetime | None = None
    facts: IncidentFacts = IncidentFacts()


class IncidentFactsUpdate(BaseModel):
    facts: IncidentFacts
    awareness_at: datetime | None = None
    detected_at: datetime | None = None


class ClassificationConfirmIn(BaseModel):
    classification_run_id: str


class DraftGenerateIn(BaseModel):
    framework: str
    stage: str


class DraftUpdateIn(BaseModel):
    content: str
