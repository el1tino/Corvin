import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
# Import every model module so they're registered on Base's mapper registry
# before create_all() / relationship configuration runs.
from app.models import (  # noqa: F401
    AuditEvent,
    ClassificationRun,
    CustomerConfig,
    Draft,
    Incident,
    User,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
