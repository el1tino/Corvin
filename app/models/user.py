from __future__ import annotations

import enum

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .base import Timestamped, UUIDPk


class Role(str, enum.Enum):
    ANALYST = "analyst"       # SOC analyst / security lead: confirms incidents
    COMPLIANCE = "compliance"  # GRC lead / DPO: owns regulatory filings
    ADMIN = "admin"            # tunes rules, manages users and customer config


class User(Base, UUIDPk, Timestamped):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def display_label(self) -> str:
        return f"{self.full_name} ({self.role.value})"
