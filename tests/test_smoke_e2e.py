"""The build spec's definition-of-done walkthrough, driven through the JSON
API exactly as the demo does: webhook -> classify -> confirm -> clocks ->
drafts -> edit -> export -> audit trail verifies."""

from conftest import bearer, post_webhook


def test_full_demo_walkthrough(app_client):
    admin = bearer(app_client, "admin")
    compliance = bearer(app_client, "compliance")

    resp = app_client.put(
        "/api/config",
        headers=admin,
        json={
            "entity_name": "Acme Fintech BV",
            "member_state": "NL",
            "dora_authority_name": "De Nederlandsche Bank",
            "gdpr_supervisory_authority_name": "Autoriteit Persoonsgegevens",
        },
    )
    assert resp.status_code == 200, resp.text
    assert app_client.get("/api/config", headers=compliance).json()["entity_name"] == "Acme Fintech BV"

    # 1. The phishing scanner fires the webhook.
    incident_id = post_webhook(app_client)["id"]

    # 2. It appears on the dashboard list.
    assert any(i["id"] == incident_id for i in app_client.get("/api/incidents", headers=compliance).json())

    # 3. Engine: DORA + GDPR reportable, NIS2 not.
    run = app_client.post(f"/api/incidents/{incident_id}/classify", headers=compliance).json()[
        "latest_classification"
    ]
    assert run["results"]["dora"]["result"] == "reportable"
    assert run["results"]["gdpr"]["result"] == "reportable"
    assert run["results"]["nis2"]["result"] == "not_reportable"
    assert "dora.data_losses" in run["results"]["dora"]["fired_rules"]

    # 4. Named sign-off.
    resp = app_client.post(
        f"/api/incidents/{incident_id}/classify/confirm",
        json={"classification_run_id": run["id"]},
        headers=compliance,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["confirmed_classification"]["is_confirmed"] is True
    assert data["confirmed_by"] == "Cara Compliance (compliance)"

    # 5. Clocks: DORA has three milestones, GDPR one, NIS2 none.
    clocks = data["clocks"]["frameworks"]
    assert len(clocks["dora"]["deadlines"]) == 3
    assert len(clocks["gdpr"]["deadlines"]) == 1
    assert clocks["gdpr"]["data_subject_notification_required"] is True
    assert "nis2" not in clocks
    assert data["clocks"]["nearest_deadline"]["label"] == "Initial notification"

    # 6. Drafts for the two reportable frameworks; refused for the third.
    dora_draft = app_client.post(
        f"/api/incidents/{incident_id}/drafts",
        json={"framework": "dora", "stage": "dora_initial"},
        headers=compliance,
    ).json()
    assert "Acme Fintech BV" in dora_draft["content"]
    assert dora_draft["model_used"] == "deterministic-template"
    assert dora_draft["placeholders"]
    gdpr_draft = app_client.post(
        f"/api/incidents/{incident_id}/drafts",
        json={"framework": "gdpr", "stage": "gdpr_article_33"},
        headers=compliance,
    ).json()
    assert "high risk to the rights and freedoms" in gdpr_draft["content"]
    resp = app_client.post(
        f"/api/incidents/{incident_id}/drafts",
        json={"framework": "nis2", "stage": "nis2_early_warning"},
        headers=compliance,
    )
    assert resp.status_code == 409

    # 7. Edit one placeholder.
    edited = dora_draft["content"].replace(dora_draft["placeholders"][0], "resolved by hand", 1)
    resp = app_client.patch(
        f"/api/incidents/{incident_id}/drafts/{dora_draft['id']}",
        json={"content": edited},
        headers=compliance,
    )
    assert resp.status_code == 200
    assert len(resp.json()["placeholders"]) == len(dora_draft["placeholders"]) - 1

    # 8. Export both as PDF.
    for draft in (dora_draft, gdpr_draft):
        resp = app_client.post(
            f"/api/incidents/{incident_id}/drafts/{draft['id']}/export?fmt=pdf", headers=compliance
        )
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"
        assert resp.headers["content-disposition"].endswith('.pdf"')

    # 9. Audit trail: every step, attributed, chain intact.
    audit = app_client.get(f"/api/incidents/{incident_id}/audit", headers=compliance).json()
    assert audit["chain_integrity"]["ok"] is True
    types = [e["event_type"] for e in audit["timeline"]]
    assert types[0] == "incident.created"
    assert audit["timeline"][0]["actor"] == "webhook:phishing-scanner"
    assert types.count("draft.generated") == 2
    assert types.count("draft.exported") == 2
    assert "classification.confirmed" in types and "draft.edited" in types
    assert all(e["actor"] == "Cara Compliance (compliance)" for e in audit["timeline"][1:])
