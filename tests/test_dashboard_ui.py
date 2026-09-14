"""The server-rendered dashboard, driven through the HTML forms a human
actually submits (cookie auth), covering the same walkthrough as the JSON
API test plus the dashboard-only flows: login errors, facts editing,
recording a submission, closing, logout."""

import re

from conftest import PASSWORD, USERS


def login(client, role="compliance"):
    resp = client.post(
        "/login", data={"username": USERS[role][0], "password": PASSWORD}, follow_redirects=False
    )
    assert resp.status_code == 303 and resp.headers["location"] == "/dashboard"
    assert "corvin_session" in resp.cookies


def test_unauthenticated_pages_redirect_to_login(app_client):
    for path in ("/", "/dashboard", "/incidents/new", "/incidents/abc"):
        resp = app_client.get(path, follow_redirects=False)
        assert resp.status_code == 303
    assert app_client.get("/dashboard", follow_redirects=False).headers["location"] == "/login"


def test_bad_login_shows_error(app_client):
    resp = app_client.post("/login", data={"username": "x@y.z", "password": "no"}, follow_redirects=False)
    assert resp.status_code == 303 and "err=" in resp.headers["location"]
    assert "Incorrect email or password" in app_client.get(resp.headers["location"]).text


def test_full_walkthrough_through_the_html_forms(app_client):
    login(app_client)
    assert "No incidents yet" in app_client.get("/dashboard").text

    resp = app_client.post(
        "/incidents/new",
        data={
            "title": "Ransomware on file server",
            "description": "Encrypted shares detected overnight",
            "detected_at": "2026-04-01T02:00",
            "awareness_at": "2026-04-01T02:30",
            "critical_services_affected": "on",
            "downtime_minutes": "400",
            "affected_clients_pct": "12.5",
            "member_states_affected_count": "1",
            "economic_impact_amount_eur": "20000",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    incident_id = resp.headers["location"].split("/")[-1].split("?")[0]
    url = f"/incidents/{incident_id}"

    page = app_client.get(url).text
    assert "Ransomware on file server" in page
    assert "12.5" in page and "No classification run yet" in page

    app_client.post(f"{url}/classify", follow_redirects=False)
    page = app_client.get(url).text
    assert "I confirm this classification" in page
    run_id = re.search(r'name="run_id" value="([^"]+)"', page).group(1)

    # Editing facts invalidates the pending run.
    resp = app_client.post(
        f"{url}/facts",
        data={
            "downtime_minutes": "500",
            "critical_services_affected": "on",
            "awareness_at": "2026-04-01T02:30",
        },
        follow_redirects=False,
    )
    assert "Facts%20updated" in resp.headers["location"]
    resp = app_client.post(f"{url}/confirm", data={"run_id": run_id}, follow_redirects=False)
    assert "err=" in resp.headers["location"]

    app_client.post(f"{url}/classify", follow_redirects=False)
    run_id = re.search(r'name="run_id" value="([^"]+)"', app_client.get(url).text).group(1)
    resp = app_client.post(f"{url}/confirm", data={"run_id": run_id}, follow_redirects=False)
    assert "confirmed%20by" in resp.headers["location"]

    page = app_client.get(url).text
    assert "Deadline clocks" in page and "Initial notification" in page
    assert "Europe/Brussels" in page  # times rendered in the configured zone

    resp = app_client.post(
        f"{url}/drafts", data={"framework": "dora", "stage": "dora_initial"}, follow_redirects=False
    )
    assert "Draft%20generated" in resp.headers["location"]
    page = app_client.get(url).text
    draft_id = re.search(r"/drafts/([0-9a-f-]+)/edit", page).group(1)

    resp = app_client.post(
        f"{url}/drafts/{draft_id}/edit",
        data={"content": "# Edited\n\nNo placeholders left."},
        follow_redirects=False,
    )
    assert "Draft%20updated" in resp.headers["location"]
    assert "0 open placeholder" in app_client.get(url).text

    resp = app_client.post(f"{url}/drafts/{draft_id}/export", data={"fmt": "pdf"})
    assert resp.status_code == 200 and resp.content[:5] == b"%PDF-"

    resp = app_client.post(f"{url}/drafts/{draft_id}/submitted", follow_redirects=False)
    assert "Recorded%20as%20submitted" in resp.headers["location"]
    assert "Record as submitted" not in app_client.get(url).text

    resp = app_client.post(f"{url}/close", follow_redirects=False)
    assert "Incident%20closed" in resp.headers["location"]
    dashboard = app_client.get("/dashboard").text
    assert "Closed incidents" in dashboard and "Open incidents" in dashboard

    resp = app_client.post("/logout", follow_redirects=False)
    assert resp.headers["location"] == "/login"
    assert app_client.get("/dashboard", follow_redirects=False).status_code == 303


def test_missing_incident_and_draft_redirect_with_error(app_client):
    login(app_client, "analyst")
    resp = app_client.get("/incidents/does-not-exist", follow_redirects=False)
    assert resp.headers["location"].startswith("/dashboard?err=")
    resp = app_client.post("/incidents/x/drafts/y/edit", data={"content": "z"}, follow_redirects=False)
    assert "err=" in resp.headers["location"]
    resp = app_client.post(
        "/incidents/x/drafts", data={"framework": "dora", "stage": "dora_initial"}, follow_redirects=False
    )
    assert "err=" in resp.headers["location"]
