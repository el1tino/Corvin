"""Small guards that are easy to break silently: the production secret
check, UTC normalisation at the DB boundary, and clock helpers' defaults."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.clocks.utils import is_overdue, remaining
from app.config import Settings
from app.models.types import UTCDateTime


def test_placeholder_secrets_are_named():
    assert Settings().insecure_defaults_in_use() == ["JWT_SECRET_KEY", "WEBHOOK_TOKEN"]
    assert Settings(jwt_secret_key="real", webhook_token="real").insecure_defaults_in_use() == []
    assert Settings(app_env="Production").is_production


def test_app_refuses_to_start_in_production_with_placeholder_secrets(app_env, monkeypatch):
    from conftest import reset_runtime_caches

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET_KEY")
    reset_runtime_caches()
    from app.main import app

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"), TestClient(app):
        pass


def test_demo_seed_refuses_to_run_in_production(app_env, monkeypatch):
    from conftest import reset_runtime_caches
    from sqlalchemy import inspect

    from app.database import get_engine
    from scripts import demo_seed

    monkeypatch.setenv("APP_ENV", "production")
    reset_runtime_caches()
    with pytest.raises(demo_seed.DemoSeedRefused, match="production"):
        demo_seed.main()
    # Refused before touching the database: not even the tables were created.
    assert "users" not in inspect(get_engine()).get_table_names()


def test_demo_seed_runs_outside_production(app_env):
    from app.database import get_session_factory
    from app.models import User
    from scripts import demo_seed

    demo_seed.main()
    db = get_session_factory()()
    try:
        emails = {u.email for u in db.query(User).all()}
    finally:
        db.close()
    assert {email for email, _, _ in demo_seed.DEMO_USERS} <= emails


def test_utc_datetime_rejects_naive_writes_and_normalises_reads():
    column = UTCDateTime()
    with pytest.raises(ValueError, match="Naive datetime"):
        column.process_bind_param(datetime(2026, 1, 1), dialect=None)
    assert column.process_bind_param(None, dialect=None) is None
    read_back = column.process_result_value(datetime(2026, 1, 1, 12, 0), dialect=None)
    assert read_back.tzinfo is UTC
    assert column.process_result_value(None, dialect=None) is None


def test_clock_helpers_default_to_now():
    past = datetime.now(UTC) - timedelta(hours=1)
    future = datetime.now(UTC) + timedelta(hours=1)
    assert is_overdue(past) and not is_overdue(future)
    assert remaining(future) > timedelta(minutes=59)
