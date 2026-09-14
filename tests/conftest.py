"""Shared fixtures.

Tests run on SQLite by default so `pytest` needs nothing installed. Set
CORVIN_TEST_DATABASE_URL to a Postgres URL (CI does) to run the identical
suite against the production database engine; the schema is created and
dropped around every test.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (  # noqa: F401  (import registers every model on Base's metadata)
    AuditEvent,
    ClassificationRun,
    CustomerConfig,
    Draft,
    Incident,
    Role,
    User,
)

PASSWORD = "password123"
WEBHOOK_TOKEN = "test-webhook-token"
USERS = {
    "analyst": ("analyst@example.com", "Alice Analyst", Role.ANALYST),
    "compliance": ("compliance@example.com", "Cara Compliance", Role.COMPLIANCE),
    "admin": ("admin@example.com", "Ada Admin", Role.ADMIN),
}

DB_OVERRIDE = os.environ.get("CORVIN_TEST_DATABASE_URL")


def reset_runtime_caches() -> None:
    from app.config import get_settings
    from app.database import get_engine, get_session_factory

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture()
def db_session():
    """A bare SQLAlchemy session on a fresh schema, for service-level tests."""
    engine = create_engine(DB_OVERRIDE or "sqlite:///:memory:", future=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """Point the app at a scratch database with known secrets and no LLM key."""
    monkeypatch.setenv("DATABASE_URL", DB_OVERRIDE or f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("WEBHOOK_TOKEN", WEBHOOK_TOKEN)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reset_runtime_caches()

    from app.database import get_engine

    Base.metadata.drop_all(get_engine())
    yield
    engine = get_engine()
    Base.metadata.drop_all(engine)
    engine.dispose()
    reset_runtime_caches()


@pytest.fixture()
def app_client(app_env):
    """The FastAPI app on a fresh schema with one user per role seeded."""
    from app.api import webhook_auth
    from app.auth.security import hash_password
    from app.database import get_engine, get_session_factory
    from app.main import app

    Base.metadata.create_all(get_engine())
    session = get_session_factory()()
    for email, name, role in USERS.values():
        session.add(User(email=email, full_name=name, role=role, hashed_password=hash_password(PASSWORD)))
    session.commit()
    session.close()
    webhook_auth._request_log.clear()

    with TestClient(app) as client:
        yield client


def bearer(client: TestClient, role: str) -> dict[str, str]:
    email = USERS[role][0]
    resp = client.post("/auth/token", data={"username": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


DEMO_WEBHOOK_PAYLOAD = {
    "title": "Phishing-borne exfiltration of customer records",
    "description": "A mailbox was compromised via a phishing link; a CRM export was exfiltrated.",
    "source_system": "phishing-scanner",
    "source_reference": "PS-0001",
    "detected_at": "2026-03-10T08:00:00Z",
    "awareness_at": "2026-03-10T08:15:00Z",
    "facts": {
        "affected_clients_pct": 12,
        "critical_services_affected": True,
        "downtime_minutes": 45,
        "member_states_affected_count": 1,
        "data_loss_confidentiality": True,
        "economic_impact_amount_eur": 150000,
        "personal_data_involved": True,
        "breach_likely_risk_to_individuals": True,
        "breach_likely_high_risk_to_individuals": True,
        "data_subjects_affected_count": 4300,
        "severe_operational_disruption": False,
        "significant_financial_loss": False,
        "affects_other_persons_considerable_damage": False,
    },
}


def post_webhook(client: TestClient, payload: dict | None = None) -> dict:
    resp = client.post(
        "/webhook/incidents", json=payload or DEMO_WEBHOOK_PAYLOAD, headers={"X-Webhook-Token": WEBHOOK_TOKEN}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def classify_and_confirm(client: TestClient, incident_id: str, headers: dict) -> dict:
    run = client.post(f"/api/incidents/{incident_id}/classify", headers=headers).json()[
        "latest_classification"
    ]
    resp = client.post(
        f"/api/incidents/{incident_id}/classify/confirm",
        json={"classification_run_id": run["id"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()
