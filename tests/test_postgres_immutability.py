"""The audit table's second layer of tamper evidence lives in Postgres
itself (rules in migration 0001), so it can only be exercised against a
real Postgres. Skipped on SQLite; CI runs it in the Postgres job."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.audit.service import append_event, verify_full_trail
from app.models import Incident, IncidentSource

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    not os.environ.get("CORVIN_TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="database-level rules only exist on Postgres",
)


def test_audit_rows_survive_raw_sql_update_and_delete(app_env):
    from app.database import get_session_factory

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")

    db = get_session_factory()()
    try:
        incident = Incident(title="Immutable", source=IncidentSource.MANUAL, facts={})
        db.add(incident)
        db.commit()
        append_event(db, event_type="incident.created", summary="original", incident_id=incident.id)
        db.commit()

        # A client with direct SQL access tries to rewrite and then erase history.
        db.execute(text("UPDATE audit_events SET summary = 'tampered'"))
        db.execute(text("DELETE FROM audit_events"))
        db.commit()

        assert db.execute(text("SELECT summary FROM audit_events")).scalars().all() == ["original"]
        assert verify_full_trail(db).ok
    finally:
        db.close()
        command.downgrade(cfg, "base")
