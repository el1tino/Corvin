from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base

SINGLETON_ID = "default"


class CustomerConfig(Base):
    """Single-tenant configuration.

    The MVP is explicitly single-tenant (see build spec's out-of-scope
    list), so this is a one-row table rather than a per-customer table --
    multi-tenancy is a Stage 3 concern with its own migration.
    """

    __tablename__ = "customer_config"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=SINGLETON_ID)

    entity_name: Mapped[str] = mapped_column(String(200), default="")
    member_state: Mapped[str] = mapped_column(String(2), default="")
    default_timezone: Mapped[str] = mapped_column(String(64), default="Europe/Brussels")

    dora_authority_name: Mapped[str] = mapped_column(String(200), default="")
    dora_authority_contact: Mapped[str] = mapped_column(String(200), default="")

    nis2_csirt_or_authority_name: Mapped[str] = mapped_column(String(200), default="")
    nis2_csirt_or_authority_contact: Mapped[str] = mapped_column(String(200), default="")

    gdpr_supervisory_authority_name: Mapped[str] = mapped_column(String(200), default="")
    gdpr_supervisory_authority_contact: Mapped[str] = mapped_column(String(200), default="")

    # Data-residency: hosting region is a visible product feature (DORA/NIS2
    # selling point, not just GDPR). allow_non_eu_llm mirrors the env-level
    # default but can be confirmed/overridden per deployment by an admin.
    hosting_region: Mapped[str] = mapped_column(String(50), default="EU")
    allow_non_eu_llm: Mapped[bool] = mapped_column(Boolean, default=False)
