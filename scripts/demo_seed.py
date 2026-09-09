"""Idempotent demo seed: creates the three role accounts and a plausible
customer configuration for a Dutch fintech, so a fresh `docker compose up`
has something to log into immediately.

Safe to run repeatedly (e.g. on every container start) -- it only inserts
rows that don't already exist.

Usage: python -m scripts.demo_seed
"""
from __future__ import annotations

from app.auth.security import hash_password
from app.database import Base, get_engine, get_session_factory
from app.models import CustomerConfig, Role, User
from app.models.customer_config import SINGLETON_ID

DEMO_USERS = [
    ("analyst@corvin.demo", "Alice Analyst", Role.ANALYST),
    ("compliance@corvin.demo", "Cara Compliance", Role.COMPLIANCE),
    ("admin@corvin.demo", "Adil Admin", Role.ADMIN),
]
DEMO_PASSWORD = "CorvinDemo!2026"


def main() -> None:
    Base.metadata.create_all(get_engine())
    db = get_session_factory()()
    try:
        for email, full_name, role in DEMO_USERS:
            existing = db.query(User).filter(User.email == email).one_or_none()
            if existing is None:
                db.add(User(email=email, full_name=full_name, role=role, hashed_password=hash_password(DEMO_PASSWORD)))
                print(f"Created demo user: {email} / {DEMO_PASSWORD} ({role.value})")

        config = db.get(CustomerConfig, SINGLETON_ID)
        if config is None:
            config = CustomerConfig(
                id=SINGLETON_ID,
                entity_name="Acme Fintech BV",
                member_state="NL",
                default_timezone="Europe/Amsterdam",
                dora_authority_name="De Nederlandsche Bank (DNB)",
                dora_authority_contact="dora-meldingen@dnb.nl",
                nis2_csirt_or_authority_name="Nationaal Cyber Security Centrum (NCSC-NL)",
                nis2_csirt_or_authority_contact="cert@ncsc.nl",
                gdpr_supervisory_authority_name="Autoriteit Persoonsgegevens",
                gdpr_supervisory_authority_contact="meldloket@autoriteitpersoonsgegevens.nl",
                hosting_region="EU",
                allow_non_eu_llm=False,
            )
            db.add(config)
            print("Created demo customer configuration for Acme Fintech BV (NL).")

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
