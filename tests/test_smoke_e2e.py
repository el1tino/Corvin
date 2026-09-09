"""End-to-end smoke test driving the FastAPI app the same way the demo
walkthrough does: webhook intake -> classify -> confirm -> clocks ->
generate + export a draft -> verify the audit trail.

Uses a scratch SQLite file DB (not :memory:) so every request in the
TestClient shares the same schema across the lifetime of the test.
"""
import os
import uuid

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("WEBHOOK_TOKEN", "test-webhook-token")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "smoke.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    from app.config import get_settings
    from app.database import get_engine, get_session_factory

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    from app.database import Base
    from app.models import User, Role
    from app.auth.security import hash_password

    Base.metadata.create_all(get_engine())

    session = get_session_factory()()
    admin = User(
        email="admin@example.com",
        full_name="Ada Admin",
        hashed_password=hash_password("password123"),
        role=Role.ADMIN,
    )
    compliance = User(
        email="compliance@example.com",
        full_name="Cara Compliance",
        hashed_password=hash_password("password123"),
        role=Role.COMPLIANCE,
    )
    session.add_all([admin, compliance])
    session.commit()
    session.close()

    from app.main import app

    with TestClient(app) as c:
        yield c

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _login(client, email, password="password123"):
    resp = client.post("/auth/token", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_full_demo_walkthrough(client):
    admin_token = _login(client, "admin@example.com")
    compliance_token = _login(client, "compliance@example.com")

    # Admin configures the customer's authorities up front.
    config_resp = client.put(
        "/api/config",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "entity_name": "Acme Fintech BV",
            "member_state": "NL",
            "dora_authority_name": "De Nederlandsche Bank",
            "dora_authority_contact": "dora@dnb.nl",
            "gdpr_supervisory_authority_name": "Autoriteit Persoonsgegevens",
            "gdpr_supervisory_authority_contact": "meldloket@autoriteitpersoonsgegevens.nl",
        },
    )
    assert config_resp.status_code == 200, config_resp.text

    # 1. Webhook fires from the phishing scanner: a confirmed phishing-borne
    # data exfiltration, pre-populated with personal-data-involved set.
    webhook_payload = {
        "title": "Phishing-borne exfiltration of customer records",
        "description": "A staff member's mailbox was compromised via a phishing link; attacker exfiltrated a CRM export.",
        "source_system": "phishing-scanner",
        "source_reference": str(uuid.uuid4()),
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
    resp = client.post(
        "/webhook/incidents", json=webhook_payload, headers={"X-Webhook-Token": "test-webhook-token"}
    )
    assert resp.status_code == 201, resp.text
    incident = resp.json()
    incident_id = incident["id"]

    # 2. Incident appears on the dashboard.
    resp = client.get("/api/incidents", headers={"Authorization": f"Bearer {compliance_token}"})
    assert resp.status_code == 200
    assert any(i["id"] == incident_id for i in resp.json())

    # 3. Engine flags DORA + GDPR as reportable, NIS2 not reportable.
    resp = client.post(
        f"/api/incidents/{incident_id}/classify", headers={"Authorization": f"Bearer {compliance_token}"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    run = data["latest_classification"]
    assert run["results"]["dora"]["result"] == "reportable"
    assert run["results"]["gdpr"]["result"] == "reportable"
    assert run["results"]["nis2"]["result"] == "not_reportable"
    assert any("dora.data_losses" in r for r in run["results"]["dora"]["fired_rules"])
    run_id = run["id"]

    # 4. The analyst confirms the classification.
    resp = client.post(
        f"/api/incidents/{incident_id}/classify/confirm",
        json={"classification_run_id": run_id},
        headers={"Authorization": f"Bearer {compliance_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["confirmed_classification"]["is_confirmed"] is True

    # 5. Three countdown clocks appear (DORA has 3 deadlines, GDPR has 1).
    clocks = data["clocks"]["frameworks"]
    assert "dora" in clocks and len(clocks["dora"]["deadlines"]) == 3
    assert "gdpr" in clocks and len(clocks["gdpr"]["deadlines"]) == 1
    assert "nis2" not in clocks  # not reportable -> no clock shown
    assert data["clocks"]["nearest_deadline"] is not None

    # 6. Compliance lead generates the DORA initial notification and the
    # GDPR notification as drafts.
    resp = client.post(
        f"/api/incidents/{incident_id}/drafts",
        json={"framework": "dora", "stage": "dora_initial"},
        headers={"Authorization": f"Bearer {compliance_token}"},
    )
    assert resp.status_code == 201, resp.text
    dora_draft = resp.json()
    assert "Acme Fintech BV" in dora_draft["content"]
    assert len(dora_draft["placeholders"]) > 0

    resp = client.post(
        f"/api/incidents/{incident_id}/drafts",
        json={"framework": "gdpr", "stage": "gdpr_article_33"},
        headers={"Authorization": f"Bearer {compliance_token}"},
    )
    assert resp.status_code == 201, resp.text
    gdpr_draft = resp.json()

    # A draft for a not-reportable framework must be refused.
    resp = client.post(
        f"/api/incidents/{incident_id}/drafts",
        json={"framework": "nis2", "stage": "nis2_early_warning"},
        headers={"Authorization": f"Bearer {compliance_token}"},
    )
    assert resp.status_code == 409

    # 7. Edit one placeholder on the DORA draft.
    edited_content = dora_draft["content"].replace(
        "[PLACEHOLDER: entity legal name]", "Acme Fintech BV (edited)", 1
    )
    resp = client.patch(
        f"/api/incidents/{incident_id}/drafts/{dora_draft['id']}",
        json={"content": edited_content},
        headers={"Authorization": f"Bearer {compliance_token}"},
    )
    assert resp.status_code == 200, resp.text

    # 8. Export both as PDF.
    resp = client.post(
        f"/api/incidents/{incident_id}/drafts/{dora_draft['id']}/export?fmt=pdf",
        headers={"Authorization": f"Bearer {compliance_token}"},
    )
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"

    resp = client.post(
        f"/api/incidents/{incident_id}/drafts/{gdpr_draft['id']}/export?fmt=pdf",
        headers={"Authorization": f"Bearer {compliance_token}"},
    )
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"

    # 9. The audit trail shows every step with timestamps and the
    # responsible user, and verifies as tamper-free.
    resp = client.get(
        f"/api/incidents/{incident_id}/audit", headers={"Authorization": f"Bearer {compliance_token}"}
    )
    assert resp.status_code == 200
    audit = resp.json()
    assert audit["chain_integrity"]["ok"] is True
    event_types = [e["event_type"] for e in audit["timeline"]]
    assert "incident.created" in event_types
    assert "classification.run" in event_types
    assert "classification.confirmed" in event_types
    assert event_types.count("draft.generated") == 2
    assert event_types.count("draft.exported") == 2
    assert "draft.edited" in event_types


def test_webhook_requires_correct_token(client):
    resp = client.post(
        "/webhook/incidents",
        json={"title": "x", "source_system": "test"},
        headers={"X-Webhook-Token": "wrong-token"},
    )
    assert resp.status_code == 401


def test_dashboard_requires_login_and_redirects(client):
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"] == "/login"
