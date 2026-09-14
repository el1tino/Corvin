"""JSON API behaviour beyond the happy path: auth, role separation,
validation, conflict handling, rate limiting and downloads."""

from conftest import DEMO_WEBHOOK_PAYLOAD, WEBHOOK_TOKEN, bearer, classify_and_confirm, post_webhook

MANUAL_INCIDENT = {
    "title": "Payments API outage",
    "description": "Failed migration took payments down.",
    "awareness_at": "2026-04-01T02:30:00Z",
    "facts": {"critical_services_affected": True, "downtime_minutes": 400},
}


# --- auth -------------------------------------------------------------------


def test_missing_or_invalid_token_is_401(app_client):
    assert app_client.get("/api/incidents").status_code == 401
    assert app_client.get("/api/incidents", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_wrong_password_is_401(app_client):
    resp = app_client.post("/auth/token", data={"username": "admin@example.com", "password": "wrong"})
    assert resp.status_code == 401


def test_me_reports_the_logged_in_user_and_logout_clears_cookie(app_client):
    headers = bearer(app_client, "analyst")
    me = app_client.get("/auth/me", headers=headers).json()
    assert me["email"] == "analyst@example.com" and me["role"] == "analyst"
    resp = app_client.post("/auth/logout")
    assert resp.status_code == 200
    assert 'corvin_session=""' in resp.headers.get("set-cookie", "")


def test_role_separation(app_client):
    analyst = bearer(app_client, "analyst")
    compliance = bearer(app_client, "compliance")
    incident_id = post_webhook(app_client)["id"]
    classify_and_confirm(app_client, incident_id, analyst)

    # Analysts confirm; only compliance/admin draft.
    resp = app_client.post(
        f"/api/incidents/{incident_id}/drafts",
        json={"framework": "dora", "stage": "dora_initial"},
        headers=analyst,
    )
    assert resp.status_code == 403
    # Only admins change customer configuration.
    assert app_client.put("/api/config", json={"entity_name": "x"}, headers=compliance).status_code == 403
    assert app_client.get("/api/config", headers=compliance).status_code == 200


# --- incidents --------------------------------------------------------------


def test_manual_incident_lifecycle(app_client):
    analyst = bearer(app_client, "analyst")
    created = app_client.post("/api/incidents", json=MANUAL_INCIDENT, headers=analyst)
    assert created.status_code == 201, created.text
    incident = created.json()
    assert incident["source"] == "manual" and incident["status"] == "new"

    fetched = app_client.get(f"/api/incidents/{incident['id']}", headers=analyst).json()
    assert fetched["facts"]["downtime_minutes"] == 400

    run = app_client.post(f"/api/incidents/{incident['id']}/classify", headers=analyst).json()
    assert run["status"] == "pending_confirmation"
    assert run["latest_classification"]["results"]["dora"]["result"] == "reportable"
    assert run["latest_classification"]["results"]["gdpr"]["result"] == "needs_human_input"

    # Editing facts after a run makes that run stale.
    resp = app_client.patch(
        f"/api/incidents/{incident['id']}/facts",
        json={"facts": {"critical_services_affected": True, "downtime_minutes": 10}},
        headers=analyst,
    )
    assert resp.status_code == 200
    resp = app_client.post(
        f"/api/incidents/{incident['id']}/classify/confirm",
        json={"classification_run_id": run["latest_classification"]["id"]},
        headers=analyst,
    )
    assert resp.status_code == 409
    resp = app_client.post(
        f"/api/incidents/{incident['id']}/classify/confirm",
        json={"classification_run_id": "does-not-exist"},
        headers=analyst,
    )
    assert resp.status_code == 404

    closed = app_client.post(f"/api/incidents/{incident['id']}/close", headers=analyst).json()
    assert closed["status"] == "closed"


def test_unknown_incident_is_404(app_client):
    assert app_client.get("/api/incidents/nope", headers=bearer(app_client, "analyst")).status_code == 404


# --- webhook ----------------------------------------------------------------


def test_webhook_rejects_wrong_token_and_invalid_facts(app_client):
    resp = app_client.post(
        "/webhook/incidents", json=DEMO_WEBHOOK_PAYLOAD, headers={"X-Webhook-Token": "bad"}
    )
    assert resp.status_code == 401
    bad = {**DEMO_WEBHOOK_PAYLOAD, "facts": {"affected_clients_pct": 150}}
    resp = app_client.post("/webhook/incidents", json=bad, headers={"X-Webhook-Token": WEBHOOK_TOKEN})
    assert resp.status_code == 422


def test_webhook_keeps_unknown_fields_in_raw_payload_and_engine_asks_for_the_rest(app_client):
    minimal = {"title": "EDR alert", "source_system": "wazuh", "facts": {"custom_severity": "high"}}
    incident_id = post_webhook(app_client, minimal)["id"]
    headers = bearer(app_client, "analyst")
    data = app_client.post(f"/api/incidents/{incident_id}/classify", headers=headers).json()
    assert data["facts"]["custom_severity"] == "high"
    assert all(r["result"] == "needs_human_input" for r in data["latest_classification"]["results"].values())


def test_webhook_rate_limit(app_client):
    from app.config import get_settings

    get_settings().webhook_rate_limit_per_minute = 2
    post_webhook(app_client)
    post_webhook(app_client)
    resp = app_client.post(
        "/webhook/incidents", json=DEMO_WEBHOOK_PAYLOAD, headers={"X-Webhook-Token": WEBHOOK_TOKEN}
    )
    assert resp.status_code == 429


# --- drafts and audit --------------------------------------------------------


def test_draft_preconditions_submission_and_export_validation(app_client):
    compliance = bearer(app_client, "compliance")
    incident_id = post_webhook(app_client)["id"]

    # Nothing can be drafted before sign-off.
    resp = app_client.post(
        f"/api/incidents/{incident_id}/drafts",
        json={"framework": "dora", "stage": "dora_initial"},
        headers=compliance,
    )
    assert resp.status_code == 409
    classify_and_confirm(app_client, incident_id, compliance)

    resp = app_client.post(
        f"/api/incidents/{incident_id}/drafts",
        json={"framework": "dora", "stage": "nis2_final"},
        headers=compliance,
    )
    assert resp.status_code == 409  # stage does not belong to the framework

    draft = app_client.post(
        f"/api/incidents/{incident_id}/drafts",
        json={"framework": "dora", "stage": "dora_initial"},
        headers=compliance,
    ).json()
    base = f"/api/incidents/{incident_id}/drafts/{draft['id']}"

    assert app_client.post(f"{base}/export?fmt=txt", headers=compliance).status_code == 400
    docx = app_client.post(f"{base}/export?fmt=docx", headers=compliance)
    assert docx.status_code == 200 and docx.content[:2] == b"PK"

    submitted = app_client.post(f"{base}/submitted", headers=compliance)
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted" and submitted.json()["submitted_at"]
    assert app_client.post(f"{base}/submitted", headers=compliance).status_code == 409

    # The intermediate clock is now anchored on the real submission, not provisional.
    incident = app_client.get(f"/api/incidents/{incident_id}", headers=compliance).json()
    intermediate = next(
        d for d in incident["clocks"]["frameworks"]["dora"]["deadlines"] if "Intermediate" in d["label"]
    )
    assert intermediate["provisional"] is False

    assert app_client.get(f"/api/incidents/{incident_id}/drafts/nope", headers=compliance).status_code in (
        404,
        405,
    )
    assert (
        app_client.patch(
            f"/api/incidents/{incident_id}/drafts/nope", json={"content": "x"}, headers=compliance
        ).status_code
        == 404
    )

    export = app_client.get(f"/api/incidents/{incident_id}/audit/export", headers=compliance)
    assert export.status_code == 200
    assert export.headers["content-disposition"].endswith('audit-trail.json"')
    assert export.json()["chain_integrity"]["ok"] is True
    assert "draft.submitted" in [e["event_type"] for e in export.json()["events"]]
