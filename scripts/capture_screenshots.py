"""Regenerate the README screenshots in docs/screenshots/.

Boots the app against a throwaway SQLite database, seeds the demo users,
drives the demo walkthrough through the JSON API (webhook -> classify ->
confirm -> drafts), then photographs the dashboard and the incident page
with a headless Chromium via Playwright.

Usage:
    pip install playwright requests && python -m scripts.capture_screenshots

Only needed when the UI changes; the images are committed.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
WEBHOOK_TOKEN = "screenshot-webhook-token"
PASSWORD = "CorvinDemo!2026"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(url, timeout=1).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"Server at {url} did not come up")


def _seed_demo_incident(base: str) -> str:
    token = requests.post(
        f"{base}/auth/token", data={"username": "compliance@corvin.demo", "password": PASSWORD}, timeout=5
    ).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    incident = requests.post(
        f"{base}/webhook/incidents",
        headers={"X-Webhook-Token": WEBHOOK_TOKEN},
        json={
            "title": "Phishing-borne exfiltration of customer CRM export",
            "description": (
                "A finance team mailbox was compromised via a credential-phishing link. The attacker used "
                "it to pull a CRM export containing customer records before the account was disabled."
            ),
            "source_system": "phishing-scanner",
            "source_reference": "PS-2026-0913-0042",
            "detected_at": "2026-09-13T06:52:00Z",
            "awareness_at": "2026-09-13T07:10:00Z",
            "facts": {
                "affected_clients_pct": 12,
                "critical_services_affected": True,
                "downtime_minutes": 45,
                "member_states_affected_count": 1,
                "data_loss_confidentiality": True,
                "data_loss_integrity": False,
                "data_loss_availability": False,
                "data_loss_authenticity": False,
                "economic_impact_amount_eur": 150000,
                "personal_data_involved": True,
                "breach_likely_risk_to_individuals": True,
                "breach_likely_high_risk_to_individuals": True,
                "data_subjects_affected_count": 4300,
                "severe_operational_disruption": False,
                "significant_financial_loss": False,
                "affects_other_persons_considerable_damage": False,
            },
        },
        timeout=5,
    ).json()
    incident_id = incident["id"]

    # A second, quieter incident so the dashboard shows more than one row.
    requests.post(
        f"{base}/webhook/incidents",
        headers={"X-Webhook-Token": WEBHOOK_TOKEN},
        json={
            "title": "Unusual outbound traffic spike from reporting database",
            "source_system": "wazuh",
            "source_reference": "WZ-118823",
            "detected_at": "2026-09-13T02:14:00Z",
            "facts": {},
        },
        timeout=5,
    )

    run = requests.post(f"{base}/api/incidents/{incident_id}/classify", headers=auth, timeout=5).json()
    requests.post(
        f"{base}/api/incidents/{incident_id}/classify/confirm",
        headers=auth,
        json={"classification_run_id": run["latest_classification"]["id"]},
        timeout=5,
    )
    for framework, stage in (("dora", "dora_initial"), ("gdpr", "gdpr_article_33")):
        requests.post(
            f"{base}/api/incidents/{incident_id}/drafts",
            headers=auth,
            json={"framework": framework, "stage": stage},
            timeout=10,
        )
    return incident_id


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    base = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite:///{tmp}/screenshots.db",
            "WEBHOOK_TOKEN": WEBHOOK_TOKEN,
            "JWT_SECRET_KEY": "screenshot-secret",
            "DEFAULT_TIMEZONE": "Europe/Amsterdam",
        }
        subprocess.run([sys.executable, "-m", "scripts.demo_seed"], env=env, check=True, capture_output=True)
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
            env=env,
        )
        try:
            _wait_for(f"{base}/healthz")
            incident_id = _seed_demo_incident(base)

            with sync_playwright() as pw:
                # CORVIN_CHROMIUM lets a machine with a preinstalled Chromium skip
                # `playwright install` (e.g. sandboxes with /opt/pw-browsers).
                browser = pw.chromium.launch(executable_path=os.environ.get("CORVIN_CHROMIUM") or None)
                page = browser.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2)
                page.goto(f"{base}/login")
                page.fill("input[name=username]", "compliance@corvin.demo")
                page.fill("input[name=password]", PASSWORD)
                page.click("button[type=submit]")
                page.wait_for_url(f"{base}/dashboard")
                page.screenshot(path=str(OUT_DIR / "dashboard.png"))

                page.goto(f"{base}/incidents/{incident_id}")
                page.screenshot(path=str(OUT_DIR / "incident.png"), full_page=True)
                cards = page.locator(".container > .card")
                cards.filter(has_text="Run classification engine").screenshot(
                    path=str(OUT_DIR / "classification.png")
                )
                cards.filter(has_text="Deadline clocks").screenshot(path=str(OUT_DIR / "clocks.png"))
                cards.filter(has_text="Audit trail").screenshot(path=str(OUT_DIR / "audit.png"))
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)

    print(f"Wrote screenshots to {OUT_DIR}")


if __name__ == "__main__":
    main()
