# Corvin

Compliance-aware incident-response orchestrator (MVP). Incidents flow from
detection (a SIEM/EDR webhook, or manual entry) into pre-classified,
deadline-tracked DORA / NIS2 / GDPR notifications, with a tamper-evident
audit trail of every decision along the way.

Everything the engine decides is a **recommendation**. A named human must
confirm the classification before any deadline clock or draft notification
is treated as authoritative, and Corvin never submits anything to a
regulator itself -- it produces drafts and exports for a human to send.

## Architecture

```
app/
  rules_engine/   pure Python, no web deps -- DORA/NIS2/GDPR classification
                  logic, editable/versioned as YAML data (rules/*.yaml)
  clocks/         pure Python -- statutory deadline math per framework
  audit/          hash-chaining primitives + DB-backed append/verify service
  models/         SQLAlchemy ORM (Postgres)
  services/       orchestration: wires rules_engine/clocks/audit/drafting
                  to the database; both the JSON API and the dashboard's
                  HTML forms call through here, so they behave identically
  drafting/       deterministic Jinja2 templates + optional LLM polish
                  layer + DOCX/PDF export
  api/            FastAPI JSON routes (webhook, incidents, drafts, audit)
  templates/      server-rendered dashboard (Jinja2)
tests/
  fixtures/       six realistic incidents: DORA-only, GDPR-only, NIS2-only,
                  all three, none, needs-human-input
migrations/       Alembic
scripts/          demo seed data + an example phishing-scanner integration
```

`rules_engine` and `clocks` are fully unit-testable in isolation -- no
database, no FastAPI, no network. Everything else is a thin layer of
orchestration around them.

## Running it

```bash
cp .env.example .env      # edit JWT_SECRET_KEY / WEBHOOK_TOKEN for anything beyond a demo
docker compose up --build
```

This starts Postgres and the web app, runs Alembic migrations, and seeds
three demo accounts (see `scripts/demo_seed.py`):

| Email                    | Password           | Role       |
|---------------------------|---------------------|------------|
| analyst@corvin.demo       | CorvinDemo!2026      | analyst    |
| compliance@corvin.demo    | CorvinDemo!2026      | compliance |
| admin@corvin.demo         | CorvinDemo!2026      | admin      |

Open http://localhost:8000/dashboard and log in.

**Change these credentials, `JWT_SECRET_KEY` and `WEBHOOK_TOKEN` before any
real use** -- the seed script is for the demo only.

## Data residency

Hosting is EU-only by design (see `docker-compose.yml` / your own
deployment). Corvin also refuses to send incident data to a non-EU-hosted
LLM provider unless `ALLOW_NON_EU_LLM=true` is explicitly set (see
`app/drafting/llm_client.py`) -- and even without any LLM configured at
all, drafting still works via the deterministic Jinja2 template renderer,
which is a fully supported mode, not a degraded one.

## The webhook

Any SIEM, EDR, or custom scanner can feed Corvin with a single documented
endpoint:

```
POST /webhook/incidents
Header: X-Webhook-Token: <shared secret, see WEBHOOK_TOKEN in .env>
```

```json
{
  "title": "Phishing-borne data exfiltration",
  "description": "...",
  "source_system": "wazuh",
  "source_reference": "alert-12345",
  "detected_at": "2026-03-10T08:00:00Z",
  "awareness_at": "2026-03-10T08:15:00Z",
  "facts": {
    "personal_data_involved": true,
    "breach_likely_risk_to_individuals": true,
    "affected_clients_pct": 12,
    "downtime_minutes": 45
  }
}
```

Only `title` and `source_system` are required. Every entry under `facts` is
optional and unknown to the engine only means the affected framework comes
back as "needs human input" instead of a guess -- see
`app/schemas/facts.py` for the full field list the classification rules
understand, and `app/rules_engine/rules/*.yaml` for the rules themselves
(editable, versioned, reviewed against the primary legal texts as noted in
each file's `disclaimer`).

Rate limiting and the token check live in `app/api/webhook_auth.py`.

### Demo: the phishing-scanner integration

```bash
CORVIN_URL=http://localhost:8000 CORVIN_WEBHOOK_TOKEN=<your token> \
    python scripts/phishing_scanner_webhook_client.py
```

Sends a realistic "confirmed phishing-borne data exfiltration" event,
pre-populated with `personal_data_involved` already set -- so the GDPR path
lights up automatically, exactly like a real client-server email/threat
scanner would report it. Adapt `build_payload()` to your own scanner's
alert schema.

## The ten-minute demo walkthrough

1. Fire the phishing-scanner webhook (above, or via `/incidents/new` for
   manual entry).
2. The incident appears on `/dashboard`.
3. Open it; click **Run classification engine** -- DORA and GDPR come back
   `reportable` with their reasoning shown inline (which rules fired, which
   didn't, which fields are still missing); NIS2 comes back
   `not_reportable`.
4. Click **I confirm this classification** as the logged-in analyst --this
   records who confirmed it and when, and is what makes clocks/drafts
   authoritative.
5. Three countdown clocks appear (DORA: initial/intermediate/final; GDPR:
   supervisory-authority notification), each showing which UTC deadline and
   why.
6. Generate the DORA initial notification and the GDPR Article 33
   notification as drafts; edit a placeholder; export both as PDF.
7. Scroll to the audit trail: every step above appears with a timestamp and
   the responsible user, plus a link to download the full
   machine-verifiable (hash-chained) export for that incident.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/fixtures/` holds six realistic incidents (DORA-only, GDPR-only,
NIS2-only, all three, none, needs-human-input) that both exercise the
rules engine and double as sample payloads. `test_clocks.py` specifically
covers the edge cases called out in the build spec: classification more
than 20 hours after awareness (the DORA 24-hour cap), a deadline window
spanning a DST transition, and awareness being backdated after the fact.
`test_smoke_e2e.py` and `test_dashboard_ui.py` run the full demo
walkthrough above end to end, through the JSON API and the HTML dashboard
respectively.

## What's out of scope for this MVP

Multi-tenancy, MSSP white-labeling, native SIEM connectors beyond the
generic webhook, the DORA Register of Information (xBRL-CSV),
cross-framework control mapping, SSO, ML-assisted severity scoring, and any
actual submission to an authority portal. See the build spec for the
staged roadmap.
