"""Example integration: feeding Corvin from a phishing/email-threat scanner.

This is the reference implementation for the build spec's demo scenario:
"a confirmed phishing-borne data exfiltration should arrive as a
pre-populated incident with personal-data-involved already set, so the
GDPR path lights up automatically."

It is deliberately a plain `requests` script, not a Corvin module -- it
models what a *separate* system (the builder's existing Python client-server
email/threat scanner, or any other SIEM/EDR) would run when it confirms a
phishing incident involving data exfiltration. Point CORVIN_URL at a
running Corvin instance and adapt `build_payload()` to pull real fields
from your scanner's own alert data.

Usage:
    CORVIN_URL=http://localhost:8000 CORVIN_WEBHOOK_TOKEN=change-me \\
        python scripts/phishing_scanner_webhook_client.py
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime

import requests


def build_payload(*, affected_mailboxes: int, records_exfiltrated: int) -> dict:
    now = datetime.now(UTC)
    return {
        "title": "Phishing-borne data exfiltration (customer CRM export)",
        "description": (
            "The scanner flagged an inbound phishing email that led to a mailbox compromise. "
            "Forensics confirmed the attacker used the compromised mailbox to exfiltrate a CRM "
            "export containing customer records before the account was disabled."
        ),
        "source_system": "phishing-scanner",
        "source_reference": str(uuid.uuid4()),
        # In a real integration these come from the scanner's own detection
        # and triage timestamps -- they are usually different moments.
        "detected_at": now.isoformat(),
        "awareness_at": now.isoformat(),
        "facts": {
            # The scanner already knows this was a data-exfiltration event,
            # so it pre-populates the GDPR-relevant facts -- the whole point
            # of a direct SOC-to-reporting integration versus a human
            # re-typing the incident into a GRC register later.
            "personal_data_involved": True,
            "breach_likely_risk_to_individuals": True,
            "breach_likely_high_risk_to_individuals": records_exfiltrated > 1000,
            "data_subjects_affected_count": records_exfiltrated,
            "data_loss_confidentiality": True,
            "critical_services_affected": False,
            "affected_clients_pct": round(min(affected_mailboxes / 500 * 100, 100), 1),
            "downtime_minutes": 0,
            "member_states_affected_count": 1,
            "economic_impact_amount_eur": 0,
            "severe_operational_disruption": False,
            "significant_financial_loss": False,
            "affects_other_persons_considerable_damage": False,
        },
    }


def send(payload: dict) -> requests.Response:
    base_url = os.environ.get("CORVIN_URL", "http://localhost:8000")
    token = os.environ.get("CORVIN_WEBHOOK_TOKEN")
    if not token:
        print(
            "Set CORVIN_WEBHOOK_TOKEN to the shared webhook secret configured on the server.", file=sys.stderr
        )
        sys.exit(1)

    return requests.post(
        f"{base_url}/webhook/incidents",
        json=payload,
        headers={"X-Webhook-Token": token},
        timeout=10,
    )


def main() -> None:
    payload = build_payload(affected_mailboxes=1, records_exfiltrated=4300)
    response = send(payload)
    print(f"POST /webhook/incidents -> {response.status_code}")
    print(response.json() if response.ok else response.text)


if __name__ == "__main__":
    main()
