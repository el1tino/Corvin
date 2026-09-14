"""The Alembic migrations and the ORM must describe the same schema, so a
model change without a migration (or vice versa) fails here rather than in
production."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

ROOT = Path(__file__).resolve().parent.parent


def test_migrations_apply_cleanly_and_match_the_models(app_env):
    from app.database import Base, get_engine

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")

    engine = get_engine()
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Models and migrations have drifted: {diff}"

    command.downgrade(cfg, "base")
    with engine.connect() as conn:
        remaining = [t for t in conn.dialect.get_table_names(conn) if t != "alembic_version"]
    assert remaining == []
