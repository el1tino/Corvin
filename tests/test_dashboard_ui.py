"""Exercises the server-rendered dashboard end to end via cookie auth,
covering the same demo walkthrough as test_smoke_e2e but through the HTML
form-post routes a human actually clicks, not the JSON API.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("WEBHOOK_TOKEN", "test-webhook-token")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "dashboard.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    from app.config import get_settings
    from app.database import get_engine, get_session_factory

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    from app.auth.security import hash_password
    from app.database import Base
    from app.models import Role, User

    Base.metadata.create_all(get_engine())

    session = get_session_factory()()
    compliance = User(
        email="cara@example.com",
        full_name="Cara Compliance",
        hashed_password=hash_password("password123"),
        role=Role.COMPLIANCE,
    )
    session.add(compliance)
    session.commit()
    session.close()

    from app.main import app

    with TestClient(app) as c:
        yield c

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def test_dashboard_login_and_create_incident_flow(client):
    resp = client.post(
        "/login", data={"username": "cara@example.com", "password": "password123"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard"
    assert "corvin_session" in resp.cookies

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "No incidents yet" in resp.text

    resp = client.post(
        "/incidents/new",
        data={
            "title": "Ransomware on file server",
            "description": "Encrypted shares detected overnight",
            "detected_at": "2026-04-01T02:00",
            "awareness_at": "2026-04-01T02:30",
            "critical_services_affected": "on",
            "downtime_minutes": "400",
            "member_states_affected_count": "1",
            "economic_impact_amount_eur": "20000",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    incident_url = resp.headers["location"]
    assert incident_url.startswith("/incidents/")
    incident_id = incident_url.split("/")[-1].split("?")[0]

    resp = client.get(incident_url)
    assert resp.status_code == 200
    assert "Ransomware on file server" in resp.text

    resp = client.post(f"/incidents/{incident_id}/classify", follow_redirects=False)
    assert resp.status_code == 303

    resp = client.get(f"/incidents/{incident_id}")
    assert "DORA" in resp.text
    assert "Confirm this classification" in resp.text or "confirm this classification" in resp.text.lower()


def test_dashboard_rejects_unauthenticated_access_to_incident_pages(client):
    resp = client.get("/incidents/new", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
